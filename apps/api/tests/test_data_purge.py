"""Story 9.4: Tests for data purge capability.

Tests cover:
- Schema validation (confirmation_text, response)
- Service layer (purge_all_user_data)
- API endpoint (POST /api/settings/data-retention/purge)
- Structural auth verification
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from src.config import settings
from src.schemas.data_purge import DataPurgeRequest, DataPurgeResponse


def unique_email(prefix: str = "purge") -> str:
    """Generate a unique email for testing."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def register_and_login(client) -> str:
    """Register a new user and return the session cookie value."""
    email = unique_email()
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


# ── Schema tests ──


class TestDataPurgeRequestSchema:
    """Tests for DataPurgeRequest schema validation."""

    def test_valid_confirmation(self):
        req = DataPurgeRequest(confirmation_text="DELETE")
        assert req.confirmation_text == "DELETE"

    def test_requires_confirmation_text(self):
        with pytest.raises(ValidationError):
            DataPurgeRequest()

    def test_accepts_any_string(self):
        """Schema accepts any string; endpoint validates the exact value."""
        req = DataPurgeRequest(confirmation_text="wrong")
        assert req.confirmation_text == "wrong"


class TestDataPurgeResponseSchema:
    """Tests for DataPurgeResponse schema."""

    def test_valid_response(self):
        resp = DataPurgeResponse(
            success=True,
            deleted_records={"glucose_readings": 100, "alerts": 5},
            total_deleted=105,
            message="Successfully purged 105 records",
        )
        assert resp.success is True
        assert resp.total_deleted == 105


# ── Service tests ──


class TestPurgeAllUserData:
    """Tests for purge_all_user_data service function."""

    @pytest.mark.asyncio
    async def test_deletes_all_categories(self):
        """Verify all 9 data categories are deleted."""
        from src.services.data_purge import purge_all_user_data

        user_id = uuid.uuid4()
        db = AsyncMock()

        mock_result = MagicMock()
        mock_result.rowcount = 10
        db.execute.return_value = mock_result

        result = await purge_all_user_data(user_id, db)

        # 10 delete calls (glucose, pump, brief, meal, correction,
        # suggestion, safety, escalation, alert, chat_messages)
        assert db.execute.call_count == 10
        assert db.commit.call_count == 1

        # All 10 categories should be in result
        assert len(result) == 10
        assert result["glucose_readings"] == 10
        assert result["pump_events"] == 10
        assert result["daily_briefs"] == 10
        assert result["meal_analyses"] == 10
        assert result["correction_analyses"] == 10
        assert result["suggestion_responses"] == 10
        assert result["safety_logs"] == 10
        assert result["escalation_events"] == 10
        assert result["alerts"] == 10

    @pytest.mark.asyncio
    async def test_returns_zero_counts_when_empty(self):
        """Purge on empty data returns zero counts."""
        from src.services.data_purge import purge_all_user_data

        user_id = uuid.uuid4()
        db = AsyncMock()

        mock_result = MagicMock()
        mock_result.rowcount = 0
        db.execute.return_value = mock_result

        result = await purge_all_user_data(user_id, db)

        assert all(v == 0 for v in result.values())
        assert db.commit.call_count == 1


# ── Endpoint tests ──


class TestPurgeEndpoint:
    """Tests for POST /api/settings/data-retention/purge."""

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        response = await client.post(
            "/api/settings/data-retention/purge",
            json={"confirmation_text": "DELETE"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_confirmation_returns_422(self, client):
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        response = await client.post(
            "/api/settings/data-retention/purge",
            json={"confirmation_text": "delete"},
            cookies=cookies,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_confirmation_returns_422(self, client):
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        response = await client.post(
            "/api/settings/data-retention/purge",
            json={"confirmation_text": ""},
            cookies=cookies,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_body_returns_422(self, client):
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        response = await client.post(
            "/api/settings/data-retention/purge",
            json={},
            cookies=cookies,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_successful_purge(self, client):
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        # Purge should succeed (even if user has no data)
        response = await client.post(
            "/api/settings/data-retention/purge",
            json={"confirmation_text": "DELETE"},
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_deleted"] >= 0
        assert "deleted_records" in data
        assert "message" in data

    @pytest.mark.asyncio
    async def test_purge_preserves_account_settings(self, client):
        """After purge, user can still access their settings."""
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        # Purge all data
        response = await client.post(
            "/api/settings/data-retention/purge",
            json={"confirmation_text": "DELETE"},
            cookies=cookies,
        )
        assert response.status_code == 200

        # Settings endpoints should still work
        response = await client.get(
            "/api/settings/data-retention",
            cookies=cookies,
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_purge_idempotent(self, client):
        """Purging twice should succeed both times."""
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        r1 = await client.post(
            "/api/settings/data-retention/purge",
            json={"confirmation_text": "DELETE"},
            cookies=cookies,
        )
        assert r1.status_code == 200

        r2 = await client.post(
            "/api/settings/data-retention/purge",
            json={"confirmation_text": "DELETE"},
            cookies=cookies,
        )
        assert r2.status_code == 200
        assert r2.json()["total_deleted"] == 0


# ── Structural tests ──


class TestPurgeEndpointStructure:
    """Verify the purge endpoint has correct auth dependencies."""

    def test_purge_endpoint_has_role_checker(self):
        """POST /api/settings/data-retention/purge must have RoleChecker."""
        from src.core.auth import RoleChecker
        from src.routers.settings import router

        purge_routes = [
            r
            for r in router.routes
            if hasattr(r, "path")
            and r.path == "/api/settings/data-retention/purge"
            and hasattr(r, "methods")
            and "POST" in r.methods
        ]
        assert len(purge_routes) == 1

        route = purge_routes[0]
        dep_classes = [type(d.dependency) for d in route.dependencies]
        assert RoleChecker in dep_classes
