"""Food records + meal-photo carb-estimation pipeline tests.

Covers the contract carb bounds (reject-not-clamp), image validation + EXIF
stripping, the vision estimation pipeline (mocked sidecar), the safety
invariants (no dosing output; no IoB / treatment_safety coupling), and the
food-record API endpoints.
"""

import json
import uuid
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import func, select

from src.config import settings
from src.main import app
from src.models.ai_provider import (
    AIProviderConfig,
    AIProviderStatus,
    AIProviderType,
)
from src.models.food_record import FoodRecord, FoodRecordSource
from src.services import food_image, food_vision
from src.vision import carb_contract


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _png_bytes(size: tuple[int, int] = (16, 16), color=(120, 40, 40)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_with_exif() -> bytes:
    """A JPEG carrying an EXIF block (so we can prove it gets stripped)."""
    img = Image.new("RGB", (24, 24), (10, 200, 10))
    exif = Image.Exif()
    exif[0x010F] = "TestCameraMake"  # Make
    exif[0x9286] = "secret-location-note"  # UserComment
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _estimate_json(
    low=40, high=55, confidence="high", desc="a bowl of pasta", extra=None
):
    payload = {
        "food_description": desc,
        "carbs_grams_low": low,
        "carbs_grams_high": high,
        "confidence": confidence,
        "assumptions": "standard restaurant portion",
        "nutrition": {"protein_grams": 12, "calories": 520},
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload)


def unique_email(prefix: str = "food") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def _register_login(client: AsyncClient) -> str:
    email = unique_email()
    await client.post(
        "/api/auth/register", json={"email": email, "password": "SecurePass123"}
    )
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": "SecurePass123"}
    )
    return resp.cookies.get(settings.jwt_cookie_name)


async def _current_user_id(client: AsyncClient) -> uuid.UUID:
    resp = await client.get("/api/auth/me")
    return uuid.UUID(resp.json()["id"])


async def _add_provider(db, user_id: uuid.UUID, provider=AIProviderType.CLAUDE_API):
    db.add(
        AIProviderConfig(
            user_id=user_id,
            provider_type=provider,
            model_name="claude-sonnet-4-5-20250929",
            status=AIProviderStatus.CONNECTED,
        )
    )
    await db.commit()


async def _new_user(db, prefix: str):
    """Create + commit a diabetic user with a configured provider."""
    from src.models.user import User, UserRole

    user = User(email=unique_email(prefix), hashed_password="x", role=UserRole.DIABETIC)
    db.add(user)
    await db.commit()
    await _add_provider(db, user.id)
    return user


@pytest.fixture
def _uploads_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "meal_intelligence_enabled", True)
    return tmp_path


@pytest_asyncio.fixture
async def auth_client(_uploads_tmp, db_session):
    """An authenticated client with an AI provider configured."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cookie = await _register_login(client)
        client.cookies.set(settings.jwt_cookie_name, cookie)
        user_id = await _current_user_id(client)
        await _add_provider(db_session, user_id)
        yield client, user_id


# --------------------------------------------------------------------------- #
# Contract carb bounds -- reject-not-clamp (AC4)
# --------------------------------------------------------------------------- #
class TestCarbBounds:
    def test_in_range_passes_unchanged(self):
        assert carb_contract.validate_carb_range(40, 55) == (40, 55)

    def test_negative_rejected_not_clamped(self):
        with pytest.raises(carb_contract.CarbBoundsError):
            carb_contract.validate_carb_range(-5, 30)

    def test_above_ceiling_rejected_not_clamped(self):
        with pytest.raises(carb_contract.CarbBoundsError):
            carb_contract.validate_carb_range(10, carb_contract.CARB_GRAMS_MAX + 1)

    def test_inverted_range_rejected(self):
        with pytest.raises(carb_contract.CarbBoundsError):
            carb_contract.validate_carb_range(80, 20)

    def test_estimate_is_a_range_not_a_point(self):
        """A valid estimate carries a low/high range + confidence, never a point."""
        est = carb_contract.parse_estimate(_estimate_json(40, 55))
        assert est.carbs_low is not None and est.carbs_high is not None
        assert est.confidence in carb_contract.CONFIDENCE_LEVELS

    def test_nan_carb_is_rejected(self):
        # Python's json accepts the non-standard NaN token; it must not slip
        # past validation (nan comparisons are all False) into a stored value.
        raw = (
            '{"carbs_grams_low": NaN, "carbs_grams_high": 25, "food_description": "x"}'
        )
        est = carb_contract.parse_estimate(raw)
        assert not est.parse_ok
        assert est.carbs_low is None

    def test_validate_carb_range_rejects_non_finite(self):
        with pytest.raises(carb_contract.CarbBoundsError):
            carb_contract.validate_carb_range(float("nan"), 25)
        with pytest.raises(carb_contract.CarbBoundsError):
            carb_contract.validate_carb_range(10, float("inf"))

    def test_null_description_not_stringified(self):
        # A JSON null description must become "", never the literal "None".
        raw = (
            '{"carbs_grams_low": 30, "carbs_grams_high": 40, '
            '"confidence": "low", "food_description": null}'
        )
        est = carb_contract.parse_estimate(raw)
        assert est.food_description == ""


# --------------------------------------------------------------------------- #
# Image validation + EXIF stripping (AC2)
# --------------------------------------------------------------------------- #
class TestImageProcessing:
    def test_strips_exif_on_reencode(self):
        processed = food_image.process_upload(_jpeg_with_exif())
        reopened = Image.open(BytesIO(processed.data))
        # No EXIF tags should survive the re-encode.
        assert dict(reopened.getexif()) == {}

    def test_accepts_png(self):
        processed = food_image.process_upload(_png_bytes())
        assert processed.extension == "png"
        assert processed.media_type == "image/png"

    def test_rejects_non_image_bytes(self):
        with pytest.raises(food_image.InvalidImageError):
            food_image.process_upload(b"this is not an image")

    def test_rejects_empty_upload(self):
        with pytest.raises(food_image.InvalidImageError):
            food_image.process_upload(b"")

    def test_rejects_oversize(self, monkeypatch):
        monkeypatch.setattr(settings, "food_image_max_bytes", 10)
        with pytest.raises(food_image.ImageTooLargeError):
            food_image.process_upload(_png_bytes((64, 64)))

    def test_rejects_unsupported_format(self):
        buf = BytesIO()
        Image.new("RGB", (8, 8)).save(buf, format="BMP")
        with pytest.raises(food_image.UnsupportedImageError):
            food_image.process_upload(buf.getvalue())

    def test_rejects_oversized_dimensions(self, monkeypatch):
        # Decompression-bomb guard: a small file decoding to too many pixels is
        # rejected from the header dimensions before any decode.
        monkeypatch.setattr(food_image, "_MAX_IMAGE_PIXELS", 100)
        with pytest.raises(food_image.InvalidImageError):
            food_image.process_upload(_png_bytes((16, 16)))  # 256 px > 100

    def test_store_generates_uuid_path_under_user_dir(self, _uploads_tmp):
        user_id = uuid.uuid4()
        processed = food_image.process_upload(_png_bytes())
        path, size = food_image.store_image(user_id, processed)
        assert str(user_id) in path
        assert Path(path).exists()
        assert size == len(processed.data)
        # Filename is server-generated, not caller-controlled.
        assert Path(path).stem != "upload"

    def test_delete_refuses_path_outside_uploads_root(self, _uploads_tmp, tmp_path):
        outside = tmp_path / "outside.txt"
        outside.write_text("keep me")
        food_image.delete_stored_image(str(outside))
        assert outside.exists()  # untouched -- containment check held


# --------------------------------------------------------------------------- #
# Vision request shape + sidecar contract mapping (AC3)
# --------------------------------------------------------------------------- #
class TestVisionService:
    def test_request_uses_base64_data_url_only(self):
        req = food_vision._build_vision_request("gpt-4o", "image/png", "QUJD")
        user_msg = req["messages"][-1]
        image_part = user_msg["content"][-1]
        assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
        # System prompt carries the no-dosing contract.
        assert "NEVER mention insulin" in req["messages"][0]["content"]

    async def test_call_vision_maps_422_to_vision_unavailable(self):
        resp = MagicMock()
        resp.status_code = 422
        resp.json.return_value = {
            "error": {
                "message": "Vision is not available",
                "code": "vision_unavailable",
            }
        }
        client = AsyncMock()
        client.post.return_value = resp
        with patch("httpx.AsyncClient") as ac:
            ac.return_value.__aenter__.return_value = client
            with pytest.raises(food_vision.VisionUnavailableError):
                await food_vision._call_vision("claude-sonnet-4-5", "image/png", "QUJD")

    async def test_call_vision_returns_content_on_200(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [{"message": {"content": _estimate_json()}}]
        }
        client = AsyncMock()
        client.post.return_value = resp
        with patch("httpx.AsyncClient") as ac:
            ac.return_value.__aenter__.return_value = client
            content = await food_vision._call_vision("gpt-4o", "image/png", "QUJD")
        assert "carbs_grams_low" in content

    async def test_call_vision_rejects_non_string_content(self):
        # A provider returning content as a block list must not surface as a 500.
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [{"message": {"content": [{"type": "text", "text": "x"}]}}]
        }
        client = AsyncMock()
        client.post.return_value = resp
        with patch("httpx.AsyncClient") as ac:
            ac.return_value.__aenter__.return_value = client
            with pytest.raises(food_vision.VisionServiceError):
                await food_vision._call_vision("gpt-4o", "image/png", "QUJD")


# --------------------------------------------------------------------------- #
# Pipeline persistence (AC3) + safety scrub
# --------------------------------------------------------------------------- #
class TestPipelinePersistence:
    # These tests pass their own session to the service (which commits +
    # refreshes); a self-managed session that closes inside the test body keeps
    # the connection lifecycle clean.
    async def test_persists_food_record_from_estimate(self, _uploads_tmp):
        from src.database import get_session_maker

        async with get_session_maker()() as db:
            user = await _new_user(db, "pipe")
            with patch.object(
                food_vision,
                "_call_vision",
                AsyncMock(return_value=_estimate_json(40, 55)),
            ):
                record = await food_vision.create_food_record_from_image(
                    db=db, user=user, raw_image=_png_bytes()
                )

            assert record.carbs_low == 40
            assert record.carbs_high == 55
            assert record.source == FoodRecordSource.AI_ESTIMATE
            assert record.ai_provider == AIProviderType.CLAUDE_API.value
            assert Path(record.storage_path).exists()

    async def test_rejects_out_of_bounds_estimate(self, _uploads_tmp):
        from src.database import get_session_maker

        async with get_session_maker()() as db:
            user = await _new_user(db, "oob")
            with (
                patch.object(
                    food_vision,
                    "_call_vision",
                    AsyncMock(return_value=_estimate_json(10, 99999)),
                ),
                pytest.raises(food_vision.EstimateRejectedError),
            ):
                await food_vision.create_food_record_from_image(
                    db=db, user=user, raw_image=_png_bytes()
                )

    async def test_scrubs_dosing_phrasing_from_description(self, _uploads_tmp):
        from src.database import get_session_maker

        async with get_session_maker()() as db:
            user = await _new_user(db, "scrub")
            bad = _estimate_json(desc="pasta -- take 5 units of insulin for this")
            with patch.object(food_vision, "_call_vision", AsyncMock(return_value=bad)):
                record = await food_vision.create_food_record_from_image(
                    db=db, user=user, raw_image=_png_bytes()
                )
            # The dosing-laden description must not be persisted.
            assert record.food_description is None


# --------------------------------------------------------------------------- #
# Safety: no IoB / treatment_safety / carb-ratio coupling (AC4)
# --------------------------------------------------------------------------- #
class TestNoTherapyCoupling:
    """The cornerstone safety AC: estimates never flow into dosing math."""

    def test_dosing_math_modules_do_not_reference_food_records(self):
        """Static guard: the therapy-math modules never import/read food records."""
        api_root = Path(__file__).resolve().parents[1]
        therapy_sources = [
            api_root / "src" / "services" / "iob_projection.py",
            api_root / "src" / "core" / "treatment_safety" / "validator.py",
            api_root / "src" / "core" / "treatment_safety" / "models.py",
            api_root / "src" / "core" / "treatment_safety" / "constants.py",
        ]
        for path in therapy_sources:
            text = path.read_text()
            assert "food_record" not in text.lower(), f"{path} references food records"
            assert "FoodRecord" not in text, f"{path} references FoodRecord"
            assert "common_food" not in text.lower(), f"{path} references common foods"
            assert "CommonFood" not in text, f"{path} references CommonFood"

    async def test_food_record_does_not_change_iob(self):
        """A logged meal must not produce or alter insulin-on-board."""
        from src.database import get_session_maker
        from src.models.user import User, UserRole
        from src.services.iob_projection import get_iob_projection

        async with get_session_maker()() as db:
            user = User(
                email=unique_email("iob"), hashed_password="x", role=UserRole.DIABETIC
            )
            db.add(user)
            await db.commit()

            before = await get_iob_projection(db, user.id)

            db.add(
                FoodRecord(
                    user_id=user.id,
                    filename="x.png",
                    file_type="png",
                    file_size_bytes=10,
                    storage_path="/uploads/food/x/x.png",
                    carbs_low=80,
                    carbs_high=120,
                    confidence="high",
                    source=FoodRecordSource.AI_ESTIMATE,
                )
            )
            await db.commit()

            after = await get_iob_projection(db, user.id)
            # No insulin doses exist -> IoB is None before and after; the food
            # record never created an insulin-on-board contribution.
            assert before is None
            assert after is None

    def test_response_schema_has_no_dose_field(self):
        from src.schemas.food_record import FoodRecordResponse

        fields = set(FoodRecordResponse.model_fields)
        for forbidden in ("dose", "units", "bolus", "insulin", "carb_ratio"):
            assert not any(forbidden in f for f in fields)


# --------------------------------------------------------------------------- #
# API endpoints (AC2/AC3/AC5)
# --------------------------------------------------------------------------- #
class TestFoodRecordsApi:
    async def test_requires_auth(self, _uploads_tmp):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/food-records")
        assert resp.status_code == 401

    async def test_disabled_when_flag_off(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "meal_intelligence_enabled", False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            cookie = await _register_login(client)
            client.cookies.set(settings.jwt_cookie_name, cookie)
            resp = await client.get("/api/food-records")
        assert resp.status_code == 404

    async def test_upload_creates_and_lists_record(self, auth_client):
        client, _ = auth_client
        with patch.object(
            food_vision, "_call_vision", AsyncMock(return_value=_estimate_json(30, 45))
        ):
            resp = await client.post(
                "/api/food-records",
                files={"file": ("meal.png", _png_bytes(), "image/png")},
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["carbs_low"] == 30
        assert body["carbs_high"] == 45
        assert body["source"] == "ai_estimate"
        assert "dose" not in body and "insulin" not in body

        listing = await client.get("/api/food-records")
        assert listing.status_code == 200
        assert listing.json()["total"] >= 1

    async def test_upload_rejects_non_image(self, auth_client):
        client, _ = auth_client
        resp = await client.post(
            "/api/food-records",
            files={"file": ("bad.png", b"not an image", "image/png")},
        )
        assert resp.status_code == 400

    async def test_upload_rejects_declared_bad_type(self, auth_client):
        client, _ = auth_client
        resp = await client.post(
            "/api/food-records",
            files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert resp.status_code == 415

    async def test_vision_unavailable_returns_422(self, auth_client):
        client, _ = auth_client
        with patch.object(
            food_vision,
            "_call_vision",
            AsyncMock(side_effect=food_vision.VisionUnavailableError("no vision")),
        ):
            resp = await client.post(
                "/api/food-records",
                files={"file": ("meal.png", _png_bytes(), "image/png")},
            )
        assert resp.status_code == 422
        assert "vision" in resp.json()["detail"].lower()

    async def test_no_provider_returns_404(self, _uploads_tmp):
        # No provider configured -> _resolve_model raises before any vision call.
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            cookie = await _register_login(client)
            client.cookies.set(settings.jwt_cookie_name, cookie)
            resp = await client.post(
                "/api/food-records",
                files={"file": ("meal.png", _png_bytes(), "image/png")},
            )
        assert resp.status_code == 404

    async def test_delete_removes_record_and_file(self, auth_client):
        client, _ = auth_client
        with patch.object(
            food_vision, "_call_vision", AsyncMock(return_value=_estimate_json())
        ):
            created = await client.post(
                "/api/food-records",
                files={"file": ("meal.png", _png_bytes(), "image/png")},
            )
        record_id = created.json()["id"]
        resp = await client.delete(f"/api/food-records/{record_id}")
        assert resp.status_code == 204
        # Gone afterwards.
        missing = await client.get(f"/api/food-records/{record_id}")
        assert missing.status_code == 404

    async def test_cannot_access_other_users_record(self, auth_client, _uploads_tmp):
        client, _ = auth_client
        with patch.object(
            food_vision, "_call_vision", AsyncMock(return_value=_estimate_json())
        ):
            created = await client.post(
                "/api/food-records",
                files={"file": ("meal.png", _png_bytes(), "image/png")},
            )
        record_id = created.json()["id"]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as other:
            cookie = await _register_login(other)
            other.cookies.set(settings.jwt_cookie_name, cookie)
            resp = await other.get(f"/api/food-records/{record_id}")
        assert resp.status_code == 404


async def _create_record(client: AsyncClient, low=40, high=55) -> dict:
    """Create a food record through the API (mocking the vision call)."""
    with patch.object(
        food_vision, "_call_vision", AsyncMock(return_value=_estimate_json(low, high))
    ):
        resp = await client.post(
            "/api/food-records",
            files={"file": ("meal.png", _png_bytes(), "image/png")},
        )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# Correction loop (AC1) -- provenance flip, original estimate preserved
# --------------------------------------------------------------------------- #
class TestCorrection:
    async def test_correction_flips_provenance_and_preserves_original(
        self, auth_client
    ):
        client, _ = auth_client
        created = await _create_record(client, 40, 55)
        record_id = created["id"]

        resp = await client.post(
            f"/api/food-records/{record_id}/correct",
            json={
                "corrected_carbs_low": 70,
                "corrected_carbs_high": 80,
                "corrected_nutrition": {"protein_grams": 20},
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Provenance flips; corrected values become the stored truth.
        assert body["source"] == "user_corrected"
        assert body["corrected_carbs_low"] == 70
        assert body["corrected_carbs_high"] == 80
        assert body["corrected_nutrition_json"] == {"protein_grams": 20}
        assert body["corrected_at"] is not None
        # Original AI estimate is retained, not overwritten.
        assert body["carbs_low"] == 40
        assert body["carbs_high"] == 55

    async def test_correction_rejects_out_of_bounds_not_clamped(self, auth_client):
        client, _ = auth_client
        created = await _create_record(client)
        record_id = created["id"]
        resp = await client.post(
            f"/api/food-records/{record_id}/correct",
            json={"corrected_carbs_low": 10, "corrected_carbs_high": 99999},
        )
        assert resp.status_code == 422

    async def test_correction_rejects_inverted_range(self, auth_client):
        client, _ = auth_client
        created = await _create_record(client)
        record_id = created["id"]
        resp = await client.post(
            f"/api/food-records/{record_id}/correct",
            json={"corrected_carbs_low": 80, "corrected_carbs_high": 20},
        )
        assert resp.status_code == 422

    async def test_correction_rejects_dose_fields(self, auth_client):
        # extra=forbid: a smuggled dose/units field is rejected at the boundary.
        client, _ = auth_client
        created = await _create_record(client)
        record_id = created["id"]
        resp = await client.post(
            f"/api/food-records/{record_id}/correct",
            json={
                "corrected_carbs_low": 30,
                "corrected_carbs_high": 40,
                "insulin_units": 5,
            },
        )
        assert resp.status_code == 422

    async def test_correction_rejects_oversized_nutrition(self, auth_client):
        # A single huge nutrition value (not just many keys) is rejected.
        client, _ = auth_client
        created = await _create_record(client)
        record_id = created["id"]
        resp = await client.post(
            f"/api/food-records/{record_id}/correct",
            json={
                "corrected_carbs_low": 30,
                "corrected_carbs_high": 40,
                "corrected_nutrition": {"note": "x" * 5000},
            },
        )
        assert resp.status_code == 422

    async def test_cannot_correct_other_users_record(self, auth_client):
        client, _ = auth_client
        created = await _create_record(client)
        record_id = created["id"]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as other:
            cookie = await _register_login(other)
            other.cookies.set(settings.jwt_cookie_name, cookie)
            resp = await other.post(
                f"/api/food-records/{record_id}/correct",
                json={"corrected_carbs_low": 30, "corrected_carbs_high": 40},
            )
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Food-identity confirmation gate (Story 50.H2)
# --------------------------------------------------------------------------- #
class TestIdentityConfirmation:
    async def test_fresh_estimate_is_unconfirmed(self, auth_client):
        client, _ = auth_client
        created = await _create_record(client)
        # A fresh estimate is never auto-grounded: identity unconfirmed, no
        # grounding source attached.
        assert created["identity_confirmed"] is False
        assert created["confirmed_food_name"] is None
        assert created["grounding_source"] is None

    async def test_confirm_identity_persists_and_opens_gate(self, auth_client):
        client, _ = auth_client
        created = await _create_record(client)
        record_id = created["id"]
        resp = await client.post(
            f"/api/food-records/{record_id}/confirm-identity",
            json={"confirmed_food_name": "bowl of pasta"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["identity_confirmed"] is True
        assert body["confirmed_food_name"] == "bowl of pasta"
        # Carbs are untouched by an identity confirmation (never a dose).
        assert body["carbs_low"] == created["carbs_low"]
        assert body["carbs_high"] == created["carbs_high"]

    async def test_confirm_identity_rejects_blank(self, auth_client):
        client, _ = auth_client
        created = await _create_record(client)
        record_id = created["id"]
        for bad in ({"confirmed_food_name": "   "}, {"confirmed_food_name": ""}, {}):
            resp = await client.post(
                f"/api/food-records/{record_id}/confirm-identity", json=bad
            )
            assert resp.status_code == 422, bad

    async def test_confirm_identity_rejects_extra_fields(self, auth_client):
        # extra=forbid: a smuggled dose field is rejected at the boundary.
        client, _ = auth_client
        created = await _create_record(client)
        record_id = created["id"]
        resp = await client.post(
            f"/api/food-records/{record_id}/confirm-identity",
            json={"confirmed_food_name": "pasta", "insulin_units": 5},
        )
        assert resp.status_code == 422

    async def test_cannot_confirm_other_users_record(self, auth_client):
        client, _ = auth_client
        created = await _create_record(client)
        record_id = created["id"]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as other:
            cookie = await _register_login(other)
            other.cookies.set(settings.jwt_cookie_name, cookie)
            resp = await other.post(
                f"/api/food-records/{record_id}/confirm-identity",
                json={"confirmed_food_name": "pasta"},
            )
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Estimate auditability & provenance (Story 50.H3)
# --------------------------------------------------------------------------- #
class TestEstimateAudit:
    async def test_audit_endpoint_returns_provenance(self, auth_client):
        client, _ = auth_client
        created = await _create_record(client)
        record_id = created["id"]
        # Confirm identity so the precedence reflects a grounding decision.
        await client.post(
            f"/api/food-records/{record_id}/confirm-identity",
            json={"confirmed_food_name": "bowl of pasta"},
        )
        resp = await client.get(f"/api/food-records/{record_id}/audit")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["food_record_id"] == record_id
        assert body["samples"]  # raw per-sample reads present
        assert body["precedence"]["identity_confirmed"] is True
        # Self-reported confidence is internal-only -- never in the response.
        assert "self_reported_confidence" not in resp.text

    async def test_audit_endpoint_is_owner_scoped(self, auth_client):
        client, _ = auth_client
        created = await _create_record(client)
        record_id = created["id"]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as other:
            cookie = await _register_login(other)
            other.cookies.set(settings.jwt_cookie_name, cookie)
            resp = await other.get(f"/api/food-records/{record_id}/audit")
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Common foods: promotion, dedupe, linking, management (AC2/AC3)
# --------------------------------------------------------------------------- #
class TestCommonFoods:
    async def test_save_as_common_food_uses_corrected_values(self, auth_client):
        client, _ = auth_client
        created = await _create_record(client, 40, 55)
        record_id = created["id"]
        # Correct first; the promotion should baseline the corrected values.
        await client.post(
            f"/api/food-records/{record_id}/correct",
            json={"corrected_carbs_low": 70, "corrected_carbs_high": 75},
        )
        resp = await client.post(
            f"/api/food-records/{record_id}/save-as-common-food",
            json={"name": "Oatmeal Bowl"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == "Oatmeal Bowl"
        assert body["carbs_low"] == 70
        assert body["carbs_high"] == 75

        # The record is now linked to the baseline.
        record = await client.get(f"/api/food-records/{record_id}")
        assert record.json()["common_food_id"] == body["id"]

    async def test_save_as_common_food_uses_ai_values_when_uncorrected(
        self, auth_client
    ):
        client, _ = auth_client
        created = await _create_record(client, 30, 45)
        resp = await client.post(
            f"/api/food-records/{created['id']}/save-as-common-food",
            json={"name": "Toast"},
        )
        assert resp.status_code == 201
        assert resp.json()["carbs_low"] == 30
        assert resp.json()["carbs_high"] == 45

    async def test_dedupe_same_name_updates_single_baseline(self, auth_client):
        client, _ = auth_client
        first = await _create_record(client, 30, 40)
        second = await _create_record(client, 50, 60)

        r1 = await client.post(
            f"/api/food-records/{first['id']}/save-as-common-food",
            json={"name": "Pasta"},
        )
        # Same name (different casing/spacing) -> updates the same baseline.
        r2 = await client.post(
            f"/api/food-records/{second['id']}/save-as-common-food",
            json={"name": "  pasta  "},
        )
        assert r1.json()["id"] == r2.json()["id"]
        assert r2.json()["carbs_low"] == 50
        assert r2.json()["carbs_high"] == 60

        listing = await client.get("/api/common-foods")
        names = [f["name"] for f in listing.json()["common_foods"]]
        assert names.count("Pasta") + names.count("pasta") == 1

    async def test_link_existing_record_to_common_food(self, auth_client):
        client, _ = auth_client
        seed = await _create_record(client, 30, 40)
        cf = await client.post(
            f"/api/food-records/{seed['id']}/save-as-common-food",
            json={"name": "Rice"},
        )
        common_food_id = cf.json()["id"]

        other_record = await _create_record(client, 35, 45)
        resp = await client.post(
            f"/api/food-records/{other_record['id']}/link-common-food",
            json={"common_food_id": common_food_id},
        )
        assert resp.status_code == 200
        assert resp.json()["common_food_id"] == common_food_id

    async def test_rename_and_update_baseline(self, auth_client):
        client, _ = auth_client
        seed = await _create_record(client, 30, 40)
        cf = await client.post(
            f"/api/food-records/{seed['id']}/save-as-common-food",
            json={"name": "Cereal"},
        )
        cf_id = cf.json()["id"]
        resp = await client.patch(
            f"/api/common-foods/{cf_id}",
            json={"name": "Granola", "carbs_low": 45, "carbs_high": 50},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Granola"
        assert resp.json()["carbs_low"] == 45

    async def test_rename_collision_returns_409(self, auth_client):
        client, _ = auth_client
        a = await _create_record(client, 30, 40)
        b = await _create_record(client, 30, 40)
        cf_a = await client.post(
            f"/api/food-records/{a['id']}/save-as-common-food", json={"name": "Apple"}
        )
        await client.post(
            f"/api/food-records/{b['id']}/save-as-common-food", json={"name": "Banana"}
        )
        resp = await client.patch(
            f"/api/common-foods/{cf_a.json()['id']}", json={"name": "banana"}
        )
        assert resp.status_code == 409

    async def test_promote_corrected_carbs_keeps_ai_nutrition(self, auth_client):
        # Correct carbs only (no corrected nutrition) -> the promoted baseline
        # carries the corrected carbs but the original AI nutrition.
        client, _ = auth_client
        created = await _create_record(client, 40, 55)
        record_id = created["id"]
        await client.post(
            f"/api/food-records/{record_id}/correct",
            json={"corrected_carbs_low": 70, "corrected_carbs_high": 75},
        )
        resp = await client.post(
            f"/api/food-records/{record_id}/save-as-common-food",
            json={"name": "Burrito"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["carbs_low"] == 70
        # _estimate_json seeds AI nutrition {"protein_grams": 12, "calories": 520}.
        assert body["nutrition_json"] == {"protein_grams": 12, "calories": 520}

    async def test_update_rejects_partial_carb_range(self, auth_client):
        client, _ = auth_client
        seed = await _create_record(client, 30, 40)
        cf = await client.post(
            f"/api/food-records/{seed['id']}/save-as-common-food",
            json={"name": "Soup"},
        )
        # Only one carb bound -> schema rejects (can't form a valid range).
        resp = await client.patch(
            f"/api/common-foods/{cf.json()['id']}", json={"carbs_low": 20}
        )
        assert resp.status_code == 422

    async def test_delete_common_food_unlinks_records(self, auth_client):
        client, _ = auth_client
        seed = await _create_record(client, 30, 40)
        cf = await client.post(
            f"/api/food-records/{seed['id']}/save-as-common-food",
            json={"name": "Yogurt"},
        )
        cf_id = cf.json()["id"]
        resp = await client.delete(f"/api/common-foods/{cf_id}")
        assert resp.status_code == 204
        # The previously-linked record survives, now unlinked (SET NULL).
        record = await client.get(f"/api/food-records/{seed['id']}")
        assert record.status_code == 200
        assert record.json()["common_food_id"] is None

    async def test_cannot_link_other_users_common_food(self, auth_client, db_session):
        client, _ = auth_client
        my_record = await _create_record(client, 30, 40)

        # Another user's baseline, seeded directly (the IDOR target).
        from src.models.common_food import CommonFood

        other = await _new_user(db_session, "link-idor")
        their_cf = CommonFood(
            user_id=other.id,
            name="Secret",
            normalized_name="secret",
            carbs_low=30,
            carbs_high=40,
        )
        db_session.add(their_cf)
        await db_session.commit()

        resp = await client.post(
            f"/api/food-records/{my_record['id']}/link-common-food",
            json={"common_food_id": str(their_cf.id)},
        )
        assert resp.status_code == 404

    async def test_cannot_access_other_users_common_food(self, auth_client):
        client, _ = auth_client
        seed = await _create_record(client, 30, 40)
        cf = await client.post(
            f"/api/food-records/{seed['id']}/save-as-common-food",
            json={"name": "Mine"},
        )
        cf_id = cf.json()["id"]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as other:
            cookie = await _register_login(other)
            other.cookies.set(settings.jwt_cookie_name, cookie)
            assert (await other.get(f"/api/common-foods/{cf_id}")).status_code == 404
            assert (
                await other.patch(f"/api/common-foods/{cf_id}", json={"name": "Hijack"})
            ).status_code == 404
            assert (await other.delete(f"/api/common-foods/{cf_id}")).status_code == 404
            # The owner's baseline is untouched.
        assert (await client.get(f"/api/common-foods/{cf_id}")).json()["name"] == "Mine"

    async def test_common_foods_listing_is_owner_scoped(self, auth_client):
        client, _ = auth_client
        seed = await _create_record(client, 30, 40)
        await client.post(
            f"/api/food-records/{seed['id']}/save-as-common-food",
            json={"name": "OnlyMine"},
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as other:
            cookie = await _register_login(other)
            other.cookies.set(settings.jwt_cookie_name, cookie)
            listing = await other.get("/api/common-foods")
        names = [f["name"] for f in listing.json()["common_foods"]]
        assert "OnlyMine" not in names

    async def test_common_foods_disabled_when_flag_off(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "meal_intelligence_enabled", False)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            cookie = await _register_login(client)
            client.cookies.set(settings.jwt_cookie_name, cookie)
            resp = await client.get("/api/common-foods")
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Safety: corrected + common-food values never flow into dosing math (AC4)
# --------------------------------------------------------------------------- #
class TestCorrectionNoTherapyCoupling:
    async def test_correction_does_not_change_iob(self, _uploads_tmp):
        """Correcting a meal must not produce or alter insulin-on-board."""
        from src.database import get_session_maker
        from src.models.user import User, UserRole
        from src.schemas.food_record import FoodRecordCorrectionRequest
        from src.services import common_food as common_food_service
        from src.services.iob_projection import get_iob_projection

        async with get_session_maker()() as db:
            user = User(
                email=unique_email("c-iob"),
                hashed_password="x",
                role=UserRole.DIABETIC,
            )
            db.add(user)
            await db.commit()

            before = await get_iob_projection(db, user.id)

            record = FoodRecord(
                user_id=user.id,
                filename="x.png",
                file_type="png",
                file_size_bytes=10,
                storage_path="/uploads/food/x/x.png",
                carbs_low=40,
                carbs_high=55,
                confidence="high",
                source=FoodRecordSource.AI_ESTIMATE,
            )
            db.add(record)
            await db.commit()

            await common_food_service.correct_food_record(
                db,
                record,
                FoodRecordCorrectionRequest(
                    corrected_carbs_low=120, corrected_carbs_high=150
                ),
            )
            await common_food_service.promote_to_common_food(db, record, "Big Meal")

            after = await get_iob_projection(db, user.id)
            # No insulin doses exist -> IoB is None before and after; neither the
            # correction nor the common-food baseline created an IoB contribution.
            assert before is None
            assert after is None

    def test_common_food_schema_has_no_dose_field(self):
        from src.schemas.common_food import CommonFoodResponse

        fields = set(CommonFoodResponse.model_fields)
        for forbidden in ("dose", "units", "bolus", "insulin", "carb_ratio"):
            assert not any(forbidden in f for f in fields)


# --------------------------------------------------------------------------- #
# Account purge clears common foods (and unlinks)
# --------------------------------------------------------------------------- #
class TestPurgeClearsCommonFoods:
    async def test_purge_deletes_common_foods(self, _uploads_tmp):
        from src.database import get_session_maker
        from src.models.common_food import CommonFood
        from src.services.data_purge import purge_all_user_data

        async with get_session_maker()() as db:
            user = await _new_user(db, "purge-cf")
            db.add(
                CommonFood(
                    user_id=user.id,
                    name="Sandwich",
                    normalized_name="sandwich",
                    carbs_low=40,
                    carbs_high=50,
                )
            )
            await db.commit()

            deleted = await purge_all_user_data(user.id, db)
            assert deleted["common_foods"] == 1

            remaining = await db.scalar(
                select(func.count())
                .select_from(CommonFood)
                .where(CommonFood.user_id == user.id)
            )
            assert remaining == 0
