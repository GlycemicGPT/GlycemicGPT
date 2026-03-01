"""Tests for API key management (Story 28.7).

Covers create, list, revoke, scope validation, and auth via X-API-Key header.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.core.auth import get_current_user
from src.database import get_db
from src.main import app
from src.services.api_key_service import _hash_key


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


def _mock_user(user_id=None):
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = "test@example.com"
    user.role = MagicMock()
    user.role.value = "diabetic"
    user.is_active = True
    return user


class TestCreateApiKey:
    """Tests for POST /api/v1/api-keys."""

    @pytest.mark.asyncio
    async def test_create_key_success(self, client):
        """Creating an API key returns 201 with raw key."""
        mock_user = _mock_user()
        mock_db = AsyncMock()
        test_raw_key = f"ggpt_{secrets.token_urlsafe(32)}"
        mock_key = MagicMock()
        mock_key.id = uuid.uuid4()
        mock_key.prefix = test_raw_key[:12]
        mock_key.name = "Test Key"
        mock_key.scopes = "read:glucose"

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with (
                patch(
                    "src.routers.api_keys.create_api_key",
                    new_callable=AsyncMock,
                    return_value=(mock_key, test_raw_key),
                ),
                patch(
                    "src.routers.api_keys.log_event",
                    new_callable=AsyncMock,
                ),
            ):
                response = await client.post(
                    "/api/v1/api-keys",
                    json={
                        "name": "Test Key",
                        "scopes": ["read:glucose"],
                    },
                )
                assert response.status_code == 201
                data = response.json()
                assert data["raw_key"] == test_raw_key
                assert data["prefix"] == mock_key.prefix
                assert data["scopes"] == ["read:glucose"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_create_key_invalid_scopes(self, client):
        """Invalid scopes returns 400."""
        mock_user = _mock_user()
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with patch(
                "src.routers.api_keys.create_api_key",
                new_callable=AsyncMock,
                side_effect=ValueError("Invalid scopes: admin:all"),
            ):
                response = await client.post(
                    "/api/v1/api-keys",
                    json={
                        "name": "Bad Key",
                        "scopes": ["admin:all"],
                    },
                )
                assert response.status_code == 400
                assert "invalid scopes" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_create_key_requires_auth(self, client):
        """Creating an API key without auth returns 401."""
        response = await client.post(
            "/api/v1/api-keys",
            json={"name": "No Auth", "scopes": ["read:glucose"]},
        )
        assert response.status_code == 401


class TestListApiKeys:
    """Tests for GET /api/v1/api-keys."""

    @pytest.mark.asyncio
    async def test_list_keys_success(self, client):
        """List returns keys without raw key or hash."""
        mock_user = _mock_user()
        mock_db = AsyncMock()

        now = datetime.now(UTC)
        test_prefix = f"ggpt_{secrets.token_urlsafe(5)}"[:12]
        mock_key = MagicMock()
        mock_key.id = uuid.uuid4()
        mock_key.prefix = test_prefix
        mock_key.name = "My Key"
        mock_key.scopes = "read:glucose,read:pump"
        mock_key.is_active = True
        mock_key.last_used_at = now
        mock_key.expires_at = None
        mock_key.created_at = now

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with patch(
                "src.routers.api_keys.list_api_keys",
                new_callable=AsyncMock,
                return_value=[mock_key],
            ):
                response = await client.get("/api/v1/api-keys")
                assert response.status_code == 200
                data = response.json()
                assert len(data["keys"]) == 1
                key = data["keys"][0]
                assert key["prefix"] == test_prefix
                assert key["scopes"] == ["read:glucose", "read:pump"]
                assert "raw_key" not in key
                assert "key_hash" not in key
        finally:
            app.dependency_overrides.clear()


class TestRevokeApiKey:
    """Tests for DELETE /api/v1/api-keys/{key_id}."""

    @pytest.mark.asyncio
    async def test_revoke_key_success(self, client):
        """Revoking a valid key returns 204."""
        mock_user = _mock_user()
        mock_db = AsyncMock()
        key_id = uuid.uuid4()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with (
                patch(
                    "src.routers.api_keys.revoke_api_key",
                    new_callable=AsyncMock,
                    return_value=True,
                ),
                patch(
                    "src.routers.api_keys.log_event",
                    new_callable=AsyncMock,
                ),
            ):
                response = await client.delete(f"/api/v1/api-keys/{key_id}")
                assert response.status_code == 204
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_revoke_key_not_found(self, client):
        """Revoking a nonexistent key returns 404."""
        mock_user = _mock_user()
        mock_db = AsyncMock()
        key_id = uuid.uuid4()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with patch(
                "src.routers.api_keys.revoke_api_key",
                new_callable=AsyncMock,
                return_value=False,
            ):
                response = await client.delete(f"/api/v1/api-keys/{key_id}")
                assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()


class TestApiKeyServiceUnit:
    """Unit tests for API key service functions."""

    def test_hash_key_is_sha256(self):
        """Key hash uses SHA-256."""
        raw = f"ggpt_{secrets.token_urlsafe(16)}"
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert _hash_key(raw) == expected
        assert len(_hash_key(raw)) == 64

    @pytest.mark.asyncio
    async def test_validate_rejects_wrong_prefix(self):
        """Keys not starting with ggpt_ are rejected."""
        from src.services.api_key_service import validate_api_key

        mock_db = AsyncMock()
        result = await validate_api_key(mock_db, "badprefix_12345")
        assert result is None


class TestApiKeyExpiry:
    """Tests for expired API key behavior."""

    @pytest.mark.asyncio
    async def test_expired_key_returns_none(self):
        """Expired API keys are rejected during validation."""
        from src.services.api_key_service import _hash_key, validate_api_key

        raw_key = f"ggpt_{secrets.token_urlsafe(32)}"
        mock_key = MagicMock()
        mock_key.prefix = raw_key[:12]
        mock_key.key_hash = _hash_key(raw_key)
        mock_key.is_active = True
        mock_key.expires_at = datetime.now(UTC) - timedelta(hours=1)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_key

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        result = await validate_api_key(mock_db, raw_key)
        assert result is None
