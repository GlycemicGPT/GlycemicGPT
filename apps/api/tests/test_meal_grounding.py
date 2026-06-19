"""Story 50.E1: grounding -- own-history RAG recall + USDA/OFF + precedence.

Covers the two grounding mechanisms kept architecturally distinct by trust tier:
own-history recall (USER_PROVIDED) and external published facts (USDA
AUTHORITATIVE / Open Food Facts RESEARCHED); the precedence reconciliation; the
SSRF/key-handling guards on the external fetch; the clinical-retrieval exclusion;
and the cornerstone safety invariant (grounding never couples into dosing math).

Embeddings are stubbed deterministically by the autouse ``_fake_embedding_model``
conftest fixture: identical text -> identical vector (cosine distance 0), so
own-history recall is exercised without the real model. External HTTP is mocked.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from src.config import settings
from src.database import get_session_maker
from src.models.ai_provider import AIProviderConfig, AIProviderStatus, AIProviderType
from src.models.common_food import CommonFood, normalize_common_food_name
from src.models.food_record import FoodRecord, FoodRecordSource
from src.models.knowledge_chunk import KnowledgeChunk
from src.models.user import User, UserRole
from src.services import (
    food_vision,
    meal_grounding,
    meal_rag,
    nutrition_sources,
    restaurant_nutrition,
)
from src.vision.carb_contract import (
    MEAL_ESTIMATE_QUALIFIER,
    NEVER_DOSE_PROHIBITION,
    find_dosing_violations,
)

# (asyncio_mode = "auto" in pyproject -- async tests need no explicit mark.)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def _new_user(db) -> User:
    user = User(
        email=f"grounding_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role=UserRole.DIABETIC,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _new_record(
    db,
    user: User,
    description: str,
    *,
    low: float = 40,
    high: float = 55,
    corrected: tuple[float, float] | None = None,
) -> FoodRecord:
    record = FoodRecord(
        user_id=user.id,
        filename="x.png",
        file_type="png",
        file_size_bytes=10,
        storage_path=f"/uploads/food/{user.id}/x.png",
        food_description=description,
        carbs_low=low,
        carbs_high=high,
        confidence="medium",
        source=FoodRecordSource.AI_ESTIMATE,
    )
    if corrected is not None:
        record.corrected_carbs_low, record.corrected_carbs_high = corrected
        record.source = FoodRecordSource.USER_CORRECTED
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def _set_chunk_retrieved_at(food_record_id: uuid.UUID, when: datetime) -> None:
    """Pin a food-record chunk's ``retrieved_at`` so most-recent ties are stable
    (rather than racing on the sub-millisecond gap between two index calls)."""
    from sqlalchemy import update

    async with get_session_maker()() as db:
        await db.execute(
            update(KnowledgeChunk)
            .where(
                KnowledgeChunk.metadata_json["food_record_id"].astext
                == str(food_record_id)
            )
            .values(retrieved_at=when)
        )
        await db.commit()


async def _user_with_provider(db) -> User:
    user = await _new_user(db)
    db.add(
        AIProviderConfig(
            user_id=user.id,
            provider_type=AIProviderType.CLAUDE_API,
            model_name="claude-sonnet-4-5-20250929",
            status=AIProviderStatus.CONNECTED,
        )
    )
    await db.commit()
    return user


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (16, 16), (90, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _estimate_json(desc: str, low: float = 40, high: float = 55) -> str:
    return json.dumps(
        {
            "food_description": desc,
            "carbs_grams_low": low,
            "carbs_grams_high": high,
            "confidence": "medium",
        }
    )


def _mock_httpx(payload: dict, status: int = 200, *, body: bytes | None = None):
    """Patch httpx.AsyncClient.stream so the lookup gets ``payload``.

    ``_get_json`` streams the response, so we mock ``client.stream(...)`` as an
    async context manager yielding a response with ``aiter_bytes()``. Returns the
    patch context and the client mock; assert on ``client.stream.call_count`` /
    ``call_args``.
    """
    raw = body if body is not None else json.dumps(payload).encode()

    async def _aiter_bytes():
        yield raw

    resp = MagicMock()
    resp.status_code = status
    resp.aiter_bytes = _aiter_bytes

    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=resp)
    stream_cm.__aexit__ = AsyncMock(return_value=False)

    client = AsyncMock()
    client.stream = MagicMock(return_value=stream_cm)  # stream() is sync -> CM
    ctx = patch("httpx.AsyncClient")
    return ctx, client


# --------------------------------------------------------------------------- #
# Own-history RAG recall (AC1)
# --------------------------------------------------------------------------- #
class TestOwnHistoryRecall:
    async def test_index_then_recall_same_food(self):
        async with get_session_maker()() as db:
            user = await _new_user(db)
            desc = _uniq("a bowl of oatmeal with berries")
            record = await _new_record(db, user, desc, low=30, high=40)

        await meal_rag.index_food_record(record)

        recall = await meal_rag.recall_similar_meal(user.id, desc)
        assert recall is not None
        assert recall.carbs_low == 30 and recall.carbs_high == 40
        assert recall.is_corrected is False
        assert recall.food_record_id == str(record.id)
        assert recall.distance == pytest.approx(0.0, abs=1e-6)

    async def test_recall_prefers_corrected_value(self):
        async with get_session_maker()() as db:
            user = await _new_user(db)
            desc = _uniq("grilled chicken and rice")
            record = await _new_record(
                db, user, desc, low=50, high=70, corrected=(80, 90)
            )

        await meal_rag.index_food_record(record)

        recall = await meal_rag.recall_similar_meal(user.id, desc)
        assert recall is not None
        # The corrected value -- the user's truth -- is what gets recalled.
        assert recall.is_corrected is True
        assert recall.carbs_low == 80 and recall.carbs_high == 90

    async def test_different_food_does_not_match(self):
        async with get_session_maker()() as db:
            user = await _new_user(db)
            record = await _new_record(db, user, _uniq("oatmeal"), low=30, high=40)

        await meal_rag.index_food_record(record)

        recall = await meal_rag.recall_similar_meal(user.id, _uniq("ribeye steak"))
        assert recall is None

    async def test_recall_is_owner_scoped(self):
        desc = _uniq("shared dish name")
        async with get_session_maker()() as db:
            owner = await _new_user(db)
            other = await _new_user(db)
            record = await _new_record(db, owner, desc, low=20, high=25)

        await meal_rag.index_food_record(record)

        # The other user must never recall someone else's history.
        assert await meal_rag.recall_similar_meal(other.id, desc) is None
        assert await meal_rag.recall_similar_meal(owner.id, desc) is not None

    async def test_reindex_replaces_prior_chunk(self):
        async with get_session_maker()() as db:
            user = await _new_user(db)
            desc = _uniq("pasta plate")
            record = await _new_record(db, user, desc, low=40, high=55)

        await meal_rag.index_food_record(record)

        # Correct the record and re-index: recall must now reflect the new value
        # and there must be exactly one live chunk for the record.
        async with get_session_maker()() as db:
            record = await db.get(FoodRecord, record.id)
            record.corrected_carbs_low = 60
            record.corrected_carbs_high = 70
            record.source = FoodRecordSource.USER_CORRECTED
            await db.commit()
            await db.refresh(record)
        await meal_rag.index_food_record(record)

        recall = await meal_rag.recall_similar_meal(user.id, desc)
        assert recall.carbs_low == 60 and recall.carbs_high == 70

        async with get_session_maker()() as db:
            from sqlalchemy import func, select

            live = await db.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(
                    KnowledgeChunk.user_id == user.id,
                    KnowledgeChunk.source_type == meal_rag.SOURCE_TYPE_FOOD_RECORD,
                    KnowledgeChunk.metadata_json["food_record_id"].astext
                    == str(record.id),
                    KnowledgeChunk.valid_to.is_(None),
                )
            )
        assert live == 1

    async def test_common_food_indexed_as_corrected_baseline(self):
        async with get_session_maker()() as db:
            user = await _new_user(db)
            name = _uniq("My usual smoothie")
            cf = CommonFood(
                user_id=user.id,
                name=name,
                normalized_name=normalize_common_food_name(name),
                carbs_low=35,
                carbs_high=45,
            )
            db.add(cf)
            await db.commit()
            await db.refresh(cf)

        await meal_rag.index_common_food(cf)

        recall = await meal_rag.recall_similar_meal(user.id, name)
        assert recall is not None
        assert recall.common_food_id == str(cf.id)
        assert recall.is_corrected is True  # a curated baseline is the truth

    async def test_recall_breaks_distance_tie_toward_corrected(self):
        # Two own-history chunks for one food embed to an EXACT distance tie (same
        # description). The corrected one -- the user's truth -- must win. This is
        # the HIGH bug: without a deterministic order the tie resolved
        # implementation-defined, so grounding could fall back to the uncorrected
        # guess. Indexing the uncorrected one first means a naive ORDER BY distance
        # would surface it.
        #
        # Pin the CORRECTED chunk as the OLDER one so the recency fallback
        # (retrieved_at DESC) would actually prefer the uncorrected row -- only the
        # corrected-first ordering can surface the correction here. That isolates
        # the corrected-first term: drop it and this test fails on the recency tie.
        async with get_session_maker()() as db:
            user = await _new_user(db)
            desc = _uniq("turkey sandwich")
            uncorrected = await _new_record(db, user, desc, low=40, high=50)
            corrected = await _new_record(
                db, user, desc, low=40, high=50, corrected=(70, 80)
            )

        await meal_rag.index_food_record(uncorrected)
        await meal_rag.index_food_record(corrected)
        now = datetime.now(UTC)
        await _set_chunk_retrieved_at(corrected.id, now - timedelta(hours=2))
        await _set_chunk_retrieved_at(uncorrected.id, now)

        recall = await meal_rag.recall_similar_meal(user.id, desc)
        assert recall is not None
        assert recall.is_corrected is True
        assert recall.food_record_id == str(corrected.id)
        assert recall.carbs_low == 70 and recall.carbs_high == 80

    async def test_recall_tie_among_corrected_prefers_most_recent(self):
        # Two equidistant CORRECTED chunks -> the most-recently indexed wins,
        # deterministically (a later correction supersedes an earlier one).
        async with get_session_maker()() as db:
            user = await _new_user(db)
            desc = _uniq("veggie curry")
            older = await _new_record(
                db, user, desc, low=40, high=50, corrected=(60, 70)
            )
            newer = await _new_record(
                db, user, desc, low=40, high=50, corrected=(90, 100)
            )

        await meal_rag.index_food_record(older)
        await meal_rag.index_food_record(newer)
        now = datetime.now(UTC)
        await _set_chunk_retrieved_at(older.id, now - timedelta(hours=2))
        await _set_chunk_retrieved_at(newer.id, now)

        recall = await meal_rag.recall_similar_meal(user.id, desc)
        assert recall is not None
        assert recall.food_record_id == str(newer.id)
        assert recall.carbs_low == 90 and recall.carbs_high == 100

    async def test_recall_excludes_the_record_being_grounded(self):
        # A first-ever log must not recall ITSELF as own-history (self-exclusion).
        async with get_session_maker()() as db:
            user = await _new_user(db)
            desc = _uniq("first ever log")
            record = await _new_record(db, user, desc, low=30, high=40)

        await meal_rag.index_food_record(record)

        assert (
            await meal_rag.recall_similar_meal(
                user.id, desc, exclude_food_record_id=record.id
            )
            is None
        )
        # Sanity: the chunk does exist -- without the exclusion it is found.
        assert await meal_rag.recall_similar_meal(user.id, desc) is not None

    async def test_recall_excludes_self_but_finds_genuine_prior(self):
        # Excluding the re-shoot's own chunk still recalls a genuine prior log.
        async with get_session_maker()() as db:
            user = await _new_user(db)
            desc = _uniq("repeat meal")
            prior = await _new_record(
                db, user, desc, low=40, high=50, corrected=(70, 80)
            )
            reshoot = await _new_record(db, user, desc, low=45, high=55)

        await meal_rag.index_food_record(prior)
        await meal_rag.index_food_record(reshoot)

        recall = await meal_rag.recall_similar_meal(
            user.id, desc, exclude_food_record_id=reshoot.id
        )
        assert recall is not None
        assert recall.food_record_id == str(prior.id)
        assert recall.is_corrected is True
        assert recall.carbs_low == 70 and recall.carbs_high == 80

    async def test_self_exclusion_keeps_common_food_baseline(self):
        # A common-food chunk carries common_food_id, not food_record_id, so the
        # IS DISTINCT FROM exclusion must KEEP it (a NULL "!=" would wrongly drop
        # it). Excluding the record's own chunk still recalls the baseline.
        async with get_session_maker()() as db:
            user = await _new_user(db)
            name = _uniq("my saved bowl")
            cf = CommonFood(
                user_id=user.id,
                name=name,
                normalized_name=normalize_common_food_name(name),
                carbs_low=55,
                carbs_high=65,
            )
            db.add(cf)
            await db.commit()
            await db.refresh(cf)
            record = await _new_record(db, user, name, low=40, high=50)

        await meal_rag.index_common_food(cf)
        await meal_rag.index_food_record(record)

        recall = await meal_rag.recall_similar_meal(
            user.id, name, exclude_food_record_id=record.id
        )
        assert recall is not None
        assert recall.common_food_id == str(cf.id)
        assert recall.is_corrected is True


# --------------------------------------------------------------------------- #
# External sources: USDA + Open Food Facts (AC2/AC3)
# --------------------------------------------------------------------------- #
class TestUsda:
    _PAYLOAD = {
        "foods": [
            {
                "description": "Oatmeal, cooked",
                "fdcId": 123456,
                "foodNutrients": [
                    {"nutrientNumber": "203", "nutrientName": "Protein", "value": 2.0},
                    {
                        "nutrientNumber": "205",
                        "nutrientName": "Carbohydrate, by difference",
                        "value": 12.0,
                        "unitName": "G",
                    },
                ],
            }
        ]
    }

    async def test_lookup_parses_and_caches(self, monkeypatch):
        monkeypatch.setattr(settings, "usda_fdc_api_key", "TESTKEY")
        query = _uniq("oatmeal")
        ctx, client = _mock_httpx(self._PAYLOAD)
        with ctx as ac:
            ac.return_value.__aenter__.return_value = client
            first = await nutrition_sources.lookup_usda(query)
            second = await nutrition_sources.lookup_usda(query)

        assert first is not None
        assert first.source_name == "USDA FoodData Central"
        assert first.trust_tier == KnowledgeChunk.TIER_AUTHORITATIVE
        assert first.carbs_grams == 12.0
        assert first.serving == "per 100 g"
        assert "fdc-app" in (first.source_url or "")
        # Second call is served from the cache -- no second HTTP request.
        assert client.stream.call_count == 1
        assert second is not None and second.carbs_grams == 12.0

    async def test_skipped_without_api_key(self, monkeypatch):
        monkeypatch.setattr(settings, "usda_fdc_api_key", "")
        ctx, client = _mock_httpx(self._PAYLOAD)
        with ctx as ac:
            ac.return_value.__aenter__.return_value = client
            result = await nutrition_sources.lookup_usda(_uniq("anything"))
        assert result is None
        assert client.stream.call_count == 0  # no key -> no network at all

    async def test_implausible_carbs_rejected(self, monkeypatch):
        monkeypatch.setattr(settings, "usda_fdc_api_key", "TESTKEY")
        payload = {
            "foods": [
                {
                    "description": "Bad row",
                    "fdcId": 1,
                    "foodNutrients": [
                        {"nutrientNumber": "205", "value": 250.0}  # >100 g/100 g
                    ],
                }
            ]
        }
        ctx, client = _mock_httpx(payload)
        with ctx as ac:
            ac.return_value.__aenter__.return_value = client
            result = await nutrition_sources.lookup_usda(_uniq("bad"))
        assert result is None

    async def test_cache_put_is_idempotent(self):
        # Two writes for the same (source_type, query) -- e.g. concurrent
        # first-time lookups -- must not raise on the unique index; the second
        # upserts the latest value.
        query = _uniq("idempotent food")
        fact1 = nutrition_sources.NutritionFact(
            source_name="USDA FoodData Central",
            source_url="https://fdc.nal.usda.gov/x",
            trust_tier=KnowledgeChunk.TIER_AUTHORITATIVE,
            name="thing",
            carbs_grams=12.0,
            serving="per 100 g",
            disclaimer=None,
        )
        fact2 = nutrition_sources.NutritionFact(
            **{**fact1.__dict__, "carbs_grams": 20.0}
        )
        async with get_session_maker()() as db:
            await nutrition_sources._cache_put(
                db,
                source_type=meal_rag.SOURCE_TYPE_USDA,
                normalized_query=query,
                fact=fact1,
            )
            await nutrition_sources._cache_put(
                db,
                source_type=meal_rag.SOURCE_TYPE_USDA,
                normalized_query=query,
                fact=fact2,
            )
            cached = await nutrition_sources._cache_get(
                db, meal_rag.SOURCE_TYPE_USDA, query
            )
        assert (
            cached is not None and cached.carbs_grams == 20.0
        )  # updated, not rejected


class TestOpenFoodFacts:
    def _payload(self):
        return {
            "products": [
                {
                    "product_name": "Brand Cereal",
                    "carbohydrates_100g": 70.0,
                    "code": "999",
                    "url": "https://world.openfoodfacts.org/product/999",
                }
            ]
        }

    async def test_lookup_attribution_and_disclaimer(self, monkeypatch):
        monkeypatch.setattr(settings, "open_food_facts_enabled", True)
        ctx, client = _mock_httpx(self._payload())
        with ctx as ac:
            ac.return_value.__aenter__.return_value = client
            fact = await nutrition_sources.lookup_open_food_facts(_uniq("cereal"))
        assert fact is not None
        assert fact.source_name == "Open Food Facts"
        assert fact.trust_tier == KnowledgeChunk.TIER_RESEARCHED
        assert fact.carbs_grams == 70.0
        assert fact.source_url == "https://world.openfoodfacts.org/product/999"
        assert fact.disclaimer and "Open Food Facts" in fact.disclaimer
        # Story 50.H5 (AC4): the grounding disclaimer carries the canonical dosing
        # prohibition (single source of truth, shared with MEAL_ESTIMATE_QUALIFIER)
        # and never the permissive "verify before dosing". It must NOT mislabel
        # published reference data as an "AI estimate" -- only the prohibition is
        # reused, not the whole estimate qualifier.
        assert NEVER_DOSE_PROHIBITION in fact.disclaimer
        assert "verify before dosing" not in fact.disclaimer.lower()
        assert "AI estimate" not in fact.disclaimer
        assert MEAL_ESTIMATE_QUALIFIER not in fact.disclaimer

    async def test_disabled_returns_none(self, monkeypatch):
        monkeypatch.setattr(settings, "open_food_facts_enabled", False)
        ctx, client = _mock_httpx(self._payload())
        with ctx as ac:
            ac.return_value.__aenter__.return_value = client
            assert await nutrition_sources.lookup_open_food_facts(_uniq("x")) is None
        assert client.stream.call_count == 0

    async def test_malicious_product_url_rejected(self, monkeypatch):
        # A volunteer-contributed off-domain / javascript: URL must not be cited
        # verbatim; we fall back to the server-built /product/<code> URL.
        monkeypatch.setattr(settings, "open_food_facts_enabled", True)
        payload = {
            "products": [
                {
                    "product_name": "Sketchy Item",
                    "carbohydrates_100g": 20.0,
                    "code": "555",
                    "url": "javascript:alert(1)",
                }
            ]
        }
        ctx, client = _mock_httpx(payload)
        with ctx as ac:
            ac.return_value.__aenter__.return_value = client
            fact = await nutrition_sources.lookup_open_food_facts(_uniq("sketchy"))
        assert fact is not None
        assert fact.source_url == "https://world.openfoodfacts.org/product/555"

    def test_off_url_validator(self):
        ok = nutrition_sources._safe_off_citation_url(
            "https://world.openfoodfacts.org/product/1", "1"
        )
        assert ok == "https://world.openfoodfacts.org/product/1"
        # Off-domain / non-https / dangerous schemes fall back to the built URL.
        for bad in (
            "http://world.openfoodfacts.org/x",
            "https://evil.com/x",
            "javascript:x",
        ):
            assert (
                nutrition_sources._safe_off_citation_url(bad, "9")
                == "https://world.openfoodfacts.org/product/9"
            )
        # No usable url and no code -> None.
        assert nutrition_sources._safe_off_citation_url("javascript:x", None) is None


# --------------------------------------------------------------------------- #
# Security: SSRF / host allow-list on the external fetch
# --------------------------------------------------------------------------- #
class TestExternalFetchSecurity:
    def test_host_allowlist(self):
        assert nutrition_sources._host_allowed("https://api.nal.usda.gov")
        assert nutrition_sources._host_allowed("https://world.openfoodfacts.org")
        # Internal / metadata / plaintext targets are rejected.
        assert not nutrition_sources._host_allowed("http://api.nal.usda.gov")
        assert not nutrition_sources._host_allowed("https://169.254.169.254")
        assert not nutrition_sources._host_allowed("https://localhost")
        assert not nutrition_sources._host_allowed("https://evil.example.com")

    async def test_disallowed_base_url_makes_no_request(self, monkeypatch):
        monkeypatch.setattr(settings, "usda_fdc_api_key", "TESTKEY")
        monkeypatch.setattr(settings, "usda_fdc_base_url", "http://169.254.169.254")
        ctx, client = _mock_httpx({"foods": []})
        with ctx as ac:
            ac.return_value.__aenter__.return_value = client
            result = await nutrition_sources.lookup_usda(_uniq("x"))
        assert result is None
        # Guard short-circuits before any HTTP client is constructed.
        assert client.stream.call_count == 0

    async def test_request_uses_redirect_free_param_query(self, monkeypatch):
        # The search term travels as an encoded query *param*, never the path,
        # and redirects are not followed (no redirect-based SSRF).
        monkeypatch.setattr(settings, "usda_fdc_api_key", "TESTKEY")
        query = _uniq("oatmeal")  # unique -> guaranteed cache miss -> real fetch
        ctx, client = _mock_httpx(TestUsda._PAYLOAD)
        with ctx as ac:
            ac.return_value.__aenter__.return_value = client
            await nutrition_sources.lookup_usda(query)
        # AsyncClient configured with follow_redirects=False.
        _, kwargs = ac.call_args
        assert kwargs.get("follow_redirects") is False
        # The query rode in params, not interpolated into the URL path.
        _, get_kwargs = client.stream.call_args
        assert get_kwargs["params"]["query"] == query

    async def test_non_200_returns_none(self, monkeypatch):
        monkeypatch.setattr(settings, "usda_fdc_api_key", "TESTKEY")
        ctx, client = _mock_httpx({"foods": []}, status=500)
        with ctx as ac:
            ac.return_value.__aenter__.return_value = client
            assert await nutrition_sources.lookup_usda(_uniq("x")) is None

    async def test_oversized_body_rejected(self, monkeypatch):
        monkeypatch.setattr(settings, "usda_fdc_api_key", "TESTKEY")
        monkeypatch.setattr(nutrition_sources, "_MAX_RESPONSE_BYTES", 16)
        ctx, client = _mock_httpx({}, body=b"x" * 64)  # 64 bytes > 16-byte cap
        with ctx as ac:
            ac.return_value.__aenter__.return_value = client
            assert await nutrition_sources.lookup_usda(_uniq("x")) is None


# --------------------------------------------------------------------------- #
# Precedence reconciliation (AC4)
# --------------------------------------------------------------------------- #
class TestPrecedence:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch):
        monkeypatch.setattr(settings, "meal_intelligence_enabled", True)

    def _recall(self, *, corrected: bool):
        return meal_rag.MealRecall(
            name="leftover stew",
            carbs_low=33,
            carbs_high=33,
            is_corrected=corrected,
            food_record_id="r1",
            common_food_id=None,
            distance=0.05,
        )

    def _fact(self, source, tier, carbs, disclaimer=None):
        return nutrition_sources.NutritionFact(
            source_name=source,
            source_url="https://example.org/x",
            trust_tier=tier,
            name=source,
            carbs_grams=carbs,
            serving="per 100 g",
            disclaimer=disclaimer,
        )

    async def test_corrected_history_wins_and_skips_external(self):
        with (
            patch.object(
                meal_rag,
                "recall_similar_meal",
                AsyncMock(return_value=self._recall(corrected=True)),
            ),
            patch.object(
                nutrition_sources, "lookup_published_nutrition", AsyncMock()
            ) as lookup,
        ):
            detail = await meal_grounding.ground_estimate(
                uuid.uuid4(), "stew", identity_confirmed=True
            )
        assert detail is not None
        assert detail.source == "Your meal history"
        assert detail.trust_tier == KnowledgeChunk.TIER_USER_PROVIDED
        assert detail.carbs_low == 33
        # Corrected history short-circuits -- the external lookup never runs.
        lookup.assert_not_awaited()

    async def test_usda_preferred_over_off(self):
        usda = self._fact(
            "USDA FoodData Central", KnowledgeChunk.TIER_AUTHORITATIVE, 12
        )
        off = self._fact("Open Food Facts", KnowledgeChunk.TIER_RESEARCHED, 70)
        with (
            patch.object(meal_rag, "recall_similar_meal", AsyncMock(return_value=None)),
            patch.object(
                nutrition_sources,
                "lookup_published_nutrition",
                AsyncMock(return_value=(usda, off)),
            ),
        ):
            detail = await meal_grounding.ground_estimate(
                uuid.uuid4(), "oatmeal", identity_confirmed=True
            )
        assert detail.source == "USDA FoodData Central"
        assert detail.carbs_low == 12

    async def test_off_used_when_no_usda(self):
        off = self._fact(
            "Open Food Facts",
            KnowledgeChunk.TIER_RESEARCHED,
            70,
            disclaimer="Open Food Facts (ODbL) -- never use it to dose or bolus.",
        )
        with (
            patch.object(meal_rag, "recall_similar_meal", AsyncMock(return_value=None)),
            patch.object(
                nutrition_sources,
                "lookup_published_nutrition",
                AsyncMock(return_value=(None, off)),
            ),
        ):
            detail = await meal_grounding.ground_estimate(
                uuid.uuid4(), "cereal", identity_confirmed=True
            )
        assert detail.source == "Open Food Facts"
        assert detail.disclaimer  # OFF disclaimer carried through

    async def test_uncorrected_history_below_published(self):
        # When nothing published matches, an uncorrected prior log still grounds.
        with (
            patch.object(
                meal_rag,
                "recall_similar_meal",
                AsyncMock(return_value=self._recall(corrected=False)),
            ),
            patch.object(
                nutrition_sources,
                "lookup_published_nutrition",
                AsyncMock(return_value=(None, None)),
            ),
        ):
            detail = await meal_grounding.ground_estimate(
                uuid.uuid4(), "stew", identity_confirmed=True
            )
        assert detail.source == "Your meal history"

    async def test_pure_vision_when_nothing_grounds(self):
        with (
            patch.object(meal_rag, "recall_similar_meal", AsyncMock(return_value=None)),
            patch.object(
                nutrition_sources,
                "lookup_published_nutrition",
                AsyncMock(return_value=(None, None)),
            ),
        ):
            assert (
                await meal_grounding.ground_estimate(
                    uuid.uuid4(), "x", identity_confirmed=True
                )
                is None
            )

    async def test_empty_description_is_ungrounded(self):
        assert (
            await meal_grounding.ground_estimate(
                uuid.uuid4(), "", identity_confirmed=True
            )
            is None
        )
        assert (
            await meal_grounding.ground_estimate(
                uuid.uuid4(), None, identity_confirmed=True
            )
            is None
        )

    async def test_unconfirmed_identity_is_never_grounded(self):
        # The H2 gate: even with a strong corrected own-history match and a
        # published fact available, an UNCONFIRMED identity grounds to nothing.
        with (
            patch.object(
                meal_rag,
                "recall_similar_meal",
                AsyncMock(return_value=self._recall(corrected=True)),
            ) as recall,
            patch.object(
                nutrition_sources, "lookup_published_nutrition", AsyncMock()
            ) as lookup,
        ):
            detail = await meal_grounding.ground_estimate(
                uuid.uuid4(), "stew", identity_confirmed=False
            )
        assert detail is None
        # The gate short-circuits before any recall or external lookup runs.
        recall.assert_not_awaited()
        lookup.assert_not_awaited()

    # ── Story 50.E2: restaurant slots in as AUTHORITATIVE above USDA ──
    def _restaurant_fact(self, carbs=30):
        return nutrition_sources.NutritionFact(
            source_name="McDonald's",
            source_url="https://www.mcdonalds.com/x",
            trust_tier=KnowledgeChunk.TIER_AUTHORITATIVE,
            name="Quarter Pounder with Cheese",
            carbs_grams=carbs,
            serving="per item",
            disclaimer="Reference only; never use it to dose or bolus.",
        )

    async def test_restaurant_preferred_over_usda(self):
        # A branded chain item grounds to the chain's own facts above generic USDA.
        usda = self._fact(
            "USDA FoodData Central", KnowledgeChunk.TIER_AUTHORITATIVE, 12
        )
        with (
            patch.object(meal_rag, "recall_similar_meal", AsyncMock(return_value=None)),
            patch.object(
                restaurant_nutrition,
                "lookup_restaurant",
                AsyncMock(return_value=self._restaurant_fact(30)),
            ),
            patch.object(
                nutrition_sources,
                "lookup_published_nutrition",
                AsyncMock(return_value=(usda, None)),
            ) as published,
        ):
            detail = await meal_grounding.ground_estimate(
                uuid.uuid4(), "McDonald's Quarter Pounder", identity_confirmed=True
            )
        assert detail.source == "McDonald's"
        assert detail.carbs_low == 30  # the chain figure, not the USDA 12
        assert detail.trust_tier == KnowledgeChunk.TIER_AUTHORITATIVE
        # A restaurant hit short-circuits before the USDA/OFF HTTP round-trips.
        published.assert_not_awaited()

    async def test_corrected_own_history_beats_restaurant(self):
        # Precedence: own-history corrected > restaurant. A corrected match
        # short-circuits before the restaurant lookup even runs.
        with (
            patch.object(
                meal_rag,
                "recall_similar_meal",
                AsyncMock(return_value=self._recall(corrected=True)),
            ),
            patch.object(
                restaurant_nutrition, "lookup_restaurant", AsyncMock()
            ) as restaurant,
        ):
            detail = await meal_grounding.ground_estimate(
                uuid.uuid4(), "McDonald's Quarter Pounder", identity_confirmed=True
            )
        assert detail.source == "Your meal history"
        restaurant.assert_not_awaited()

    async def test_restaurant_falls_through_to_usda_when_unbranded(self):
        # A generic food (restaurant lookup returns None) still grounds to USDA.
        usda = self._fact(
            "USDA FoodData Central", KnowledgeChunk.TIER_AUTHORITATIVE, 12
        )
        with (
            patch.object(meal_rag, "recall_similar_meal", AsyncMock(return_value=None)),
            patch.object(
                restaurant_nutrition,
                "lookup_restaurant",
                AsyncMock(return_value=None),
            ),
            patch.object(
                nutrition_sources,
                "lookup_published_nutrition",
                AsyncMock(return_value=(usda, None)),
            ),
        ):
            detail = await meal_grounding.ground_estimate(
                uuid.uuid4(), "oatmeal", identity_confirmed=True
            )
        assert detail.source == "USDA FoodData Central"
        assert detail.carbs_low == 12

    async def test_unconfirmed_identity_never_grounds_restaurant(self):
        # AC8: the restaurant lookup is never even reached for an unconfirmed item.
        with patch.object(
            restaurant_nutrition, "lookup_restaurant", AsyncMock()
        ) as restaurant:
            detail = await meal_grounding.ground_estimate(
                uuid.uuid4(),
                "McDonald's Quarter Pounder",
                identity_confirmed=False,
            )
        assert detail is None
        restaurant.assert_not_awaited()


# --------------------------------------------------------------------------- #
# Clinical-retrieval separation (AC4): food chunks never leak into clinical RAG
# --------------------------------------------------------------------------- #
class TestRetrievalSeparation:
    async def test_food_chunks_excluded_from_clinical_retrieval(self):
        from src.services.embedding import embed_text
        from src.services.knowledge_retrieval import retrieve_knowledge

        query = _uniq("how do I handle a high reading")
        emb = embed_text(query)  # deterministic stub
        async with get_session_maker()() as db:
            user = await _new_user(db)
            # A clinical chunk (should be retrieved) and a food-grounding chunk
            # (must be excluded) with the SAME embedding so only the source_type
            # filter can separate them.
            db.add(
                KnowledgeChunk(
                    user_id=user.id,
                    trust_tier=KnowledgeChunk.TIER_USER_PROVIDED,
                    source_type="user_document",
                    source_name="Clinical note",
                    content="clinical content",
                    embedding=emb,
                )
            )
            db.add(
                KnowledgeChunk(
                    user_id=user.id,
                    trust_tier=KnowledgeChunk.TIER_USER_PROVIDED,
                    source_type=meal_rag.SOURCE_TYPE_FOOD_RECORD,
                    source_name="oatmeal",
                    content="oatmeal",
                    embedding=emb,
                )
            )
            await db.commit()

            chunks = await retrieve_knowledge(db, user.id, query)
        source_types = {c.source_type for c in chunks}
        assert "user_document" in source_types
        assert meal_rag.SOURCE_TYPE_FOOD_RECORD not in source_types


# --------------------------------------------------------------------------- #
# Safety: grounding sharpens the descriptive estimate, never a dose (AC5)
# --------------------------------------------------------------------------- #
class TestNoTherapyCoupling:
    def test_dosing_math_modules_do_not_reference_grounding(self):
        """Static guard: therapy-math modules never import the grounding code."""
        api_root = Path(__file__).resolve().parents[1]
        therapy_sources = [
            api_root / "src" / "services" / "iob_projection.py",
            api_root / "src" / "core" / "treatment_safety" / "validator.py",
            api_root / "src" / "core" / "treatment_safety" / "models.py",
            api_root / "src" / "core" / "treatment_safety" / "constants.py",
        ]
        for path in therapy_sources:
            text = path.read_text()
            for needle in (
                "meal_rag",
                "meal_grounding",
                "nutrition_sources",
                "grounding",
            ):
                assert needle not in text, f"{path} references {needle}"

    async def test_grounding_output_carries_no_dosing_language(self, monkeypatch):
        monkeypatch.setattr(settings, "meal_intelligence_enabled", True)
        # Every rendered grounding string must be free of dosing/advice phrasing.
        recall = meal_rag.MealRecall(
            name="oatmeal",
            carbs_low=30,
            carbs_high=40,
            is_corrected=True,
            food_record_id="r",
            common_food_id=None,
            distance=0.0,
        )
        with (
            patch.object(
                meal_rag, "recall_similar_meal", AsyncMock(return_value=recall)
            ),
        ):
            detail = await meal_grounding.ground_estimate(
                uuid.uuid4(), "oatmeal", identity_confirmed=True
            )
        for field in (detail.source, detail.note, detail.serving):
            assert not find_dosing_violations(field or "")

    def test_food_record_grounding_columns_not_read_by_therapy(self):
        # The new attribution columns must not leak into treatment-safety models.
        api_root = Path(__file__).resolve().parents[1]
        validator = (
            api_root / "src" / "core" / "treatment_safety" / "validator.py"
        ).read_text()
        assert "grounding_source" not in validator


# --------------------------------------------------------------------------- #
# Estimation pipeline: grounding wired end-to-end (AC1 + AC4 + AC5)
# --------------------------------------------------------------------------- #
class TestEstimatePipelineGrounding:
    @pytest.fixture(autouse=True)
    def _enable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
        monkeypatch.setattr(settings, "meal_intelligence_enabled", True)

    async def test_create_is_vision_only_then_confirm_grounds(self):
        # Story 50.H2: a fresh estimate is NOT grounded (identity unconfirmed);
        # it surfaces a suggested identity from own history for a one-tap confirm,
        # and grounding runs only after the user confirms.
        from src.services import common_food as common_food_service

        desc = _uniq("homemade lasagna")
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            # A prior logged + corrected record seeds own-history grounding.
            prior = await _new_record(db, user, desc, low=40, high=55)
            from src.schemas.food_record import FoodRecordCorrectionRequest

            await common_food_service.correct_food_record(
                db,
                prior,
                FoodRecordCorrectionRequest(
                    corrected_carbs_low=70, corrected_carbs_high=80
                ),
            )

        # A new photo the model identifies as the same food.
        async with get_session_maker()() as db:
            user = await db.get(User, user.id)
            with patch.object(
                food_vision,
                "_call_vision",
                AsyncMock(return_value=_estimate_json(desc, 45, 60)),
            ):
                record = await food_vision.create_food_record_from_image(
                    db=db, user=user, raw_image=_png_bytes()
                )

            # Create: vision-only, identity unconfirmed, but own history is
            # suggested for confirmation (the safe fast path).
            assert record.carbs_low == 45 and record.carbs_high == 60
            assert record.identity_confirmed is False
            assert record.grounding_source is None
            assert record.grounding is None
            assert record.suggested_identity is not None

            # Confirm the identity -> NOW it grounds against the user's own
            # corrected history.
            record = await common_food_service.confirm_food_identity(db, record, desc)

        assert record.identity_confirmed is True
        assert record.confirmed_food_name == desc
        assert record.carbs_low == 45 and record.carbs_high == 60  # carbs unchanged
        assert record.grounding_source == "Your meal history"
        assert record.grounding_trust_tier == KnowledgeChunk.TIER_USER_PROVIDED
        assert record.grounding is not None
        assert record.grounding.carbs_low == 70 and record.grounding.carbs_high == 80
        assert "logged this before" in (record.grounding.note or "")
        assert not find_dosing_violations(record.grounding.note or "")

    async def test_confirm_falls_back_to_vision_only_on_grounding_failure(self):
        from src.services import common_food as common_food_service

        desc = _uniq("mystery casserole")
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            with patch.object(
                food_vision,
                "_call_vision",
                AsyncMock(return_value=_estimate_json(desc, 30, 45)),
            ):
                record = await food_vision.create_food_record_from_image(
                    db=db, user=user, raw_image=_png_bytes()
                )

            # Confirm, but grounding blows up -> the confirmation still succeeds
            # and the estimate degrades cleanly to vision-only (never a dose).
            with patch.object(
                meal_grounding,
                "ground_estimate",
                AsyncMock(side_effect=RuntimeError("source down")),
            ):
                record = await common_food_service.confirm_food_identity(
                    db, record, "mystery casserole"
                )

        assert record.carbs_low == 30 and record.carbs_high == 45
        assert record.identity_confirmed is True  # identity still confirmed
        assert record.grounding_source is None  # grounding degraded cleanly
        assert record.grounding is None

    async def test_reconfirm_regrounds_and_clears_stale_citation(self):
        # Re-confirming with a corrected identity that grounds to nothing must
        # CLEAR the prior authoritative citation -- otherwise a stale citation
        # from the first (wrong) identity would survive the correction, the exact
        # misID-amplification H2 exists to prevent.
        from src.services import common_food as common_food_service

        desc = _uniq("reconfirm food")
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            with patch.object(
                food_vision,
                "_call_vision",
                AsyncMock(return_value=_estimate_json(desc, 40, 50)),
            ):
                record = await food_vision.create_food_record_from_image(
                    db=db, user=user, raw_image=_png_bytes()
                )

            usda = nutrition_sources.NutritionFact(
                source_name="USDA FoodData Central",
                source_url="https://fdc.nal.usda.gov/x",
                trust_tier=KnowledgeChunk.TIER_AUTHORITATIVE,
                name="pasta",
                carbs_grams=43,
                serving="per 100 g",
                disclaimer=None,
            )
            # First confirm -> grounds to a USDA fact.
            with (
                patch.object(
                    meal_rag, "recall_similar_meal", AsyncMock(return_value=None)
                ),
                patch.object(
                    nutrition_sources,
                    "lookup_published_nutrition",
                    AsyncMock(return_value=(usda, None)),
                ),
            ):
                record = await common_food_service.confirm_food_identity(
                    db, record, "pasta"
                )
            assert record.grounding_source == "USDA FoodData Central"
            assert record.grounding_trust_tier == KnowledgeChunk.TIER_AUTHORITATIVE

            # Re-confirm with a corrected identity nothing matches -> citation
            # must be cleared, not left stale.
            with (
                patch.object(
                    meal_rag, "recall_similar_meal", AsyncMock(return_value=None)
                ),
                patch.object(
                    nutrition_sources,
                    "lookup_published_nutrition",
                    AsyncMock(return_value=(None, None)),
                ),
            ):
                record = await common_food_service.confirm_food_identity(
                    db, record, "obscure nonfood item"
                )

        assert record.confirmed_food_name == "obscure nonfood item"
        assert record.grounding_source is None
        assert record.grounding_source_url is None
        assert record.grounding_trust_tier is None
        assert record.grounding is None

    async def test_corrected_identity_feeds_future_suggestion(self):
        # Correcting the identity re-indexes own-history RAG on the confirmed
        # name, so the next photo of the same food suggests the user's truth, not
        # the stale AI label -- closing the one-tap-confirm loop (AC4).
        from src.services import common_food as common_food_service

        ai_label = _uniq("ai mislabel soup")
        corrected = _uniq("my homemade chili")
        async with get_session_maker()() as db:
            user = await _user_with_provider(db)
            with patch.object(
                food_vision,
                "_call_vision",
                AsyncMock(return_value=_estimate_json(ai_label, 40, 50)),
            ):
                record = await food_vision.create_food_record_from_image(
                    db=db, user=user, raw_image=_png_bytes()
                )
            record = await common_food_service.confirm_food_identity(
                db, record, corrected
            )

        # The corrected identity is now what own-history suggests...
        assert await meal_grounding.suggest_identity(user.id, corrected) == corrected
        # ...and the stale AI label no longer recalls this record.
        assert await meal_grounding.suggest_identity(user.id, ai_label) is None
