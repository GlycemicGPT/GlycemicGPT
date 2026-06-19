"""End-to-end meal-intelligence journeys over HTTP (real ASGI app + real DB).

Two layers live here:

* The original composed estimate->confirm->audit->delete chain: a meal photo
  goes upload -> multi-sample dispersion -> identity confirmation that opens the
  grounding gate + re-indexes own history -> auditable provenance with the
  self-reported confidence hidden -> delete that cascades the audit.
* The user-journey backfill (the safety net the live feature lacked): the core
  loop a real user walks -- first estimate -> correct -> save & recognize a
  common food -> meal-aware chat with a verified citation -- plus the failure
  modes users actually hit (no provider, no-vision provider, feature flag off, a
  hallucinated chat carb number, an external-grounding fetch failure, and
  cross-user isolation).

Only the vision LLM (``_call_vision``) and the chat model (``get_ai_client``)
are mocked; the pipeline, router, schemas, grounding precedence, citation
verifier, and database are all real. Embeddings are the autouse conftest stub,
so own-history recall is deterministic (identical text -> distance 0).

Assertions are behavioral, never exact carb values from the model: a range is
present, the safety qualifier is present, a cited number traces to a stored
record, a correction persists, recognition fires, and an unconfirmed identity is
not certified. The only hard numbers asserted are user-supplied (a correction)
or model-mocked inputs we control in the test.
"""

import contextlib
import uuid
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image

from src.config import settings
from src.database import get_session_maker
from src.main import app
from src.models.ai_provider import AIProviderConfig, AIProviderStatus, AIProviderType
from src.schemas.ai_response import AIResponse, AIUsage
from src.services import food_vision
from src.vision.carb_contract import MEAL_ESTIMATE_QUALIFIER, find_dosing_violations


def _png() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (16, 16), (60, 40, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _vision(desc: str, low: float, high: float, confidence: str = "high") -> str:
    import json

    return json.dumps(
        {
            "food_description": desc,
            "carbs_grams_low": low,
            "carbs_grams_high": high,
            "confidence": confidence,
        }
    )


# Digits map to letters so a unique food name interpolated into a mocked chat
# reply can never be misread as a (carb-anchored) figure by the F2 verifier.
_ALPHA_SUFFIX = str.maketrans("0123456789", "ghijklmnop")


def _uniq() -> str:
    """A short, digit-free unique token for food names."""
    return uuid.uuid4().hex[:6].translate(_ALPHA_SUFFIX)


@pytest.fixture(autouse=True)
def _enable(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "meal_intelligence_enabled", True)
    monkeypatch.setattr(settings, "meal_estimate_sample_count", 3)
    # Keep grounding deterministic: no external sources, only own-history.
    monkeypatch.setattr(settings, "usda_fdc_api_key", "")
    monkeypatch.setattr(settings, "open_food_facts_enabled", False)


async def _provision(c: AsyncClient, *, with_provider: bool = True) -> uuid.UUID:
    """Register + log in a fresh user on ``c``; optionally give them a provider.

    Returns the new user's id. ``with_provider=False`` leaves the user with no AI
    provider so the upload path raises ``ProviderNotConfiguredError`` (FM1). The
    provider is seeded directly (the same pattern the original chain test used)
    because the public provider API requires a real key-validation round-trip.
    """
    email = f"e2e_{uuid.uuid4().hex[:8]}@example.com"
    register = await c.post(
        "/api/auth/register", json={"email": email, "password": "SecurePass123"}
    )
    assert register.status_code == 201, register.text
    login = await c.post(
        "/api/auth/login", json={"email": email, "password": "SecurePass123"}
    )
    assert login.status_code == 200, login.text
    c.cookies.set(settings.jwt_cookie_name, login.cookies.get(settings.jwt_cookie_name))
    me = await c.get("/api/auth/me")
    user_id = uuid.UUID(me.json()["id"])
    if with_provider:
        async with get_session_maker()() as db:
            db.add(
                AIProviderConfig(
                    user_id=user_id,
                    provider_type=AIProviderType.CLAUDE_API,
                    model_name="claude-sonnet-4-5-20250929",
                    status=AIProviderStatus.CONNECTED,
                )
            )
            await db.commit()
    return user_id


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _provision(c)
        yield c


@contextlib.asynccontextmanager
async def _second_client(*, with_provider: bool = True):
    """A second authenticated client against the same app (cross-user tests)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await _provision(c, with_provider=with_provider)
        yield c


def _ai_client(content: str) -> MagicMock:
    """A fake AI client whose ``generate`` returns a canned response."""
    fake = MagicMock()
    fake.generate = AsyncMock(
        return_value=AIResponse(
            content=content,
            model="claude-sonnet-4-5-20250929",
            provider=AIProviderType.CLAUDE_API,
            usage=AIUsage(input_tokens=10, output_tokens=10),
        )
    )
    return fake


async def _chat(client: AsyncClient, message: str, *, ai_says: str) -> str:
    """Drive a web chat turn with the model output mocked; return the reply text.

    The diabetes-context build is stubbed (its builders have their own tests and
    cannot affect a mocked reply), but the meal-citation verifier runs for real
    against the user's logged meals in the database.
    """
    with (
        patch(
            "src.services.telegram_chat.get_ai_client",
            AsyncMock(return_value=_ai_client(ai_says)),
        ),
        patch(
            "src.services.telegram_chat.build_diabetes_context",
            AsyncMock(return_value="[context]"),
        ),
    ):
        resp = await client.post("/api/ai/chat", json={"message": message})
    assert resp.status_code == 200, resp.text
    return resp.json()["response"]


async def _upload(client: AsyncClient, *responses: str) -> dict:
    with patch.object(
        food_vision, "_call_vision", AsyncMock(side_effect=list(responses))
    ):
        resp = await client.post(
            "/api/food-records", files={"file": ("m.png", _png(), "image/png")}
        )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_full_chain_upload_confirm_audit_delete(client):
    desc = f"spaghetti bolognese {uuid.uuid4().hex[:6]}"

    # --- H1: upload A, three disagreeing samples -> empirical dispersion ---
    rec_a = await _upload(
        client,
        _vision(desc, 40, 50),
        _vision(desc, 90, 100),
        _vision(desc, 60, 70),
    )
    disp = rec_a["estimate_dispersion"]
    assert disp is not None, "H1 dispersion detail missing from create response"
    assert disp["samples_used"] == 3
    assert disp["wide_spread"] is True  # 45..95 midpoints -> wide
    assert rec_a["carbs_low"] == 40 and rec_a["carbs_high"] == 100  # union band
    assert "self_reported_confidence" not in rec_a  # H1: never surfaced
    assert rec_a["identity_confirmed"] is False  # H2: unconfirmed at create
    assert rec_a["grounding_source"] is None  # gate: no grounding yet
    assert not find_dosing_violations(disp["note"] or "")

    # Correct A's carbs so own-history holds a corrected value for this food.
    corr = await client.post(
        f"/api/food-records/{rec_a['id']}/correct",
        json={"corrected_carbs_low": 75, "corrected_carbs_high": 85},
    )
    assert corr.status_code == 200, corr.text

    # --- H1+H2: upload B (same food), then confirm identity -> grounds to A ---
    rec_b = await _upload(
        client, _vision(desc, 50, 60), _vision(desc, 55, 65), _vision(desc, 52, 62)
    )
    rec_b_band = (rec_b["carbs_low"], rec_b["carbs_high"])
    assert rec_b["grounding_source"] is None  # vision-only at create
    assert rec_b["suggested_identity"] is not None  # own-history pre-fill (H2 AC4)

    confirm = await client.post(
        f"/api/food-records/{rec_b['id']}/confirm-identity",
        json={"confirmed_food_name": desc},
    )
    assert confirm.status_code == 200, confirm.text
    body = confirm.json()
    assert body["identity_confirmed"] is True
    assert (
        body["grounding_source"] == "Your meal history"
    )  # H2: gate opened -> grounded
    assert body["grounding"]["carbs_low"] == 75  # the corrected own-history value
    # Carbs are the create-time empirical band, untouched by the confirmation.
    assert (body["carbs_low"], body["carbs_high"]) == rec_b_band

    # --- H3: audit provenance, self-reported confidence hidden ---
    audit = await client.get(f"/api/food-records/{rec_b['id']}/audit")
    assert audit.status_code == 200, audit.text
    a = audit.json()
    assert len(a["samples"]) == 3  # raw per-sample retained
    assert a["precedence"]["outcome"] == "grounded"
    assert a["precedence"]["chosen_source"] == "Your meal history"
    assert a["precedence"]["identity_used"] == desc
    assert "self_reported_confidence" not in audit.text  # H3: internal-only

    # --- H3 AC5: deleting the record cascades its audit ---
    assert (await client.delete(f"/api/food-records/{rec_b['id']}")).status_code == 204
    assert (
        await client.get(f"/api/food-records/{rec_b['id']}/audit")
    ).status_code == 404


async def test_unconfirmed_identity_audit_is_vision_only(client):
    desc = f"mystery stew {uuid.uuid4().hex[:6]}"
    rec = await _upload(
        client, _vision(desc, 30, 40), _vision(desc, 32, 42), _vision(desc, 31, 41)
    )
    # Never confirmed -> audit records a vision-only precedence, no grounding.
    audit = (await client.get(f"/api/food-records/{rec['id']}/audit")).json()
    assert audit["precedence"]["outcome"] == "vision_only"
    assert audit["precedence"]["identity_confirmed"] is False
    assert rec["grounding_source"] is None


# ── Core-loop user journey (GJ1 -> GJ2 -> GJ3 -> GJ6) ──
# The single loop a real user walks across the merged milestones: photograph a
# meal, correct the estimate, save & recognize it as a common food, then ask the
# AI about it and get a citation that traces to the saved value. Behavioral
# assertions only -- the model's carb numbers are never asserted, but the
# user-supplied correction and the mocked-model citation (both inputs we control)
# are.

# Carb figures that, if they showed up as response *fields*, would mean food
# records had been coupled into dosing/treatment math -- the one thing this
# feature must never do.
_DOSE_FIELDS = {"dose", "insulin", "bolus", "iob", "units", "carb_ratio"}


async def test_core_loop_estimate_correct_save_recognize_cite(client):
    desc = f"chicken burrito {_uniq()}"

    # --- GJ1: first estimate (cold start) -> range + qualifier, no dose ---
    rec = await _upload(
        client, _vision(desc, 45, 55), _vision(desc, 50, 60), _vision(desc, 48, 58)
    )
    assert rec["carbs_low"] < rec["carbs_high"]  # a range, not a lone integer
    assert "Never use it" in rec["safety_qualifier"]  # qualifier present
    assert rec["identity_confirmed"] is False  # unconfirmed at create
    assert rec["grounding_source"] is None  # gate closed -> no grounding yet
    assert rec["suggested_identity"] is None  # nothing logged before this
    disp = rec["estimate_dispersion"]
    assert disp is not None and disp["samples_used"] == 3
    assert not find_dosing_violations(disp["note"] or "")  # uncertainty note is safe
    # No dosing/IoB coupling: food records never expose a dose-shaped field.
    assert _DOSE_FIELDS.isdisjoint(rec.keys())
    rec_id = rec["id"]

    # --- GJ2: correct the estimate -> persists, source flips, original kept ---
    corr = await client.post(
        f"/api/food-records/{rec_id}/correct",
        json={"corrected_carbs_low": 70, "corrected_carbs_high": 80},
    )
    assert corr.status_code == 200, corr.text
    cbody = corr.json()
    assert (cbody["corrected_carbs_low"], cbody["corrected_carbs_high"]) == (70, 80)
    assert cbody["source"] == "user_corrected"  # provenance flipped
    # The original AI estimate is preserved alongside the correction.
    assert (cbody["carbs_low"], cbody["carbs_high"]) == (
        rec["carbs_low"],
        rec["carbs_high"],
    )

    # --- GJ3a: save the corrected estimate as a named common food ---
    # Save under a distinct canonical name (not the vision description). The
    # common-food baseline is the user's curated truth; grounding the re-shoot
    # against this name resolves to exactly this one corrected baseline -- which
    # makes the "prefers the corrected value" assertion deterministic. Confirming
    # against the bare description instead would leave the recall query equidistant
    # (under the conftest fake embedding) to BOTH the corrected baseline and the
    # re-shoot's own uncorrected chunk, and the production recall currently has no
    # tie-breaker to deterministically prefer the corrected one.
    saved_name = f"my usual {desc}"
    save = await client.post(
        f"/api/food-records/{rec_id}/save-as-common-food", json={"name": saved_name}
    )
    assert save.status_code == 201, save.text
    cf = save.json()
    assert (cf["carbs_low"], cf["carbs_high"]) == (70, 80)  # the corrected value
    listing = (await client.get("/api/common-foods")).json()
    assert any(item["id"] == cf["id"] for item in listing["common_foods"])

    # --- GJ3b: re-shoot the same food -> recall recognizes it ---
    rec2 = await _upload(
        client, _vision(desc, 52, 62), _vision(desc, 54, 64), _vision(desc, 53, 63)
    )
    assert rec2["suggested_identity"] is not None  # "you've logged this before"
    assert rec2["grounding_source"] is None  # still vision-only until confirmed

    # Confirm the re-shoot as the saved common food -> grounding resolves to that
    # one corrected baseline and prefers the corrected value over the vision band.
    confirm = await client.post(
        f"/api/food-records/{rec2['id']}/confirm-identity",
        json={"confirmed_food_name": saved_name},
    )
    assert confirm.status_code == 200, confirm.text
    g = confirm.json()
    assert g["identity_confirmed"] is True
    assert g["grounding_source"] == "Your meal history"  # own-history grounded
    assert g["grounding"]["carbs_low"] == 70  # the corrected value, not vision
    assert "corrected value" in g["grounding"]["note"]

    # --- GJ6: meal-aware chat references the meal with a VERIFIED citation ---
    # The model utters a carb figure that traces to the corrected record (70-80g):
    # within tolerance, so the verifier leaves it byte-for-byte unchanged.
    reply = await _chat(
        client,
        "what have I eaten lately?",
        ai_says=f"You logged {desc} with about 75g of carbs recently. How did it sit?",
    )
    assert "75g" in reply  # the verified figure survived untouched
    assert desc in reply  # the AI referenced the logged meal
    assert "can't verify" not in reply  # not scrubbed -- it matched a record


# ── Failure modes users actually hit (FM1, FM2, FM3, FM5, FM6, FM7) ──


async def test_fm1_no_provider_returns_structured_error():
    """FM1: a user with no AI provider gets a clear 4xx, never a crash."""
    async with _second_client(with_provider=False) as c:
        resp = await c.post(
            "/api/food-records", files={"file": ("m.png", _png(), "image/png")}
        )
    assert resp.status_code == 404
    assert "provider" in resp.json()["detail"].lower()


async def test_fm2_provider_without_vision_returns_vision_unavailable(client):
    """FM2: a provider with no vision route -> 422, never a fabricated estimate."""
    with patch.object(
        food_vision,
        "_call_vision",
        AsyncMock(
            side_effect=food_vision.VisionUnavailableError(
                "Vision is not available on your current AI provider."
            )
        ),
    ):
        resp = await client.post(
            "/api/food-records", files={"file": ("m.png", _png(), "image/png")}
        )
    assert resp.status_code == 422
    assert "vision" in resp.json()["detail"].lower()


async def test_fm3_feature_flag_off_returns_404(client, monkeypatch):
    """FM3: with the feature flag off, the meal endpoints are invisible (404)."""
    monkeypatch.setattr(settings, "meal_intelligence_enabled", False)
    upload = await client.post(
        "/api/food-records", files={"file": ("m.png", _png(), "image/png")}
    )
    assert upload.status_code == 404
    assert (await client.get("/api/food-records")).status_code == 404
    assert (await client.get("/api/common-foods")).status_code == 404


async def test_fm5_wrong_chat_carb_number_is_scrubbed(client):
    """FM5: a carb figure the model invents is corrected/scrubbed before the user sees it."""
    desc = f"oatmeal {_uniq()}"
    rec = await _upload(
        client, _vision(desc, 30, 40), _vision(desc, 32, 42), _vision(desc, 31, 41)
    )
    low, high = rec["carbs_low"], rec["carbs_high"]

    # Exactly one logged meal -> a single unambiguous referent, so an unverifiable
    # figure is corrected to the stored range rather than scrubbed to prose.
    reply = await _chat(
        client,
        "how many carbs was breakfast?",
        ai_says="Your breakfast had about 200g of carbs.",
    )
    assert "200" not in reply  # the invented number is gone
    assert f"~{low:g}-{high:g}g carbs" in reply  # rewritten to the stored range
    assert MEAL_ESTIMATE_QUALIFIER in reply  # carries the never-dose framing


async def test_fm5_wrong_chat_carb_number_scrubbed_when_ambiguous(client):
    """FM5 (multi-referent): with >1 meal, an unverifiable figure is scrubbed."""
    a = f"toast {_uniq()}"
    b = f"yogurt {_uniq()}"
    await _upload(client, _vision(a, 20, 30), _vision(a, 22, 32), _vision(a, 21, 31))
    await _upload(client, _vision(b, 10, 18), _vision(b, 12, 20), _vision(b, 11, 19))

    reply = await _chat(
        client,
        "what did I eat today?",
        ai_says="Across the day you had about 999g of carbs.",
    )
    assert "999" not in reply  # can't be pinned to one meal -> not guessed
    assert "can't verify" in reply
    assert MEAL_ESTIMATE_QUALIFIER in reply


async def test_fm6_external_grounding_failure_degrades_to_vision_only(client):
    """FM6: an external nutrition fetch failure degrades gracefully (no crash)."""
    from src.services import nutrition_sources

    desc = f"unique dish {_uniq()}"
    rec = await _upload(
        client, _vision(desc, 40, 50), _vision(desc, 42, 52), _vision(desc, 41, 51)
    )
    assert rec["carbs_low"] < rec["carbs_high"]  # the user already got an estimate

    # Confirm a never-before-grounded identity (so own-history can't ground it)
    # while both published-source lookups blow up. End to end, the grounding path
    # must swallow the failure: confirmation still succeeds, gracefully vision-only,
    # and the user keeps their estimate. This asserts the end-to-end degradation,
    # not which specific fail-open layer caught it (the orchestrator's own wrapper
    # has focused unit coverage). The novel name keeps the recall query off the
    # record's freshly-indexed chunk, so the external-failure path is what's tested
    # rather than the own-history fallback.
    novel = f"never grounded {_uniq()}"
    with (
        patch.object(
            nutrition_sources,
            "lookup_usda",
            AsyncMock(side_effect=RuntimeError("down")),
        ),
        patch.object(
            nutrition_sources,
            "lookup_open_food_facts",
            AsyncMock(side_effect=RuntimeError("down")),
        ),
    ):
        confirm = await client.post(
            f"/api/food-records/{rec['id']}/confirm-identity",
            json={"confirmed_food_name": novel},
        )
    assert confirm.status_code == 200, confirm.text  # no crash
    body = confirm.json()
    assert body["identity_confirmed"] is True
    assert body["grounding_source"] is None  # gracefully vision-only
    # The estimate band is untouched by the failed grounding attempt.
    assert (body["carbs_low"], body["carbs_high"]) == (
        rec["carbs_low"],
        rec["carbs_high"],
    )


async def test_fm7_cross_user_isolation(client):
    """FM7 (IDOR): user B can never see user A's records or common foods."""
    desc = f"private meal {_uniq()}"
    rec_a = await _upload(
        client, _vision(desc, 60, 70), _vision(desc, 62, 72), _vision(desc, 61, 71)
    )
    cf_a = (
        await client.post(
            f"/api/food-records/{rec_a['id']}/save-as-common-food",
            json={"name": desc},
        )
    ).json()

    async with _second_client() as b:
        # Direct object access is a not-found, not a forbidden (no existence leak).
        assert (await b.get(f"/api/food-records/{rec_a['id']}")).status_code == 404
        assert (
            await b.get(f"/api/food-records/{rec_a['id']}/audit")
        ).status_code == 404
        correct_b = await b.post(
            f"/api/food-records/{rec_a['id']}/correct",
            json={"corrected_carbs_low": 1, "corrected_carbs_high": 2},
        )
        assert correct_b.status_code == 404
        assert (await b.get(f"/api/common-foods/{cf_a['id']}")).status_code == 404

        # Listings never surface another user's rows.
        assert (await b.get("/api/food-records")).json()["total"] == 0
        assert (await b.get("/api/common-foods")).json()["total"] == 0

        # Own-history recall is owner-scoped: B shooting A's food gets no recall.
        rec_b = await _upload(
            b, _vision(desc, 60, 70), _vision(desc, 62, 72), _vision(desc, 61, 71)
        )
        assert rec_b["suggested_identity"] is None


# ── Story 50.E2: restaurant grounding journeys (GJ5, FM4, FM6) ──
# The chain HTTP is never hit here -- restaurant_nutrition.lookup_restaurant is
# patched so the journey asserts the gate + precedence + provenance plumbing.
# FM7 (owner-scoped restaurant cache isolation) lives in test_restaurant_nutrition
# where the cache + mocked HTTP are exercised directly.


def _chain_fact(carbs: float = 42):
    from src.services import nutrition_sources

    return nutrition_sources.NutritionFact(
        source_name="McDonald's",
        source_url="https://www.mcdonalds.com/x",
        trust_tier="AUTHORITATIVE",
        name="Quarter Pounder with Cheese",
        carbs_grams=carbs,
        serving="per item",
        disclaimer="Reference only; never use it to dose or bolus.",
    )


async def test_gj5_confirmed_chain_item_gets_authoritative_citation(client):
    """GJ5: a chain item is fetched + cited at AUTHORITATIVE only AFTER the user
    confirms identity; an unconfirmed item never carries a chain citation."""
    from src.services import restaurant_nutrition

    desc = f"mcdonalds quarter pounder {_uniq()}"
    rec = await _upload(
        client, _vision(desc, 40, 50), _vision(desc, 42, 52), _vision(desc, 41, 51)
    )
    # Headline AC8 safety point: vision-only at create, no chain citation yet.
    assert rec["identity_confirmed"] is False
    assert rec["grounding_source"] is None

    with patch.object(
        restaurant_nutrition,
        "lookup_restaurant",
        AsyncMock(return_value=_chain_fact(42)),
    ):
        confirm = await client.post(
            f"/api/food-records/{rec['id']}/confirm-identity",
            json={"confirmed_food_name": desc},
        )
    assert confirm.status_code == 200, confirm.text
    body = confirm.json()
    assert body["identity_confirmed"] is True
    assert body["grounding_source"] == "McDonald's"
    assert body["grounding_trust_tier"] == "AUTHORITATIVE"
    assert body["grounding_source_url"] == "https://www.mcdonalds.com/x"
    assert body["grounding"]["carbs_low"] == 42  # the chain's own published figure
    # Grounding is descriptive only -- the user's empirical band is untouched.
    assert (body["carbs_low"], body["carbs_high"]) == (
        rec["carbs_low"],
        rec["carbs_high"],
    )
    assert not find_dosing_violations(body["grounding"]["note"] or "")


async def test_fm4_misidentified_chain_item_grounds_only_corrected_identity(client):
    """FM4: the AI's mislabel is never cited; only the user's corrected identity
    is grounded, and the chain is queried on the corrected name."""
    from src.services import restaurant_nutrition

    mislabel = f"mystery sandwich {_uniq()}"
    corrected = f"mcdonalds quarter pounder {_uniq()}"
    rec = await _upload(
        client,
        _vision(mislabel, 35, 45),
        _vision(mislabel, 36, 46),
        _vision(mislabel, 34, 44),
    )
    assert rec["grounding_source"] is None  # the mislabel is never grounded

    seen = {}

    async def _fake_lookup(user_id, identity):
        seen["identity"] = identity
        return _chain_fact(42)

    with patch.object(
        restaurant_nutrition, "lookup_restaurant", AsyncMock(side_effect=_fake_lookup)
    ):
        confirm = await client.post(
            f"/api/food-records/{rec['id']}/confirm-identity",
            json={"confirmed_food_name": corrected},
        )
    assert confirm.status_code == 200, confirm.text
    body = confirm.json()
    assert body["confirmed_food_name"] == corrected
    assert body["grounding_source"] == "McDonald's"
    # The chain was queried on the CORRECTED identity, never the AI's mislabel.
    assert seen["identity"] == corrected


async def test_fm6_restaurant_fetch_failure_degrades_to_vision_only(client):
    """FM6: a restaurant fetch blowing up degrades cleanly -- confirmation still
    succeeds, the estimate stays vision-only, and the band is untouched."""
    from src.services import restaurant_nutrition

    desc = f"mcdonalds big mac {_uniq()}"
    rec = await _upload(
        client, _vision(desc, 40, 50), _vision(desc, 42, 52), _vision(desc, 41, 51)
    )
    with patch.object(
        restaurant_nutrition,
        "lookup_restaurant",
        AsyncMock(side_effect=RuntimeError("endpoint down")),
    ):
        confirm = await client.post(
            f"/api/food-records/{rec['id']}/confirm-identity",
            json={"confirmed_food_name": desc},
        )
    assert confirm.status_code == 200, confirm.text  # no crash
    body = confirm.json()
    assert body["identity_confirmed"] is True
    assert body["grounding_source"] is None  # gracefully vision-only
    assert (body["carbs_low"], body["carbs_high"]) == (
        rec["carbs_low"],
        rec["carbs_high"],
    )
