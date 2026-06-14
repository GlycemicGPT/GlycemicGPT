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
