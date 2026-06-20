"""Story 50.E2: restaurant / fast-food grounding -- fetchers, SSRF, owner-scoped
cache, robots/rate-limit compliance, reference-data disclaimer, and the optional
FatSecret BYO-key provider.

Chain HTTP is always mocked (``_mock_httpx`` patches ``httpx.AsyncClient.stream`` /
``.post`` -- never a live call, per the Test Plan). robots.txt is bypassed for the
fetch tests (``_robots_allows`` patched True) and exercised directly in its own
test. Behavioral assertions only -- never an exact published carb count from a real
endpoint; the only hard numbers are inputs we control in the mocked payloads.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import update

from src.config import settings
from src.database import get_session_maker
from src.models.knowledge_chunk import KnowledgeChunk
from src.models.user import User, UserRole
from src.services import meal_rag
from src.services import restaurant_nutrition as rn
from src.vision.carb_contract import (
    MEAL_ESTIMATE_QUALIFIER,
    NEVER_DOSE_PROHIBITION,
    find_dosing_violations,
)

# (asyncio_mode = "auto" in pyproject -- async tests need no explicit mark.)


# --------------------------------------------------------------------------- #
# Helpers + fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(settings, "restaurant_grounding_enabled", True)
    # No real sleeps in the rate limiter for the fetch tests.
    monkeypatch.setattr(settings, "restaurant_min_seconds_between_fetches", 0.0)
    # FatSecret off by default (no shared key); the FatSecret tests opt in.
    monkeypatch.setattr(settings, "fatsecret_consumer_key", "")
    monkeypatch.setattr(settings, "fatsecret_consumer_secret", "")
    rn._reset_state_for_tests()
    yield
    rn._reset_state_for_tests()


def _allow_robots():
    """Bypass the robots.txt fetch so a test exercises only the data fetch."""
    return patch.object(rn, "_robots_allows", AsyncMock(return_value=True))


def _mock_httpx(payload, status=200, *, body=None, token=None):
    """Patch ``httpx.AsyncClient`` so ``.stream("GET", ...)`` yields the data payload
    and ``.stream("POST", ...)`` (the FatSecret OAuth token exchange) yields a token.

    ``token=None`` makes the POST return 401 (a token failure). Mirrors
    test_meal_grounding's streamed-mock idiom; ``stream()`` is method-aware so the
    GET data fetch and the streamed POST token exchange get distinct responses.
    """
    search_raw = body if body is not None else json.dumps(payload).encode()
    token_raw = json.dumps({"access_token": token}).encode() if token else b"{}"

    def _make_cm(raw, st):
        async def _aiter_bytes():
            yield raw

        resp = MagicMock()
        resp.status_code = st
        resp.aiter_bytes = _aiter_bytes
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    def _stream(method, *args, **kwargs):
        if method == "POST":
            return _make_cm(token_raw, 200 if token else 401)
        return _make_cm(search_raw, status)

    client = AsyncMock()
    client.stream = MagicMock(side_effect=_stream)  # stream() is sync -> CM
    ctx = patch("httpx.AsyncClient")
    return ctx, client


async def _new_user() -> User:
    async with get_session_maker()() as db:
        user = User(
            email=f"restaurant_{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            role=UserRole.DIABETIC,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


_MCD_PAYLOAD = {
    "items": [
        {
            "item_name": "Quarter Pounder with Cheese",
            "nutrient_facts": [
                {"name": "Calories", "value": 520},
                {"name": "Carbohydrates", "value": 42, "uom": "g"},
            ],
        }
    ]
}

_CHIPOTLE_PAYLOAD = {
    "items": [
        {
            "itemName": "Chicken Bowl",
            "nutrition": [
                {"name": "Protein", "value": 32},
                {"name": "Total Carbohydrate", "value": 40, "unit": "g"},
            ],
        }
    ]
}

# FatSecret v1 foods.search embeds nutrients in the description string.
_FATSECRET_PAYLOAD = {
    "foods": {
        "food": {
            "food_id": "33691",
            "food_name": "Crunchwrap Supreme",
            "food_description": "Per 1 wrap - Calories: 530kcal | Fat: 21.00g | "
            "Carbs: 71.00g | Protein: 16.00g",
        }
    }
}


# --------------------------------------------------------------------------- #
# Brand detection (the chain-from-identity step)
# --------------------------------------------------------------------------- #
class TestBrandDetection:
    def test_identifies_dedicated_chains(self):
        mcd = rn._identify_chain("McDonald's Quarter Pounder with cheese")
        assert mcd is not None and mcd[0].chain_id == "mcdonalds"
        assert "quarter pounder" in mcd[1]

        chip = rn._identify_chain("Chipotle chicken bowl")
        assert chip is not None and chip[0].chain_id == "chipotle"
        assert "chicken bowl" in chip[1]

    def test_generic_food_is_not_a_chain(self):
        assert rn._identify_chain("a bowl of oatmeal with berries") is None
        # No item after the brand -> nothing to look up.
        assert rn._identify_chain("mcdonalds") is None

    def test_known_brand_without_dedicated_fetcher(self):
        # Routes to FatSecret, never to USDA/OFF.
        assert rn._has_known_brand("Taco Bell crunchwrap supreme") is True
        assert rn._has_known_brand("Starbucks caramel frappuccino") is True
        # A plain food carries no brand.
        assert rn._has_known_brand("homemade chili") is False

    def test_punctuation_free_brand_spellings_match(self):
        # Common collapsed spellings must still be recognized as a brand, even
        # though _canon turns "wendy's" -> "wendy s" / "chick-fil-a" -> "chick fil a".
        assert rn._has_known_brand("wendys baconator") is True
        assert rn._has_known_brand("chickfila sandwich") is True
        assert rn._has_known_brand("innout double double") is True

    def test_brand_match_is_whole_token(self):
        # "mcd" must not match inside "mcdonalds"; "taco" must not match a non-brand.
        assert rn._contains_phrase(rn._canon("mcdonalds big mac"), "mcd") is False
        assert rn._contains_phrase(rn._canon("tacopalooza dish"), "taco bell") is False

    def test_canon_folds_accents(self):
        # NFKD accent folding keeps an accented menu name comparable to its ASCII
        # form (consistent with the hardened own-history matcher).
        assert rn._canon("Crème Brûlée") == "creme brulee"
        assert rn._canon("Açaí Bowl") == "acai bowl"


# --------------------------------------------------------------------------- #
# Happy path: fetch -> parse -> owner-scoped cache (GJ5 at the unit level)
# --------------------------------------------------------------------------- #
class TestChainFetch:
    async def test_mcdonalds_parses_and_caches(self):
        user = await _new_user()
        ctx, client = _mock_httpx(_MCD_PAYLOAD)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            first = await rn.lookup_restaurant(user.id, "McDonald's Quarter Pounder")
            second = await rn.lookup_restaurant(user.id, "McDonald's Quarter Pounder")

        assert first is not None
        assert first.source_name == "McDonald's"
        assert first.trust_tier == KnowledgeChunk.TIER_AUTHORITATIVE
        assert first.carbs_grams == 42
        assert first.serving == "per item"
        # Second call is served from the owner-scoped cache -- no second fetch.
        assert client.stream.call_count == 1
        assert second is not None and second.carbs_grams == 42

    async def test_chipotle_parses(self):
        user = await _new_user()
        ctx, client = _mock_httpx(_CHIPOTLE_PAYLOAD)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            fact = await rn.lookup_restaurant(user.id, "Chipotle chicken bowl")
        assert fact is not None
        assert fact.source_name == "Chipotle"
        assert fact.carbs_grams == 40
        assert fact.trust_tier == KnowledgeChunk.TIER_AUTHORITATIVE

    async def test_captures_comorbidity_and_cache_round_trips(self):
        # A chain's published saturated fat / sugars / sodium flow into
        # the fact (per-item) and survive the owner-scoped cache round-trip.
        user = await _new_user()
        payload = {
            "items": [
                {
                    "item_name": "Big Mac",
                    "nutrient_facts": [
                        {"name": "Carbohydrates", "value": 45},
                        {"name": "Saturated Fat", "value": 10},
                        {"name": "Total Sugars", "value": 9},
                        {"name": "Added Sugars", "value": 7},
                        {"name": "Sodium", "value": 1010},
                    ],
                }
            ]
        }
        ctx, client = _mock_httpx(payload)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            first = await rn.lookup_restaurant(user.id, "McDonald's Big Mac")
            second = await rn.lookup_restaurant(user.id, "McDonald's Big Mac")
        assert first is not None
        assert first.comorbidity_dict() == {
            "saturated_fat_grams": 10.0,
            "sugars_grams": 9.0,
            "added_sugars_grams": 7.0,
            "sodium_mg": 1010.0,
        }
        # Served from the owner-scoped cache with comorbidity intact (no 2nd fetch).
        assert client.stream.call_count == 1
        assert second is not None
        assert second.comorbidity_dict() == first.comorbidity_dict()

    def test_sugar_alcohol_is_not_bucketed_as_total_sugars(self):
        # "Sugar Alcohol" (polyols) contains "sugar" but is a distinct field; it must
        # not be surfaced as the meal's total Sugars figure.
        result = rn._comorbidity_from_nutrients(
            [
                {"name": "Total Sugars", "value": 9},
                {"name": "Sugar Alcohol", "value": 4},
            ],
            name_key="name",
            value_key="value",
        )
        assert result == {"sugars_grams": 9.0}

    def test_unsaturated_fat_is_not_bucketed_as_saturated(self):
        # "saturated" is a substring of mono-/poly-unsaturated; an unsaturated row
        # (appearing first) must not be stored as the saturated-fat figure.
        result = rn._comorbidity_from_nutrients(
            [
                {"name": "Monounsaturated Fat", "value": 7},
                {"name": "Polyunsaturated Fat", "value": 5},
                {"name": "Saturated Fat", "value": 3},
            ],
            name_key="name",
            value_key="value",
        )
        assert result == {"saturated_fat_grams": 3.0}

    async def test_no_brand_makes_no_request(self):
        user = await _new_user()
        ctx, client = _mock_httpx(_MCD_PAYLOAD)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            fact = await rn.lookup_restaurant(user.id, "plain oatmeal")
        assert fact is None
        assert client.stream.call_count == 0  # generic food -> never a chain fetch

    async def test_disabled_flag_skips_fetch(self, monkeypatch):
        monkeypatch.setattr(settings, "restaurant_grounding_enabled", False)
        user = await _new_user()
        ctx, client = _mock_httpx(_MCD_PAYLOAD)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            fact = await rn.lookup_restaurant(user.id, "McDonald's Big Mac")
        assert fact is None
        assert client.stream.call_count == 0


# --------------------------------------------------------------------------- #
# FM7: owner-scoped cache isolation (the key difference from USDA/OFF caching)
# --------------------------------------------------------------------------- #
class TestOwnerScopedCache:
    async def test_user_b_never_sees_user_a_cached_fetch(self):
        user_a = await _new_user()
        user_b = await _new_user()
        ctx, client = _mock_httpx(_MCD_PAYLOAD)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            a1 = await rn.lookup_restaurant(user_a.id, "McDonald's Big Mac")
            assert client.stream.call_count == 1
            # A re-logs -> served from A's own cache (no new fetch).
            await rn.lookup_restaurant(user_a.id, "McDonald's Big Mac")
            assert client.stream.call_count == 1
            # B logs the same item -> B does NOT read A's cache; it fetches itself.
            b1 = await rn.lookup_restaurant(user_b.id, "McDonald's Big Mac")
            assert client.stream.call_count == 2
        assert a1 is not None and b1 is not None

        # And the cache rows are genuinely per-user (distinct content_hash + user).
        async with get_session_maker()() as db:
            from sqlalchemy import func, select

            a_rows = await db.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(
                    KnowledgeChunk.user_id == user_a.id,
                    KnowledgeChunk.source_type == meal_rag.SOURCE_TYPE_RESTAURANT_CHAIN,
                )
            )
            b_rows = await db.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(
                    KnowledgeChunk.user_id == user_b.id,
                    KnowledgeChunk.source_type == meal_rag.SOURCE_TYPE_RESTAURANT_CHAIN,
                )
            )
        assert a_rows == 1 and b_rows == 1

    async def test_restaurant_cache_is_never_shared(self):
        # A restaurant chunk must never be written shared (user_id IS NULL) like
        # the redistributable USDA/OFF mirror.
        user = await _new_user()
        ctx, client = _mock_httpx(_MCD_PAYLOAD)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            await rn.lookup_restaurant(user.id, "McDonald's Big Mac")
        async with get_session_maker()() as db:
            from sqlalchemy import func, select

            shared = await db.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(
                    KnowledgeChunk.user_id.is_(None),
                    KnowledgeChunk.source_type == meal_rag.SOURCE_TYPE_RESTAURANT_CHAIN,
                )
            )
        assert shared == 0


# --------------------------------------------------------------------------- #
# FM6 + fallbacks: every failure mode degrades to None (vision-only upstream)
# --------------------------------------------------------------------------- #
class TestFallbacks:
    async def test_non_200_returns_none(self):
        user = await _new_user()
        ctx, client = _mock_httpx(_MCD_PAYLOAD, status=500)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            assert await rn.lookup_restaurant(user.id, "McDonald's Big Mac") is None

    async def test_fetch_exception_returns_none(self):
        user = await _new_user()
        with (
            _allow_robots(),
            patch.object(
                rn._McDonalds,
                "fetch_item",
                AsyncMock(side_effect=RuntimeError("endpoint changed")),
            ),
        ):
            assert await rn.lookup_restaurant(user.id, "McDonald's Big Mac") is None

    async def test_empty_or_malformed_payload_returns_none(self):
        user = await _new_user()
        for payload in ({}, {"items": []}, {"items": [{"item_name": "x"}]}):
            ctx, client = _mock_httpx(payload)
            with _allow_robots(), ctx as ac:
                ac.return_value.__aenter__.return_value = client
                assert await rn.lookup_restaurant(user.id, "McDonald's thing") is None

    async def test_out_of_range_carbs_dropped_not_clamped(self):
        user = await _new_user()
        payload = {
            "items": [
                {
                    "item_name": "Impossible plate",
                    "nutrient_facts": [{"name": "Carbohydrates", "value": 5000}],
                }
            ]
        }
        ctx, client = _mock_httpx(payload)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            # > CARB_GRAMS_MAX -> rejected, never a "published" wrong number.
            assert await rn.lookup_restaurant(user.id, "McDonald's plate") is None

    async def test_multi_item_no_match_does_not_cite_wrong_item(self):
        # A search-style response with several items, none matching the confirmed
        # identity, must NOT cite the first (a different food) as authoritative --
        # it degrades to vision-only instead.
        user = await _new_user()
        payload = {
            "items": [
                {
                    "item_name": "Big Mac",
                    "nutrient_facts": [{"name": "Carbohydrates", "value": 45}],
                },
                {
                    "item_name": "McFlurry",
                    "nutrient_facts": [{"name": "Carbohydrates", "value": 80}],
                },
            ]
        }
        ctx, client = _mock_httpx(payload)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            assert (
                await rn.lookup_restaurant(user.id, "McDonald's Quarter Pounder")
                is None
            )

    async def test_single_item_response_is_trusted(self):
        # A single-item endpoint response IS trusted even without a token match --
        # it's the chain's one hit for our exact query param.
        user = await _new_user()
        payload = {
            "items": [
                {
                    "item_name": "Some Combo",
                    "nutrient_facts": [{"name": "Carbohydrates", "value": 50}],
                }
            ]
        }
        ctx, client = _mock_httpx(payload)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            fact = await rn.lookup_restaurant(user.id, "McDonald's Quarter Pounder")
        assert fact is not None and fact.carbs_grams == 50

    async def test_dosing_language_item_name_is_dropped(self):
        # Defence in depth: a source-controlled item name carrying dosing language
        # drops the grounding rather than surface it in the citation note.
        user = await _new_user()
        payload = {
            "items": [
                {
                    "item_name": "Quarter Pounder bolus 6u",
                    "nutrient_facts": [{"name": "Carbohydrates", "value": 42}],
                }
            ]
        }
        ctx, client = _mock_httpx(payload)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            assert (
                await rn.lookup_restaurant(user.id, "McDonald's Quarter Pounder")
                is None
            )


# --------------------------------------------------------------------------- #
# Security: SSRF host allow-list / https-only / redirect-free / key handling
# --------------------------------------------------------------------------- #
class TestSsrf:
    def test_host_allowlist(self):
        hosts = frozenset({"www.mcdonalds.com"})
        assert rn._host_allowed("https://www.mcdonalds.com/x", hosts)
        # Plaintext, off-list, and metadata/internal targets are rejected.
        assert not rn._host_allowed("http://www.mcdonalds.com/x", hosts)
        assert not rn._host_allowed("https://169.254.169.254/x", hosts)
        assert not rn._host_allowed("https://localhost/x", hosts)
        assert not rn._host_allowed("https://evil.example.com/x", hosts)

    async def test_off_list_host_makes_no_request(self):
        ctx, client = _mock_httpx({"items": []})
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            out = await rn._fetch_json(
                "https://169.254.169.254/itemNutrition",
                {"name": "x"},
                host="169.254.169.254",
                allowed_hosts=frozenset({"www.mcdonalds.com"}),
            )
        assert out is None
        # Guard short-circuits before any HTTP client stream is constructed.
        assert client.stream.call_count == 0

    async def test_redirect_free_and_query_rides_in_params(self):
        user = await _new_user()
        ctx, client = _mock_httpx(_MCD_PAYLOAD)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            await rn.lookup_restaurant(user.id, "McDonald's Quarter Pounder")
        # AsyncClient configured to not follow redirects (no redirect-based SSRF).
        _, kwargs = ac.call_args
        assert kwargs.get("follow_redirects") is False
        # The item travels as an encoded query param, never interpolated in a path.
        _, stream_kwargs = client.stream.call_args
        assert "quarter pounder" in stream_kwargs["params"]["name"].lower()

    async def test_oversized_body_rejected(self, monkeypatch):
        user = await _new_user()
        monkeypatch.setattr(rn, "_MAX_RESPONSE_BYTES", 16)
        ctx, client = _mock_httpx({}, body=b"x" * 64)  # 64 bytes > 16-byte cap
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            assert await rn.lookup_restaurant(user.id, "McDonald's Big Mac") is None


# --------------------------------------------------------------------------- #
# Compliance: robots.txt + rate-limit / back-off (AC2)
# --------------------------------------------------------------------------- #
class TestCompliance:
    async def test_robots_disallow_skips_fetch(self):
        user = await _new_user()
        # The mocked response body is the robots.txt (disallow all) for the robots
        # fetch; the data fetch must never run once robots forbids it.
        ctx, client = _mock_httpx(None, body=b"User-agent: *\nDisallow: /")
        with ctx as ac:  # NB: real _robots_allows (not bypassed) here
            ac.return_value.__aenter__.return_value = client
            fact = await rn.lookup_restaurant(user.id, "McDonald's Big Mac")
        assert fact is None

    async def test_robots_allow_permits_fetch(self):
        allow = await self._robots_decision(b"User-agent: *\nAllow: /")
        assert allow is True
        disallow = await self._robots_decision(b"User-agent: *\nDisallow: /")
        assert disallow is False

    async def _robots_decision(self, robots_body: bytes) -> bool:
        rn._reset_state_for_tests()
        ctx, client = _mock_httpx(None, body=robots_body)
        with ctx as ac:
            ac.return_value.__aenter__.return_value = client
            return await rn._robots_allows(
                "https://www.mcdonalds.com/dnaapp/itemNutrition",
                frozenset({"www.mcdonalds.com"}),
            )

    async def test_backoff_skips_fetch_after_rate_limit(self):
        host = "www.mcdonalds.com"
        # A 429/503 arms back-off; while it holds, a fetch is skipped (no HTTP).
        rn._note_backoff(host)
        assert rn._in_backoff(host) is True
        ctx, client = _mock_httpx(_MCD_PAYLOAD)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            out = await rn._fetch_json(
                "https://www.mcdonalds.com/dnaapp/itemNutrition",
                {"name": "x"},
                host=host,
                allowed_hosts=frozenset({host}),
            )
        assert out is None
        assert client.stream.call_count == 0

    async def test_503_response_arms_backoff(self):
        user = await _new_user()
        ctx, client = _mock_httpx(_MCD_PAYLOAD, status=503)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            await rn.lookup_restaurant(user.id, "McDonald's Big Mac")
        assert rn._in_backoff("www.mcdonalds.com") is True

    async def test_rate_limit_sleeps_between_fetches(self, monkeypatch):
        monkeypatch.setattr(settings, "restaurant_min_seconds_between_fetches", 5.0)
        slept = []

        async def _fake_sleep(seconds):
            slept.append(seconds)

        host = "www.mcdonalds.com"
        rn._host_state[host] = {"last": __import__("time").monotonic()}
        with patch.object(rn.asyncio, "sleep", _fake_sleep):
            await rn._respect_rate_limit(host)
        assert slept and slept[0] > 0  # waited for the min interval

    async def test_concurrent_same_host_calls_serialize(self, monkeypatch):
        # The per-host lock serializes two concurrent fetches to the same host:
        # exactly one waits for the other's slot (without it, both could read a
        # stale `last` and skip the rate limit together).
        monkeypatch.setattr(settings, "restaurant_min_seconds_between_fetches", 5.0)
        slept = []

        async def _fake_sleep(seconds):
            slept.append(seconds)

        host = "www.mcdonalds.com"
        with patch.object(rn.asyncio, "sleep", _fake_sleep):
            await asyncio.gather(
                rn._respect_rate_limit(host), rn._respect_rate_limit(host)
            )
        assert len(slept) == 1 and slept[0] > 0


# --------------------------------------------------------------------------- #
# Reference-data disclaimer (NOT an AI estimate) + no-dosing safety
# --------------------------------------------------------------------------- #
class TestDisclaimerAndSafety:
    async def test_disclaimer_is_reference_data_not_ai_estimate(self):
        user = await _new_user()
        ctx, client = _mock_httpx(_MCD_PAYLOAD)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            fact = await rn.lookup_restaurant(user.id, "McDonald's Quarter Pounder")
        assert fact is not None and fact.disclaimer
        # Carries the canonical dosing prohibition (single source of truth)...
        assert NEVER_DOSE_PROHIBITION in fact.disclaimer
        # ...but never the "AI estimate"/"AI guess" framing that would mislabel a
        # chain's own published facts, nor the permissive "verify before dosing".
        assert MEAL_ESTIMATE_QUALIFIER not in fact.disclaimer
        assert "AI estimate" not in fact.disclaimer
        assert "verify before dosing" not in fact.disclaimer.lower()
        # The dosing scanner is applied to model-generated name/serving, NOT the
        # disclaimer (which intentionally contains the word "bolus").
        assert not find_dosing_violations(fact.name)
        assert not find_dosing_violations(fact.serving or "")
        assert "bolus" in fact.disclaimer


# --------------------------------------------------------------------------- #
# Optional FatSecret BYO-key provider (AC5)
# --------------------------------------------------------------------------- #
class TestFatSecret:
    def _enable(self, monkeypatch):
        monkeypatch.setattr(settings, "fatsecret_consumer_key", "KEY")
        monkeypatch.setattr(settings, "fatsecret_consumer_secret", "SECRET")

    async def test_without_key_silently_skipped(self):
        # Default fixture leaves the key empty -> a known brand without a dedicated
        # fetcher makes no FatSecret call.
        user = await _new_user()
        ctx, client = _mock_httpx(_FATSECRET_PAYLOAD, token="tok")
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            fact = await rn.lookup_restaurant(user.id, "Taco Bell crunchwrap")
        assert fact is None
        assert client.stream.call_count == 0

    async def test_with_key_fetches_and_caches(self, monkeypatch):
        self._enable(monkeypatch)
        user = await _new_user()
        ctx, client = _mock_httpx(_FATSECRET_PAYLOAD, token="tok")
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            first = await rn.lookup_restaurant(user.id, "Taco Bell crunchwrap")
            second = await rn.lookup_restaurant(user.id, "Taco Bell crunchwrap")
        assert first is not None
        assert first.source_name == "FatSecret"
        assert first.carbs_grams == 71.0  # parsed from the description string
        assert first.trust_tier == KnowledgeChunk.TIER_AUTHORITATIVE
        assert NEVER_DOSE_PROHIBITION in (first.disclaimer or "")
        # First lookup = token POST + search GET; second is served owner-scoped
        # cache with no further token/search.
        assert client.stream.call_count == 2
        assert second is not None

    async def test_token_failure_yields_no_search(self, monkeypatch):
        self._enable(monkeypatch)
        user = await _new_user()
        # token=None -> the streamed token POST returns 401 -> no token -> no search.
        ctx, client = _mock_httpx(_FATSECRET_PAYLOAD)
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            fact = await rn.lookup_restaurant(user.id, "Taco Bell crunchwrap")
        assert fact is None
        methods = [c.args[0] for c in client.stream.call_args_list]
        assert "GET" not in methods  # the search GET was never reached

    async def test_offlist_api_host_rejected(self, monkeypatch):
        # The FatSecret SSRF allow-list is a fixed constant, not derived from the
        # (operator) URL -- so a misconfigured api_url host is rejected.
        self._enable(monkeypatch)
        monkeypatch.setattr(
            settings, "fatsecret_api_url", "https://evil.example.com/rest"
        )
        user = await _new_user()
        ctx, client = _mock_httpx(_FATSECRET_PAYLOAD, token="tok")
        with _allow_robots(), ctx as ac:
            ac.return_value.__aenter__.return_value = client
            fact = await rn.lookup_restaurant(user.id, "Taco Bell crunchwrap")
        assert fact is None
        methods = [c.args[0] for c in client.stream.call_args_list]
        assert "GET" not in methods  # search to the off-list host never issued


# --------------------------------------------------------------------------- #
# Owner-scoped cache TTL (FatSecret's 24h ToS limit + lazy purge)
# --------------------------------------------------------------------------- #
class TestCacheTtl:
    async def test_stale_entry_is_a_miss_and_is_purged(self):
        user = await _new_user()
        fact = rn.NutritionFact(
            source_name="FatSecret",
            source_url="https://www.fatsecret.com/x",
            trust_tier=KnowledgeChunk.TIER_AUTHORITATIVE,
            name="Crunchwrap",
            carbs_grams=71.0,
            serving="per 1 wrap",
            disclaimer=rn._RESTAURANT_DISCLAIMER,
        )
        normalized = "taco bell crunchwrap"
        await rn._cache_put(
            user.id, meal_rag.SOURCE_TYPE_FATSECRET, normalized, fact, ttl_hours=24.0
        )

        # Fresh read within TTL -> hit.
        hit = await rn._cache_get(
            user.id, meal_rag.SOURCE_TYPE_FATSECRET, normalized, ttl_hours=24.0
        )
        assert hit is not None and hit.carbs_grams == 71.0

        # Age the row beyond 24h: the value must not be served (FatSecret ToS) and
        # the stale row is lazily purged.
        async with get_session_maker()() as db:
            await db.execute(
                update(KnowledgeChunk)
                .where(
                    KnowledgeChunk.user_id == user.id,
                    KnowledgeChunk.source_type == meal_rag.SOURCE_TYPE_FATSECRET,
                )
                .values(retrieved_at=datetime.now(UTC) - timedelta(hours=25))
            )
            await db.commit()

        stale = await rn._cache_get(
            user.id, meal_rag.SOURCE_TYPE_FATSECRET, normalized, ttl_hours=24.0
        )
        assert stale is None

        async with get_session_maker()() as db:
            from sqlalchemy import func, select

            remaining = await db.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(
                    KnowledgeChunk.user_id == user.id,
                    KnowledgeChunk.source_type == meal_rag.SOURCE_TYPE_FATSECRET,
                )
            )
        assert remaining == 0  # lazily purged on the stale read
