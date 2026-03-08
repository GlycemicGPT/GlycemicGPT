"""Story 3.1 & 3.3: Tests for integration credentials."""

import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.main import app


def unique_email(prefix: str = "test") -> str:
    """Generate a unique email for testing."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


class TestDexcomIntegration:
    """Tests for Dexcom integration endpoints."""

    async def test_list_integrations_empty(self):
        """Test listing integrations when none are configured."""
        email = unique_email("list_empty")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # List integrations
            response = await client.get(
                "/api/integrations",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["integrations"] == []

    async def test_connect_dexcom_requires_auth(self):
        """Test that connecting Dexcom requires authentication."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/integrations/dexcom",
                json={
                    "username": "test@example.com",
                    "password": "password123",
                },
            )

        assert response.status_code == 401

    @patch("src.routers.integrations.validate_dexcom_credentials")
    async def test_connect_dexcom_with_valid_credentials(self, mock_validate):
        """Test connecting Dexcom with valid credentials."""
        mock_validate.return_value = (True, None)

        email = unique_email("dexcom_valid")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Connect Dexcom
            response = await client.post(
                "/api/integrations/dexcom",
                json={
                    "username": "dexcom@example.com",
                    "password": "dexcom_password",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["message"] == "Dexcom connected successfully"
        assert data["integration"]["integration_type"] == "dexcom"
        assert data["integration"]["status"] == "connected"

    @patch("src.routers.integrations.validate_dexcom_credentials")
    async def test_connect_dexcom_with_invalid_credentials(self, mock_validate):
        """Test connecting Dexcom with invalid credentials."""
        mock_validate.return_value = (
            False,
            "Invalid Dexcom credentials. Please check your email and password.",
        )

        email = unique_email("dexcom_invalid")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Try to connect Dexcom with invalid credentials
            response = await client.post(
                "/api/integrations/dexcom",
                json={
                    "username": "bad@example.com",
                    "password": "wrong_password",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 400
        assert "Invalid Dexcom credentials" in response.json()["detail"]

    async def test_get_dexcom_status_not_found(self):
        """Test getting Dexcom status when not configured."""
        email = unique_email("dexcom_notfound")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Get Dexcom status
            response = await client.get(
                "/api/integrations/dexcom/status",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


# ============================================================================
# Story 3.3: Tandem t:connect Integration Tests
# ============================================================================


class TestTandemIntegration:
    """Tests for Tandem t:connect integration endpoints."""

    async def test_connect_tandem_requires_auth(self):
        """Test that connecting Tandem requires authentication."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "test@example.com",
                    "password": "password123",
                },
            )

        assert response.status_code == 401

    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_connect_tandem_with_valid_credentials(self, mock_validate):
        """Test connecting Tandem with valid credentials."""
        mock_validate.return_value = (True, None)

        email = unique_email("tandem_valid")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Connect Tandem
            response = await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "tandem@example.com",
                    "password": "tandem_password",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["message"] == "Tandem t:connect connected successfully"
        assert data["integration"]["integration_type"] == "tandem"
        assert data["integration"]["status"] == "connected"

    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_connect_tandem_with_invalid_credentials(self, mock_validate):
        """Test connecting Tandem with invalid credentials."""
        mock_validate.return_value = (
            False,
            "Invalid Tandem credentials. Please check your email and password.",
        )

        email = unique_email("tandem_invalid")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Try to connect Tandem with invalid credentials
            response = await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "bad@example.com",
                    "password": "wrong_password",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 400
        assert "Invalid Tandem credentials" in response.json()["detail"]

    async def test_get_tandem_status_not_found(self):
        """Test getting Tandem status when not configured."""
        email = unique_email("tandem_notfound")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Get Tandem status
            response = await client.get(
                "/api/integrations/tandem/status",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_disconnect_tandem(self, mock_validate):
        """Test disconnecting Tandem integration."""
        mock_validate.return_value = (True, None)

        email = unique_email("tandem_disconnect")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Connect Tandem first
            await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "tandem@example.com",
                    "password": "tandem_password",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Disconnect Tandem
            response = await client.delete(
                "/api/integrations/tandem",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert "disconnected" in data["message"].lower()

    async def test_disconnect_tandem_not_found(self):
        """Test disconnecting Tandem when not configured."""
        email = unique_email("tandem_disconnect_notfound")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Try to disconnect Tandem (not configured)
            response = await client.delete(
                "/api/integrations/tandem",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 404

    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_tandem_shows_in_integrations_list(self, mock_validate):
        """Test that connected Tandem shows in integrations list."""
        mock_validate.return_value = (True, None)

        email = unique_email("tandem_list")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Connect Tandem
            await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "tandem@example.com",
                    "password": "tandem_password",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # List integrations
            response = await client.get(
                "/api/integrations",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["integrations"]) == 1
        assert data["integrations"][0]["integration_type"] == "tandem"
        assert data["integrations"][0]["status"] == "connected"


class TestEncryption:
    """Tests for credential encryption."""

    def test_encrypt_decrypt_roundtrip(self):
        """Test that encryption and decryption work correctly."""
        from src.core.encryption import decrypt_credential, encrypt_credential

        original = "my_secret_password_123!"
        encrypted = encrypt_credential(original)

        # Encrypted should be different from original
        assert encrypted != original

        # Decrypted should match original
        decrypted = decrypt_credential(encrypted)
        assert decrypted == original

    def test_encryption_produces_different_outputs(self):
        """Test that same input produces different encrypted outputs (due to IV)."""
        from src.core.encryption import encrypt_credential

        original = "same_password"
        encrypted1 = encrypt_credential(original)
        encrypted2 = encrypt_credential(original)

        # Each encryption should produce different output (different IV)
        assert encrypted1 != encrypted2


# ── _validate_date_range tests ──


class TestValidateDateRange:
    """Tests for the _validate_date_range helper in integrations router."""

    def test_both_none_returns_none(self):
        from src.routers.integrations import _validate_date_range

        assert _validate_date_range(None, None) is None

    def test_only_start_raises_422(self):
        from datetime import UTC, datetime

        from fastapi import HTTPException

        from src.routers.integrations import _validate_date_range

        with pytest.raises(HTTPException) as exc_info:
            _validate_date_range(datetime(2026, 3, 1, tzinfo=UTC), None)
        assert exc_info.value.status_code == 422
        assert "together" in exc_info.value.detail

    def test_only_end_raises_422(self):
        from datetime import UTC, datetime

        from fastapi import HTTPException

        from src.routers.integrations import _validate_date_range

        with pytest.raises(HTTPException) as exc_info:
            _validate_date_range(None, datetime(2026, 3, 1, tzinfo=UTC))
        assert exc_info.value.status_code == 422

    def test_end_before_start_raises_422(self):
        from datetime import UTC, datetime

        from fastapi import HTTPException

        from src.routers.integrations import _validate_date_range

        with pytest.raises(HTTPException) as exc_info:
            _validate_date_range(
                datetime(2026, 3, 5, tzinfo=UTC),
                datetime(2026, 3, 1, tzinfo=UTC),
            )
        assert exc_info.value.status_code == 422
        assert "strictly after" in exc_info.value.detail

    def test_start_equals_end_raises_422(self):
        from datetime import UTC, datetime

        from fastapi import HTTPException

        from src.routers.integrations import _validate_date_range

        ts = datetime(2026, 3, 1, tzinfo=UTC)
        with pytest.raises(HTTPException) as exc_info:
            _validate_date_range(ts, ts)
        assert exc_info.value.status_code == 422

    def test_exceeds_max_days_raises_422(self):
        from datetime import UTC, datetime

        from fastapi import HTTPException

        from src.routers.integrations import _validate_date_range

        with pytest.raises(HTTPException) as exc_info:
            _validate_date_range(
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 3, 1, tzinfo=UTC),
            )
        assert exc_info.value.status_code == 422
        assert "31 days" in exc_info.value.detail

    def test_valid_range_returns_tuple(self):
        from datetime import UTC, datetime

        from src.routers.integrations import _validate_date_range

        start = datetime(2026, 3, 1, tzinfo=UTC)
        end = datetime(2026, 3, 2, tzinfo=UTC)
        result = _validate_date_range(start, end)
        assert result == (start, end)

    def test_naive_datetimes_get_utc(self):
        from datetime import UTC, datetime

        from src.routers.integrations import _validate_date_range

        start = datetime(2026, 3, 1)
        end = datetime(2026, 3, 2)
        result = _validate_date_range(start, end)
        assert result[0].tzinfo == UTC
        assert result[1].tzinfo == UTC

    def test_exactly_31_days_is_valid(self):
        from datetime import UTC, datetime

        from src.routers.integrations import _validate_date_range

        start = datetime(2026, 3, 1, tzinfo=UTC)
        end = datetime(2026, 4, 1, tzinfo=UTC)
        result = _validate_date_range(start, end)
        assert result == (start, end)
