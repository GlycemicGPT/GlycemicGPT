"""End-to-end H1->H2->H3 chain over HTTP (real ASGI app + real DB, vision mocked).

Exercises the *composed* flow the per-story tests don't: a meal photo goes
upload -> multi-sample dispersion (H1) -> identity confirmation that opens the
grounding gate + re-indexes own history (H2) -> auditable provenance with the
self-reported confidence hidden (H3) -> delete that cascades the audit. Only the
vision LLM (``_call_vision``) is mocked; everything else is the real pipeline,
router, schemas, and database. Embeddings are the autouse conftest stub, so
own-history recall is deterministic (identical text -> distance 0).
"""

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
from src.services import food_vision
from src.vision.carb_contract import find_dosing_violations


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


@pytest.fixture(autouse=True)
def _enable(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "meal_intelligence_enabled", True)
    monkeypatch.setattr(settings, "meal_estimate_sample_count", 3)
    # Keep grounding deterministic: no external sources, only own-history.
    monkeypatch.setattr(settings, "usda_fdc_api_key", "")
    monkeypatch.setattr(settings, "open_food_facts_enabled", False)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        email = f"e2e_{uuid.uuid4().hex[:8]}@example.com"
        await c.post(
            "/api/auth/register", json={"email": email, "password": "SecurePass123"}
        )
        login = await c.post(
            "/api/auth/login", json={"email": email, "password": "SecurePass123"}
        )
        c.cookies.set(
            settings.jwt_cookie_name, login.cookies.get(settings.jwt_cookie_name)
        )
        me = await c.get("/api/auth/me")
        user_id = uuid.UUID(me.json()["id"])
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
        yield c


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
