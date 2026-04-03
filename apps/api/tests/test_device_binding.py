"""Tests for enhanced device binding (Story 28.7).

Covers fingerprint storage, per-user limits, and conflict detection.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.core.auth import get_current_user
from src.database import get_db
from src.main import app


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


class TestDeviceRegistrationWithFingerprint:
    """Tests for fingerprint fields on registration."""

    @pytest.mark.asyncio
    async def test_register_with_fingerprint(self, client):
        """Registration accepts fingerprint, app_version, build_type."""
        mock_user = _mock_user()
        mock_db = AsyncMock()
        mock_device = MagicMock()
        mock_device.id = uuid.uuid4()
        mock_device.device_token = "tok-123"

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with (
                patch(
                    "src.routers.device_registration.register_device",
                    new_callable=AsyncMock,
                    return_value=mock_device,
                ) as mock_reg,
                patch(
                    "src.routers.device_registration.log_event",
                    new_callable=AsyncMock,
                ),
            ):
                response = await client.post(
                    "/api/v1/devices/register",
                    json={
                        "device_token": "tok-123",
                        "device_name": "Test Phone",
                        "device_fingerprint": "a" * 64,
                        "app_version": "1.0.0-debug",
                        "build_type": "debug",
                    },
                )
                assert response.status_code == 200
                call_kwargs = mock_reg.call_args.kwargs
                assert call_kwargs["device_fingerprint"] == "a" * 64
                assert call_kwargs["app_version"] == "1.0.0-debug"
                assert call_kwargs["build_type"] == "debug"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_register_without_fingerprint(self, client):
        """Registration still works without optional fingerprint fields."""
        mock_user = _mock_user()
        mock_db = AsyncMock()
        mock_device = MagicMock()
        mock_device.id = uuid.uuid4()
        mock_device.device_token = "tok-456"

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with (
                patch(
                    "src.routers.device_registration.register_device",
                    new_callable=AsyncMock,
                    return_value=mock_device,
                ) as mock_reg,
                patch(
                    "src.routers.device_registration.log_event",
                    new_callable=AsyncMock,
                ),
            ):
                response = await client.post(
                    "/api/v1/devices/register",
                    json={
                        "device_token": "tok-456",
                        "device_name": "Test Phone",
                    },
                )
                assert response.status_code == 200
                call_kwargs = mock_reg.call_args.kwargs
                assert call_kwargs["device_fingerprint"] is None
        finally:
            app.dependency_overrides.clear()


class TestDeviceConflictDetection:
    """Tests for fingerprint conflict and per-user limits at the service level."""

    @pytest.mark.asyncio
    async def test_fingerprint_conflict_returns_409(self, client):
        """Registration with conflicting fingerprint returns 409."""
        mock_user = _mock_user()
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with patch(
                "src.routers.device_registration.register_device",
                new_callable=AsyncMock,
                side_effect=ValueError(
                    "Device fingerprint is already registered to another user"
                ),
            ):
                response = await client.post(
                    "/api/v1/devices/register",
                    json={
                        "device_token": "tok-789",
                        "device_name": "Stolen Phone",
                        "device_fingerprint": "b" * 64,
                    },
                )
                assert response.status_code == 409
                assert "fingerprint" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_device_limit_exceeded_returns_409(self, client):
        """Exceeding per-user device limit returns 409."""
        mock_user = _mock_user()
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with patch(
                "src.routers.device_registration.register_device",
                new_callable=AsyncMock,
                side_effect=ValueError("Maximum of 10 devices per user reached"),
            ):
                response = await client.post(
                    "/api/v1/devices/register",
                    json={
                        "device_token": "tok-limit",
                        "device_name": "Too Many Phones",
                    },
                )
                assert response.status_code == 409
                assert "maximum" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()


class TestDeviceTokenTakeover:
    """Tests for cross-user device token hijacking prevention."""

    @pytest.mark.asyncio
    async def test_cross_user_token_reuse_returns_409(self, client):
        """Registering another user's device_token returns 409."""
        mock_user = _mock_user()
        mock_db = AsyncMock()

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with patch(
                "src.routers.device_registration.register_device",
                new_callable=AsyncMock,
                side_effect=ValueError(
                    "Device token is already registered to another user"
                ),
            ):
                response = await client.post(
                    "/api/v1/devices/register",
                    json={
                        "device_token": "stolen-token-123",
                        "device_name": "Attacker Phone",
                    },
                )
                assert response.status_code == 409
                assert "another user" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()


class TestDeviceListEndpoint:
    """Tests for GET /api/v1/devices."""

    @pytest.mark.asyncio
    async def test_list_devices_success(self, client):
        """List devices returns user's registered devices."""
        mock_user = _mock_user()
        mock_db = AsyncMock()

        now = datetime.now(UTC)
        device1 = MagicMock()
        device1.id = uuid.uuid4()
        device1.device_name = "Phone 1"
        device1.platform = "android"
        device1.app_version = "1.0.0"
        device1.build_type = "release"
        device1.last_seen_at = now

        app.dependency_overrides[get_current_user] = lambda: mock_user
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with patch(
                "src.routers.device_registration.get_devices_for_user",
                new_callable=AsyncMock,
                return_value=[device1],
            ):
                response = await client.get("/api/v1/devices")
                assert response.status_code == 200
                data = response.json()
                assert len(data["devices"]) == 1
                assert data["devices"][0]["device_name"] == "Phone 1"
                assert data["devices"][0]["app_version"] == "1.0.0"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_list_devices_requires_auth(self, client):
        """List devices without auth returns 401."""
        response = await client.get("/api/v1/devices")
        assert response.status_code == 401
