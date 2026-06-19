"""Local-model vision capability gating: the runtime safety control.

A user can configure any self-hosted, OpenAI-compatible model. An unverified one
must be *gated* -- refused with a clear, actionable message -- never allowed to
produce a silent low-quality carb estimate. A model a maintainer has certified is
enabled and behaves on the journey exactly like the cloud path. Cloud/API-key
paths must not regress.

Two layers:

* Unit -- the capability classifier and its message (pure, no DB).
* HTTP journey -- over the real ASGI app + DB, with only the vision LLM mocked,
  mirroring ``test_meal_e2e_chain.py``: an unverified local model is gated (and
  the model is never even called); a certified local model (allow-list patched
  for the test, as the live cross-model benchmark is operational and out of CI)
  carries GJ1 (range + empirical confidence + never-dose qualifier) and GJ7
  (wide-spread caution) just like cloud.

Assertions are behavioral, never exact carb values from the model.
"""

import json
import uuid
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image

from src.config import settings
from src.database import get_session_maker
from src.main import app
from src.models.ai_provider import AIProviderConfig, AIProviderStatus, AIProviderType
from src.services import food_vision, vision_capability
from src.vision.carb_contract import find_dosing_violations

# A model identifier used only to exercise the "certified local model" path; the
# allow-list is patched per-test so this never leaks into the shipped default.
_TEST_CERTIFIED_LOCAL_MODEL = "test-vision-local:latest"

# Field names a food record must never expose -- proves the estimate stays
# decoupled from any dosing math, on the local path as on cloud.
_DOSE_FIELDS = {"dose", "insulin", "bolus", "iob", "units", "carb_ratio"}


def _png() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (16, 16), (60, 40, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _vision(desc: str, low: float, high: float, confidence: str = "high") -> str:
    return json.dumps(
        {
            "food_description": desc,
            "carbs_grams_low": low,
            "carbs_grams_high": high,
            "confidence": confidence,
        }
    )


@pytest.fixture(autouse=True)
def _enable(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "meal_intelligence_enabled", True)
    monkeypatch.setattr(settings, "meal_estimate_sample_count", 3)
    monkeypatch.setattr(settings, "usda_fdc_api_key", "")
    monkeypatch.setattr(settings, "open_food_facts_enabled", False)


async def _provision(
    c: AsyncClient,
    *,
    provider_type: AIProviderType,
    model_name: str | None,
) -> uuid.UUID:
    """Register + log in a fresh user and seed a specific provider/model.

    The provider is seeded directly (the public API requires a key-validation
    round-trip), matching the existing meal e2e tests.
    """
    email = f"lm_{uuid.uuid4().hex[:8]}@example.com"
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
    async with get_session_maker()() as db:
        db.add(
            AIProviderConfig(
                user_id=user_id,
                provider_type=provider_type,
                model_name=model_name,
                base_url=(
                    "http://localhost:11434/v1"
                    if provider_type is AIProviderType.OPENAI_COMPATIBLE
                    else None
                ),
                status=AIProviderStatus.CONNECTED,
            )
        )
        await db.commit()
    return user_id


@pytest_asyncio.fixture
async def make_client():
    """Factory yielding authenticated clients seeded with a chosen provider/model."""
    transport = ASGITransport(app=app)
    clients: list[AsyncClient] = []

    async def _factory(
        provider_type: AIProviderType, model_name: str | None
    ) -> AsyncClient:
        c = AsyncClient(transport=transport, base_url="http://test")
        await _provision(c, provider_type=provider_type, model_name=model_name)
        clients.append(c)
        return c

    yield _factory
    for c in clients:
        await c.aclose()


async def _post_photo(c: AsyncClient):
    return await c.post(
        "/api/food-records", files={"file": ("m.png", _png(), "image/png")}
    )


# --- unit: the capability classifier -----------------------------------------


@pytest.mark.parametrize(
    "provider_type",
    [
        AIProviderType.CLAUDE_API,
        AIProviderType.OPENAI_API,
        AIProviderType.CLAUDE_SUBSCRIPTION,
        AIProviderType.CHATGPT_SUBSCRIPTION,
    ],
)
def test_cloud_providers_are_cleared(provider_type):
    assert vision_capability.is_vision_cleared(provider_type, "any-model") is True


def test_unknown_local_model_is_unverified():
    assert (
        vision_capability.classify(AIProviderType.OPENAI_COMPATIBLE, "llava:13b")
        is vision_capability.VisionCapability.UNVERIFIED_LOCAL
    )


def test_default_allowlist_is_empty_no_local_model_certified():
    # The shipped posture: nothing local is certified yet, so the gate refuses
    # every local model rather than silently estimate.
    assert not vision_capability.CLEARED_LOCAL_VISION_MODELS


def test_certified_local_model_is_cleared_when_allowlisted(monkeypatch):
    monkeypatch.setattr(
        vision_capability,
        "CLEARED_LOCAL_VISION_MODELS",
        frozenset({_TEST_CERTIFIED_LOCAL_MODEL.lower()}),
    )
    assert (
        vision_capability.is_vision_cleared(
            AIProviderType.OPENAI_COMPATIBLE, _TEST_CERTIFIED_LOCAL_MODEL.upper()
        )
        is True  # matched normalized (case-insensitive)
    )


def test_unverified_message_is_capability_not_dosing():
    msg = vision_capability.unverified_local_message("llava:13b")
    assert "llava:13b" in msg
    assert find_dosing_violations(msg) == []  # never dosing language
    assert "verified" in msg.lower()


@pytest.mark.parametrize(
    "adversarial_name",
    [
        "take 4 units of insulin",
        "inject 10 units now",
        "bolus 10u model",
        "give-yourself-insulin:13b",
    ],
)
def test_unverified_message_scrubs_dosing_phrasing_in_model_name(adversarial_name):
    # The model name is unvalidated free text; a pathological one must not smuggle
    # dosing phrasing into the user-facing refusal. The name is hidden when it
    # trips the dosing scan, so the message itself stays clean.
    msg = vision_capability.unverified_local_message(adversarial_name)
    assert find_dosing_violations(msg) == []
    assert adversarial_name not in msg
    assert "model name hidden" in msg


def test_unverified_message_preserves_original_model_casing():
    # A benign mixed-case name is echoed as the user typed it (trimmed), not
    # lower-cased, so it matches what they see in Settings.
    msg = vision_capability.unverified_local_message("  LLaVA:13B  ")
    assert "LLaVA:13B" in msg


def test_classify_fails_closed_for_unrecognized_provider_type(monkeypatch):
    # The trailing fail-closed return: a provider type in neither the cloud nor
    # the local set must classify UNVERIFIED_LOCAL (protects against future enum
    # additions silently being treated as cleared).
    monkeypatch.setattr(vision_capability, "_CLEARED_CLOUD_PROVIDER_TYPES", frozenset())
    monkeypatch.setattr(vision_capability, "_LOCAL_PROVIDER_TYPES", frozenset())
    assert (
        vision_capability.classify(AIProviderType.CLAUDE_API, "claude-sonnet-4-5")
        is vision_capability.VisionCapability.UNVERIFIED_LOCAL
    )


# --- HTTP journey -------------------------------------------------------------


async def test_unverified_local_model_is_gated_before_any_vision_call(make_client):
    """Sub-bar/unverified local model -> 422 with a clear message, model never called."""
    c = await make_client(AIProviderType.OPENAI_COMPATIBLE, "llava:13b")
    with patch.object(food_vision, "_call_vision", AsyncMock()) as call:
        resp = await _post_photo(c)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "llava:13b" in detail
    assert "verified" in detail.lower()
    assert find_dosing_violations(detail) == []
    # The gate short-circuits: an unverified model is never sent the photo.
    call.assert_not_awaited()


async def test_gate_message_is_distinct_from_vision_unavailable(make_client):
    """The capability gate must not be conflated with 'provider has no vision'."""
    c = await make_client(AIProviderType.OPENAI_COMPATIBLE, "qwen2.5-vl:7b")
    resp = await _post_photo(c)
    assert resp.status_code == 422
    detail = resp.json()["detail"].lower()
    # 'not verified for carb estimation', not 'vision unavailable on your provider'
    assert "verified" in detail
    assert "not available on your" not in detail


async def test_cloud_path_unregressed_by_the_gate(make_client):
    """A cloud provider is never gated -- it proceeds to the (mocked) vision call."""
    c = await make_client(AIProviderType.CLAUDE_API, "claude-sonnet-4-5-20250929")
    desc = f"food {uuid.uuid4().hex[:6]}"
    with patch.object(
        food_vision,
        "_call_vision",
        AsyncMock(side_effect=[_vision(desc, 28, 34)] * 3),
    ):
        resp = await _post_photo(c)
    assert resp.status_code == 201, resp.text
    rec = resp.json()
    assert rec["carbs_low"] is not None and rec["carbs_high"] is not None
    assert "Never use it" in rec["safety_qualifier"]


async def test_certified_local_model_is_enabled_like_cloud_gj1(
    make_client, monkeypatch
):
    """GJ1 on local: a certified local model yields range + confidence + qualifier."""
    monkeypatch.setattr(
        vision_capability,
        "CLEARED_LOCAL_VISION_MODELS",
        frozenset({_TEST_CERTIFIED_LOCAL_MODEL.lower()}),
    )
    c = await make_client(AIProviderType.OPENAI_COMPATIBLE, _TEST_CERTIFIED_LOCAL_MODEL)
    desc = f"food {uuid.uuid4().hex[:6]}"
    with patch.object(
        food_vision,
        "_call_vision",
        AsyncMock(side_effect=[_vision(desc, 28, 34)] * 3),
    ):
        resp = await _post_photo(c)
    assert resp.status_code == 201, resp.text
    rec = resp.json()
    # The certified local path carries the model's range through (empirical band =
    # union of the mocked sample ranges, here all 28-34), with an empirical
    # confidence and the never-dose qualifier -- behaving like the cloud path.
    assert rec["carbs_low"] == 28 and rec["carbs_high"] == 34
    assert rec["confidence"] in {"low", "medium", "high"}
    assert "Never use it" in rec["safety_qualifier"]
    assert rec["ai_provider"] == AIProviderType.OPENAI_COMPATIBLE.value
    assert _DOSE_FIELDS.isdisjoint(rec.keys())


async def test_certified_local_model_wide_spread_caution_gj7(make_client, monkeypatch):
    """GJ7 on local: widely disagreeing samples surface a wide-spread caution."""
    monkeypatch.setattr(
        vision_capability,
        "CLEARED_LOCAL_VISION_MODELS",
        frozenset({_TEST_CERTIFIED_LOCAL_MODEL.lower()}),
    )
    c = await make_client(AIProviderType.OPENAI_COMPATIBLE, _TEST_CERTIFIED_LOCAL_MODEL)
    desc = f"food {uuid.uuid4().hex[:6]}"
    with patch.object(
        food_vision,
        "_call_vision",
        AsyncMock(
            side_effect=[
                _vision(desc, 20, 30),
                _vision(desc, 80, 100),
                _vision(desc, 50, 60),
            ]
        ),
    ):
        resp = await _post_photo(c)
    assert resp.status_code == 201, resp.text
    disp = resp.json()["estimate_dispersion"]
    assert disp is not None
    assert disp["wide_spread"] is True
    assert disp["confidence"] != "high"  # consistency never framed as safe
    assert not find_dosing_violations(disp["note"] or "")
