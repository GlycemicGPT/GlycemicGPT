"""Tests for safety limits service and settings router."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from src.config import settings
from src.schemas.safety_limits import (
    SafetyLimitsDefaults,
    SafetyLimitsUpdate,
)
from src.services.safety_limits import get_or_create_safety_limits, update_safety_limits


def unique_email(prefix: str = "test") -> str:
    """Generate a unique email for testing."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def register_and_login(client) -> str:
    """Register a new user and return the session cookie value."""
    email = unique_email("safety_limits")
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


# -- Schema validation tests --


class TestSafetyLimitsUpdate:
    """Tests for SafetyLimitsUpdate schema validation."""

    def test_all_none_is_valid(self):
        update = SafetyLimitsUpdate()
        assert update.min_glucose_mgdl is None
        assert update.max_glucose_mgdl is None
        assert update.max_basal_rate_milliunits is None
        assert update.max_bolus_dose_milliunits is None

    def test_partial_update_min_glucose(self):
        update = SafetyLimitsUpdate(min_glucose_mgdl=40)
        assert update.min_glucose_mgdl == 40
        assert update.max_glucose_mgdl is None

    def test_partial_update_max_glucose(self):
        update = SafetyLimitsUpdate(max_glucose_mgdl=400)
        assert update.max_glucose_mgdl == 400

    def test_partial_update_basal(self):
        update = SafetyLimitsUpdate(max_basal_rate_milliunits=10000)
        assert update.max_basal_rate_milliunits == 10000

    def test_partial_update_bolus(self):
        update = SafetyLimitsUpdate(max_bolus_dose_milliunits=20000)
        assert update.max_bolus_dose_milliunits == 20000

    def test_min_ge_max_glucose_fails(self):
        with pytest.raises(
            ValidationError,
            match="min_glucose_mgdl must be less than max_glucose_mgdl",
        ):
            SafetyLimitsUpdate(min_glucose_mgdl=300, max_glucose_mgdl=200)

    def test_min_equal_max_glucose_fails(self):
        with pytest.raises(
            ValidationError,
            match="min_glucose_mgdl must be less than max_glucose_mgdl",
        ):
            SafetyLimitsUpdate(min_glucose_mgdl=200, max_glucose_mgdl=200)

    def test_valid_glucose_ordering_passes(self):
        update = SafetyLimitsUpdate(min_glucose_mgdl=40, max_glucose_mgdl=400)
        assert update.min_glucose_mgdl == 40
        assert update.max_glucose_mgdl == 400

    def test_min_glucose_below_range_fails(self):
        with pytest.raises(ValidationError):
            SafetyLimitsUpdate(min_glucose_mgdl=19)

    def test_min_glucose_above_range_fails(self):
        with pytest.raises(ValidationError):
            SafetyLimitsUpdate(min_glucose_mgdl=500)

    def test_max_glucose_below_range_fails(self):
        with pytest.raises(ValidationError):
            SafetyLimitsUpdate(max_glucose_mgdl=20)

    def test_max_glucose_above_range_fails(self):
        with pytest.raises(ValidationError):
            SafetyLimitsUpdate(max_glucose_mgdl=501)

    def test_basal_below_range_fails(self):
        with pytest.raises(ValidationError):
            SafetyLimitsUpdate(max_basal_rate_milliunits=0)

    def test_basal_above_range_fails(self):
        with pytest.raises(ValidationError):
            SafetyLimitsUpdate(max_basal_rate_milliunits=15001)

    def test_bolus_below_range_fails(self):
        with pytest.raises(ValidationError):
            SafetyLimitsUpdate(max_bolus_dose_milliunits=0)

    def test_bolus_above_range_fails(self):
        with pytest.raises(ValidationError):
            SafetyLimitsUpdate(max_bolus_dose_milliunits=25001)


class TestSafetyLimitsDefaults:
    """Tests for SafetyLimitsDefaults schema."""

    def test_default_values(self):
        defaults = SafetyLimitsDefaults()
        assert defaults.min_glucose_mgdl == 20
        assert defaults.max_glucose_mgdl == 500
        assert defaults.max_basal_rate_milliunits == 15000
        assert defaults.max_bolus_dose_milliunits == 25000


# -- Service tests --


class TestGetOrCreateSafetyLimits:
    """Tests for get_or_create_safety_limits service function."""

    @pytest.mark.asyncio
    async def test_creates_defaults_when_none_exist(self):
        """Should create a new SafetyLimits with defaults."""
        user_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(return_value=None)

        result = await get_or_create_safety_limits(user_id, mock_db)

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

        result = await get_or_create_safety_limits(user_id, mock_db)

        assert result == existing
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_integrity_error_race(self):
        """Should handle concurrent insert race by re-fetching."""
        user_id = uuid.uuid4()

        # First execute: no existing record
        first_result = MagicMock()
        first_result.scalar_one_or_none.return_value = None

        # Second execute (after IntegrityError): return the concurrently created record
        existing = MagicMock()
        existing.user_id = user_id
        second_result = MagicMock()
        second_result.scalar_one.return_value = existing

        mock_db = AsyncMock()
        mock_db.execute.side_effect = [first_result, second_result]
        mock_db.commit.side_effect = IntegrityError(
            statement="INSERT",
            params={},
            orig=Exception("duplicate key"),
        )
        mock_db.rollback = AsyncMock()

        result = await get_or_create_safety_limits(user_id, mock_db)

        assert result == existing
        mock_db.rollback.assert_called_once()


class TestUpdateSafetyLimits:
    """Tests for update_safety_limits service function.

    Note: update_safety_limits does two db.execute() calls:
    1. get_or_create_safety_limits (uses scalar_one_or_none)
    2. SELECT ... FOR UPDATE (uses scalar_one)
    The mock_result supports both accessor patterns.
    """

    @pytest.mark.asyncio
    async def test_partial_update_min_glucose(self):
        """Should only update min_glucose_mgdl."""
        user_id = uuid.uuid4()
        existing = MagicMock()
        existing.user_id = user_id
        existing.min_glucose_mgdl = 20
        existing.max_glucose_mgdl = 500
        existing.max_basal_rate_milliunits = 15000
        existing.max_bolus_dose_milliunits = 25000

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_result.scalar_one.return_value = existing

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        updates = SafetyLimitsUpdate(min_glucose_mgdl=40)
        result = await update_safety_limits(user_id, updates, mock_db)

        assert result.min_glucose_mgdl == 40
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_ordering_near_boundary_passes(self):
        """Should allow min < max at boundary (499 < 500)."""
        user_id = uuid.uuid4()
        existing = MagicMock()
        existing.user_id = user_id
        existing.min_glucose_mgdl = 20
        existing.max_glucose_mgdl = 500
        existing.max_basal_rate_milliunits = 15000
        existing.max_bolus_dose_milliunits = 25000

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_result.scalar_one.return_value = existing

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        # Set max_glucose below existing min_glucose (20) -- but 21 is allowed
        # so set min above existing max (500)
        updates = SafetyLimitsUpdate(min_glucose_mgdl=499)

        # After merge: min=499, max=500 -- this is valid (499 < 500)
        result = await update_safety_limits(user_id, updates, mock_db)
        assert result.min_glucose_mgdl == 499

    @pytest.mark.asyncio
    async def test_ordering_violation_min_equal_max(self):
        """Should raise ValueError when min == max after merge."""
        user_id = uuid.uuid4()
        existing = MagicMock()
        existing.user_id = user_id
        existing.min_glucose_mgdl = 20
        existing.max_glucose_mgdl = 100
        existing.max_basal_rate_milliunits = 15000
        existing.max_bolus_dose_milliunits = 25000

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_result.scalar_one.return_value = existing

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        updates = SafetyLimitsUpdate(min_glucose_mgdl=100)

        with pytest.raises(
            ValueError,
            match="min_glucose_mgdl.*must be less than.*max_glucose_mgdl",
        ):
            await update_safety_limits(user_id, updates, mock_db)

    @pytest.mark.asyncio
    async def test_partial_update_basal(self):
        """Should only update max_basal_rate_milliunits."""
        user_id = uuid.uuid4()
        existing = MagicMock()
        existing.user_id = user_id
        existing.min_glucose_mgdl = 20
        existing.max_glucose_mgdl = 500
        existing.max_basal_rate_milliunits = 15000
        existing.max_bolus_dose_milliunits = 25000

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_result.scalar_one.return_value = existing

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        updates = SafetyLimitsUpdate(max_basal_rate_milliunits=10000)
        result = await update_safety_limits(user_id, updates, mock_db)

        assert result.max_basal_rate_milliunits == 10000
        mock_db.commit.assert_called_once()


# -- Endpoint tests --


class TestGetSafetyLimitsEndpoint:
    """Tests for GET /api/settings/safety-limits."""

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get("/api/settings/safety-limits")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_authenticated_returns_defaults(self, client):
        cookie = await register_and_login(client)
        response = await client.get(
            "/api/settings/safety-limits",
            cookies={settings.jwt_cookie_name: cookie},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["min_glucose_mgdl"] == 20
        assert data["max_glucose_mgdl"] == 500
        assert data["max_basal_rate_milliunits"] == 15000
        assert data["max_bolus_dose_milliunits"] == 25000
        assert "id" in data
        assert "updated_at" in data

    @pytest.mark.asyncio
    async def test_idempotent_get_or_create(self, client):
        """Calling GET twice should return the same record."""
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        r1 = await client.get("/api/settings/safety-limits", cookies=cookies)
        r2 = await client.get("/api/settings/safety-limits", cookies=cookies)

        assert r1.json()["id"] == r2.json()["id"]


class TestPatchSafetyLimitsEndpoint:
    """Tests for PATCH /api/settings/safety-limits."""

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        response = await client.patch(
            "/api/settings/safety-limits",
            json={"min_glucose_mgdl": 40},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_range_returns_422(self, client):
        cookie = await register_and_login(client)
        response = await client.patch(
            "/api/settings/safety-limits",
            json={"min_glucose_mgdl": 10},
            cookies={settings.jwt_cookie_name: cookie},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_ordering_violation_returns_422(self, client):
        """Setting min_glucose above max_glucose should fail."""
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        await client.get("/api/settings/safety-limits", cookies=cookies)

        response = await client.patch(
            "/api/settings/safety-limits",
            json={"min_glucose_mgdl": 499, "max_glucose_mgdl": 21},
            cookies=cookies,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_valid_partial_update(self, client):
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        response = await client.patch(
            "/api/settings/safety-limits",
            json={"min_glucose_mgdl": 40},
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["min_glucose_mgdl"] == 40
        assert data["max_glucose_mgdl"] == 500
        assert data["max_basal_rate_milliunits"] == 15000
        assert data["max_bolus_dose_milliunits"] == 25000

    @pytest.mark.asyncio
    async def test_update_all_fields(self, client):
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        response = await client.patch(
            "/api/settings/safety-limits",
            json={
                "min_glucose_mgdl": 40,
                "max_glucose_mgdl": 400,
                "max_basal_rate_milliunits": 10000,
                "max_bolus_dose_milliunits": 20000,
            },
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["min_glucose_mgdl"] == 40
        assert data["max_glucose_mgdl"] == 400
        assert data["max_basal_rate_milliunits"] == 10000
        assert data["max_bolus_dose_milliunits"] == 20000

    @pytest.mark.asyncio
    async def test_persists_across_requests(self, client):
        """Updated values should persist when fetched again."""
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        await client.patch(
            "/api/settings/safety-limits",
            json={"min_glucose_mgdl": 40, "max_basal_rate_milliunits": 10000},
            cookies=cookies,
        )

        response = await client.get(
            "/api/settings/safety-limits",
            cookies=cookies,
        )
        assert response.json()["min_glucose_mgdl"] == 40
        assert response.json()["max_basal_rate_milliunits"] == 10000

    @pytest.mark.asyncio
    async def test_empty_body_returns_200(self, client):
        """Empty PATCH body should succeed without modifying anything."""
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        response = await client.patch(
            "/api/settings/safety-limits",
            json={},
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["min_glucose_mgdl"] == 20
        assert data["max_glucose_mgdl"] == 500


class TestGetSafetyLimitsDefaultsEndpoint:
    """Tests for GET /api/settings/safety-limits/defaults."""

    @pytest.mark.asyncio
    async def test_returns_defaults_without_auth(self, client):
        response = await client.get("/api/settings/safety-limits/defaults")
        assert response.status_code == 200
        data = response.json()
        assert data["min_glucose_mgdl"] == 20
        assert data["max_glucose_mgdl"] == 500
        assert data["max_basal_rate_milliunits"] == 15000
        assert data["max_bolus_dose_milliunits"] == 25000
