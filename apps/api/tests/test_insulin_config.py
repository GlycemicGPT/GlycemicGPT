"""Tests for insulin configuration service and settings router."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from src.config import settings
from src.main import app
from src.schemas.insulin_config import (
    INSULIN_PRESETS,
    VALID_INSULIN_TYPES,
    InsulinConfigDefaults,
    InsulinConfigUpdate,
)
from src.services.insulin_config import get_or_create_config, update_config


def unique_email(prefix: str = "test") -> str:
    """Generate a unique email for testing."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def register_and_login(client) -> str:
    """Register a new user and return the session cookie value."""
    email = unique_email("insulin_cfg")
    password = "SecurePass123"

    await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )

    login_response = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )

    return login_response.cookies.get(settings.jwt_cookie_name)


# Bolus insulins added to the picker. Rapid analogs reuse a shipped molecule's
# PK (aspart/lispro), so they inherit the existing 4.0h/15min curve; regular
# (short-acting) human insulins use a longer DIA and later onset.
ADDED_RAPID_ANALOG_TYPES = ("novorapid", "liprolog", "admelog", "trurapi", "kirsty")
ADDED_REGULAR_HUMAN_TYPES = ("humulin_r", "novolin_r", "insuman_rapid")


# -- Schema validation tests --


class TestInsulinConfigUpdate:
    """Tests for InsulinConfigUpdate schema validation."""

    def test_all_none_is_valid(self):
        update = InsulinConfigUpdate()
        assert update.insulin_type is None
        assert update.dia_hours is None
        assert update.onset_minutes is None

    def test_partial_update_type_only(self):
        update = InsulinConfigUpdate(insulin_type="fiasp")
        assert update.insulin_type == "fiasp"
        assert update.dia_hours is None

    def test_dia_below_range_fails(self):
        with pytest.raises(ValidationError):
            InsulinConfigUpdate(dia_hours=1.0)

    def test_dia_above_range_fails(self):
        with pytest.raises(ValidationError):
            InsulinConfigUpdate(dia_hours=10.0)

    def test_onset_below_range_fails(self):
        with pytest.raises(ValidationError):
            InsulinConfigUpdate(onset_minutes=0.5)

    def test_onset_above_range_fails(self):
        with pytest.raises(ValidationError):
            InsulinConfigUpdate(onset_minutes=61.0)

    def test_valid_full_update(self):
        update = InsulinConfigUpdate(
            insulin_type="lyumjev",
            dia_hours=3.5,
            onset_minutes=5.0,
        )
        assert update.insulin_type == "lyumjev"
        assert update.dia_hours == 3.5
        assert update.onset_minutes == 5.0

    @pytest.mark.parametrize("insulin_type", ADDED_RAPID_ANALOG_TYPES)
    def test_added_rapid_analog_type_accepted(self, insulin_type):
        update = InsulinConfigUpdate(insulin_type=insulin_type)
        assert update.insulin_type == insulin_type

    @pytest.mark.parametrize("insulin_type", ADDED_REGULAR_HUMAN_TYPES)
    def test_added_regular_human_type_accepted(self, insulin_type):
        update = InsulinConfigUpdate(insulin_type=insulin_type)
        assert update.insulin_type == insulin_type

    def test_unknown_insulin_type_rejected(self):
        with pytest.raises(ValidationError):
            InsulinConfigUpdate(insulin_type="not_an_insulin")


class TestInsulinConfigDefaults:
    """Tests for InsulinConfigDefaults schema."""

    def test_default_values(self):
        defaults = InsulinConfigDefaults()
        assert defaults.insulin_type == "humalog"
        assert defaults.dia_hours == 4.0
        assert defaults.onset_minutes == 15.0

    def test_presets_contain_expected_types(self):
        defaults = InsulinConfigDefaults()
        assert "humalog" in defaults.presets
        assert "fiasp" in defaults.presets
        assert "lyumjev" in defaults.presets

    def test_fiasp_preset_values(self):
        assert INSULIN_PRESETS["fiasp"]["dia_hours"] == 3.5
        assert INSULIN_PRESETS["fiasp"]["onset_minutes"] == 5.0

    @pytest.mark.parametrize(
        "insulin_type", ADDED_RAPID_ANALOG_TYPES + ADDED_REGULAR_HUMAN_TYPES
    )
    def test_added_types_have_presets(self, insulin_type):
        defaults = InsulinConfigDefaults()
        assert insulin_type in defaults.presets

    @pytest.mark.parametrize("insulin_type", ADDED_RAPID_ANALOG_TYPES)
    def test_rapid_analog_presets_reuse_molecule_pk(self, insulin_type):
        # A brand sharing a molecule with a shipped analog inherits its curve.
        assert INSULIN_PRESETS[insulin_type]["dia_hours"] == 4.0
        assert INSULIN_PRESETS[insulin_type]["onset_minutes"] == 15.0

    @pytest.mark.parametrize("insulin_type", ADDED_REGULAR_HUMAN_TYPES)
    def test_regular_human_preset_values(self, insulin_type):
        assert INSULIN_PRESETS[insulin_type]["dia_hours"] == 6.0
        assert INSULIN_PRESETS[insulin_type]["onset_minutes"] == 30.0

    def test_presets_and_valid_types_stay_consistent(self):
        # Drift guard: every preset key is a valid type, and "custom" is the
        # only valid type without a preset.
        assert set(INSULIN_PRESETS).issubset(VALID_INSULIN_TYPES)
        assert VALID_INSULIN_TYPES - set(INSULIN_PRESETS) == {"custom"}

    def test_every_preset_is_savable(self):
        # Selecting a preset auto-fills the form, so every preset must produce a
        # payload the InsulinConfigUpdate validator accepts -- otherwise the
        # auto-filled value would 422 on save. Construct the schema instead of
        # re-encoding its bounds so this tracks the validator (and the
        # allow-list) automatically.
        for insulin_type, values in INSULIN_PRESETS.items():
            InsulinConfigUpdate(
                insulin_type=insulin_type,
                dia_hours=values["dia_hours"],
                onset_minutes=values["onset_minutes"],
            )


# -- Service tests --


class TestGetOrCreateInsulinConfig:
    """Tests for get_or_create_config service function."""

    @pytest.mark.asyncio
    async def test_creates_defaults_when_none_exist(self):
        """Should create a new InsulinConfig with defaults."""
        user_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(return_value=None)

        result = await get_or_create_config(user_id, mock_db)

        assert result.user_id == user_id
        mock_db.add.assert_called_once_with(result)
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once_with(result)

    @pytest.mark.asyncio
    async def test_returns_existing_when_found(self):
        """Should return existing record without creating."""
        user_id = uuid.uuid4()
        existing = MagicMock()
        existing.user_id = user_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        result = await get_or_create_config(user_id, mock_db)

        assert result == existing
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()


class TestUpdateInsulinConfig:
    """Tests for update_config service function."""

    @pytest.mark.asyncio
    async def test_partial_update_type_only(self):
        """Should only update insulin_type."""
        user_id = uuid.uuid4()
        existing = MagicMock()
        existing.user_id = user_id
        existing.insulin_type = "humalog"
        existing.dia_hours = 4.0
        existing.onset_minutes = 15.0

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        updates = InsulinConfigUpdate(insulin_type="fiasp")
        result = await update_config(user_id, updates, mock_db)

        assert result.insulin_type == "fiasp"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_update(self):
        """Should update all fields."""
        user_id = uuid.uuid4()
        existing = MagicMock()
        existing.user_id = user_id
        existing.insulin_type = "humalog"
        existing.dia_hours = 4.0
        existing.onset_minutes = 15.0

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        updates = InsulinConfigUpdate(
            insulin_type="lyumjev",
            dia_hours=3.5,
            onset_minutes=5.0,
        )
        result = await update_config(user_id, updates, mock_db)

        assert result.insulin_type == "lyumjev"
        assert result.dia_hours == 3.5
        assert result.onset_minutes == 5.0
        mock_db.commit.assert_called_once()


# -- Endpoint integration tests --


class TestInsulinConfigEndpoints:
    """Tests for the insulin config settings endpoints."""

    async def test_get_insulin_config_requires_auth(self):
        """GET /api/settings/insulin-config requires authentication."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/settings/insulin-config")
        assert response.status_code == 401

    async def test_patch_insulin_config_requires_auth(self):
        """PATCH /api/settings/insulin-config requires authentication."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.patch(
                "/api/settings/insulin-config",
                json={"insulin_type": "fiasp"},
            )
        assert response.status_code == 401

    async def test_get_defaults_no_auth(self):
        """GET /api/settings/insulin-config/defaults does not require auth."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/settings/insulin-config/defaults")
        assert response.status_code == 200
        data = response.json()
        assert data["insulin_type"] == "humalog"
        assert data["dia_hours"] == 4.0
        assert "presets" in data
        assert "fiasp" in data["presets"]

    async def test_get_insulin_config_returns_defaults(self):
        """GET should return defaults for new user."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)
            response = await client.get(
                "/api/settings/insulin-config",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["insulin_type"] == "humalog"
        assert data["dia_hours"] == 4.0
        assert data["onset_minutes"] == 15.0

    async def test_patch_insulin_config_updates(self):
        """PATCH should update insulin config."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)
            response = await client.patch(
                "/api/settings/insulin-config",
                json={"insulin_type": "fiasp", "dia_hours": 3.5, "onset_minutes": 5.0},
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["insulin_type"] == "fiasp"
        assert data["dia_hours"] == 3.5
        assert data["onset_minutes"] == 5.0

    async def test_patch_partial_update(self):
        """PATCH with partial data should only update provided fields."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)
            # First get defaults
            response = await client.get(
                "/api/settings/insulin-config",
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert response.status_code == 200
            assert response.json()["dia_hours"] == 4.0

            # Partial update - only type
            response = await client.patch(
                "/api/settings/insulin-config",
                json={"insulin_type": "novolog"},
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["insulin_type"] == "novolog"
            # DIA should remain unchanged (4.0)
            assert data["dia_hours"] == 4.0

    async def test_patch_invalid_dia_rejected(self):
        """PATCH with DIA out of range should return 422."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)
            response = await client.patch(
                "/api/settings/insulin-config",
                json={"dia_hours": 0.5},
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert response.status_code == 422

    async def test_patch_unknown_insulin_type_returns_422(self):
        """PATCH with a type outside the allow-list is rejected at the body."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)
            response = await client.patch(
                "/api/settings/insulin-config",
                json={"insulin_type": "not_an_insulin"},
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert response.status_code == 422

    @pytest.mark.parametrize("insulin_type", ("novorapid", "humulin_r"))
    async def test_patch_new_insulin_type_persists(self, insulin_type):
        """A newly added bolus insulin saves and reads back unchanged."""
        preset = INSULIN_PRESETS[insulin_type]
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            cookie = await register_and_login(client)
            patch_response = await client.patch(
                "/api/settings/insulin-config",
                json={
                    "insulin_type": insulin_type,
                    "dia_hours": preset["dia_hours"],
                    "onset_minutes": preset["onset_minutes"],
                },
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert patch_response.status_code == 200
            get_response = await client.get(
                "/api/settings/insulin-config",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert patch_response.json()["insulin_type"] == insulin_type
        data = get_response.json()
        assert data["insulin_type"] == insulin_type
        assert data["dia_hours"] == preset["dia_hours"]
        assert data["onset_minutes"] == preset["onset_minutes"]
