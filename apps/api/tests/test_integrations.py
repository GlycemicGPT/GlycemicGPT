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

    def test_naive_datetimes_rejected_with_422(self):
        from datetime import datetime

        import pytest
        from fastapi import HTTPException

        from src.routers.integrations import _validate_date_range

        start = datetime(2026, 3, 1)
        end = datetime(2026, 3, 2)
        with pytest.raises(HTTPException) as exc_info:
            _validate_date_range(start, end)
        assert exc_info.value.status_code == 422
        assert "timezone offset" in str(exc_info.value.detail)

    def test_exactly_31_days_is_valid(self):
        from datetime import UTC, datetime

        from src.routers.integrations import _validate_date_range

        start = datetime(2026, 3, 1, tzinfo=UTC)
        end = datetime(2026, 4, 1, tzinfo=UTC)
        result = _validate_date_range(start, end)
        assert result == (start, end)


# ============================================================================
# Dexcom + Tandem region/country expansion
# ============================================================================


async def _login(client: AsyncClient, email: str, password: str) -> str:
    await client.post("/api/auth/register", json={"email": email, "password": password})
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    cookie = resp.cookies.get(settings.jwt_cookie_name)
    assert cookie
    return cookie


class TestDexcomRegionField:
    """Dexcom credentials accept ``region`` and reject unsupported values."""

    @patch("src.routers.integrations.validate_dexcom_credentials")
    async def test_default_region_is_us(self, mock_validate):
        """Omitting region falls back to US (matches existing pydexcom default)."""
        mock_validate.return_value = (True, None)
        email = unique_email("dex_region_default")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _login(client, email, "SecurePass123")
            resp = await client.post(
                "/api/integrations/dexcom",
                json={"username": "dex@x.com", "password": "p"},
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 201
        # validate_dexcom_credentials should have been called with region="US"
        args = mock_validate.call_args
        assert args.args[2] == "US" or args.kwargs.get("region") == "US"

    @patch("src.routers.integrations.validate_dexcom_credentials")
    async def test_accepts_ous_region(self, mock_validate):
        """OUS (Outside US) region is accepted and forwarded to validator."""
        mock_validate.return_value = (True, None)
        email = unique_email("dex_region_ous")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _login(client, email, "SecurePass123")
            resp = await client.post(
                "/api/integrations/dexcom",
                json={
                    "username": "dex_ous@x.com",
                    "password": "p",
                    "region": "OUS",
                },
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 201, resp.text
        args = mock_validate.call_args
        assert args.args[2] == "OUS" or args.kwargs.get("region") == "OUS"

    @patch("src.routers.integrations.validate_dexcom_credentials")
    async def test_accepts_jp_region(self, mock_validate):
        """Japan/APAC region is accepted."""
        mock_validate.return_value = (True, None)
        email = unique_email("dex_region_jp")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _login(client, email, "SecurePass123")
            resp = await client.post(
                "/api/integrations/dexcom",
                json={
                    "username": "dex_jp@x.com",
                    "password": "p",
                    "region": "JP",
                },
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 201

    async def test_rejects_unknown_region(self):
        """Garbage region values are rejected at the schema layer (422)."""
        email = unique_email("dex_region_bad")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _login(client, email, "SecurePass123")
            resp = await client.post(
                "/api/integrations/dexcom",
                json={
                    "username": "dex@x.com",
                    "password": "p",
                    "region": "MARS",
                },
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 422


class TestTandemCountryField:
    """Tandem credentials accept ISO-3166 country codes."""

    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_default_country_is_us(self, mock_validate):
        mock_validate.return_value = (True, None)
        email = unique_email("tan_country_default")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _login(client, email, "SecurePass123")
            resp = await client.post(
                "/api/integrations/tandem",
                json={"username": "t@x.com", "password": "p"},
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 201

    @pytest.mark.parametrize(
        "country", ["GB", "DE", "CA", "AU", "NZ", "IL", "ZA", "MX"]
    )
    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_accepts_supported_country_codes(self, mock_validate, country: str):
        mock_validate.return_value = (True, None)
        email = unique_email(f"tan_country_{country.lower()}")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _login(client, email, "SecurePass123")
            resp = await client.post(
                "/api/integrations/tandem",
                json={
                    "username": f"t_{country}@x.com",
                    "password": "p",
                    "country": country,
                },
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 201, resp.text

    @pytest.mark.parametrize("country", ["JP", "BR", "KR", "EU", "us", "USA", ""])
    async def test_rejects_unsupported_country_codes(self, country: str):
        """Tandem-unsupported countries, legacy 'EU', lowercase, and
        non-alpha-2 codes are all rejected at the schema layer."""
        email = unique_email(f"tan_country_bad_{uuid.uuid4().hex[:4]}")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _login(client, email, "SecurePass123")
            resp = await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "t@x.com",
                    "password": "p",
                    "country": country,
                },
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 422


class TestTandemCloudUploadRoutesGone:
    """The Tandem cloud-upload endpoints were removed in PR1c. Verify they
    no longer exist as a regression guard -- a future inadvertent re-add
    would silently re-enable a feature we deliberately deprecated.

    Each test authenticates first so a 401 from an auth gate around the
    re-added route surfaces as a clear test failure (distinct from "route
    is gone"), rather than masquerading as a 404 from a missing route.
    """

    async def test_status_endpoint_404(self):
        email = unique_email("upload_gone_status")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _login(client, email, "SecurePass123")
            resp = await client.get(
                "/api/integrations/tandem/cloud-upload/status",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 404, resp.text

    async def test_settings_endpoint_404(self):
        email = unique_email("upload_gone_settings")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _login(client, email, "SecurePass123")
            resp = await client.put(
                "/api/integrations/tandem/cloud-upload/settings",
                json={"enabled": False, "interval_minutes": 15},
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 404, resp.text

    async def test_trigger_endpoint_404(self):
        email = unique_email("upload_gone_trigger")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _login(client, email, "SecurePass123")
            resp = await client.post(
                "/api/integrations/tandem/cloud-upload/trigger",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 404, resp.text

    async def test_reset_endpoint_404(self):
        email = unique_email("upload_gone_reset")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _login(client, email, "SecurePass123")
            resp = await client.post(
                "/api/integrations/tandem/cloud-upload/reset",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 404, resp.text


class TestPumpPushAcceptsButIgnoresRawEvents:
    """``/api/integrations/pump/push`` keeps accepting ``raw_events`` and
    ``pump_info`` from older mobile clients (back-compat), but no longer
    persists them. Response reports zero raw_accepted/raw_duplicates and
    sets an IETF ``Deprecation`` header (RFC 9745, Structured Field date
    item: ``@<unix-timestamp>``) plus a ``Sunset`` header (RFC 8594) so
    newer clients can detect the back-compat path at the protocol level."""

    async def test_push_accepts_legacy_raw_events_field(self):
        # Use bearer-token mobile auth like the rest of pump/push tests
        # (cookie auth would trip CSRF on this state-changing endpoint).
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import inspect, text

        from src.database import get_engine

        # Take a "before" snapshot of the legacy tables. After the call we
        # re-check: if migration 058 has run (prod-shape DB), the tables
        # are absent; if the test DB was built from model metadata only
        # (it doesn't run migrations), the tables exist but the row counts
        # must be unchanged. This double-pronged assertion catches a future
        # silent re-add of either the persistence code OR the model classes.
        async with get_engine().connect() as conn:
            tables_before = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )
        legacy_tables_present = "pump_raw_events" in tables_before or (
            "pump_hardware_info" in tables_before
        )

        async def _row_counts() -> dict[str, int | None]:
            counts: dict[str, int | None] = {}
            async with get_engine().connect() as conn:
                for tbl in ("pump_raw_events", "pump_hardware_info"):
                    if tbl in tables_before:
                        res = await conn.execute(
                            text(f"SELECT COUNT(*) FROM {tbl}")  # noqa: S608
                        )
                        counts[tbl] = res.scalar()
                    else:
                        counts[tbl] = None
            return counts

        counts_before = await _row_counts()

        email = unique_email("pump_push_raw")
        # 1 hour ago so the event_timestamp validator (rejects >5 min future)
        # accepts it regardless of when the test runs.
        event_ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": "TestPass1"},
            )
            login = await client.post(
                "/api/auth/mobile/login",
                json={"email": email, "password": "TestPass1"},
            )
            token = login.json()["access_token"]
            resp = await client.post(
                "/api/integrations/pump/push",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "events": [
                        {
                            "event_type": "bolus",
                            "event_timestamp": event_ts,
                            "units": 2.0,
                            "is_automated": False,
                        }
                    ],
                    "raw_events": [
                        {
                            "sequence_number": 1,
                            "raw_bytes_b64": "AQID",
                            "event_type_id": 280,
                            "pump_time_seconds": 1000,
                        }
                    ],
                    "pump_info": {
                        "serial_number": 12345678,
                        "model_number": 99,
                        "part_number": 11111,
                        "pump_rev": "3.0",
                        "arm_sw_ver": 50000,
                        "msp_sw_ver": 50000,
                        "config_a_bits": 0,
                        "config_b_bits": 0,
                        "pcba_sn": 99999,
                        "pcba_rev": "A",
                        "pump_features": {},
                    },
                    "source": "mobile",
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # The structured event was stored...
        assert body["accepted"] == 1
        # ...but the deprecated raw_events / pump_info were silently ignored.
        assert body["raw_accepted"] == 0
        assert body["raw_duplicates"] == 0
        # Deprecation header is set when legacy fields are present.
        # RFC 9745 syntax: ``@<unix-timestamp>``. Value tracks the date
        # PR1c removed the consuming feature.
        deprecation = resp.headers.get("Deprecation")
        assert deprecation is not None and deprecation.startswith("@"), (
            f"expected RFC 9745 Deprecation header (@<ts>), got: {deprecation!r}"
        )
        # Numeric body must parse as int (sanity check on the timestamp).
        assert deprecation[1:].isdigit(), (
            f"Deprecation timestamp not numeric: {deprecation!r}"
        )
        assert "Sunset" in resp.headers
        # Sanity: the structured pump_events row WAS written (so we know the
        # 200 isn't coming from some silent short-circuit).
        async with get_engine().connect() as conn:
            count_result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM pump_events "
                    "WHERE event_type = 'bolus' AND units = 2.0"
                )
            )
            count = count_result.scalar()
        assert count is not None and count >= 1
        # Crucially: the deprecated raw_events / pump_info were NOT
        # written. If migration 058 has run (prod-shape DB), the tables
        # are gone and we have nothing to count. If the legacy tables
        # still exist (e.g. metadata-built test DB), row counts must
        # match the snapshot taken before the request.
        if legacy_tables_present:
            counts_after = await _row_counts()
            assert counts_after == counts_before, (
                "pump_raw_events / pump_hardware_info row counts changed -- "
                "the legacy upload persistence appears to have been "
                "re-introduced"
            )

    async def test_push_with_drifted_legacy_shape_does_not_422(self):
        """The legacy ``raw_events`` / ``pump_info`` fields are typed loosely
        so a future mobile drift (extra fields, type tweaks) does NOT take
        down the real ``events`` batch with a 422. This is the regression
        guard for CodeRabbit's PR review finding."""
        from datetime import UTC, datetime, timedelta

        email = unique_email("pump_push_drift")
        event_ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": "TestPass1"},
            )
            login = await client.post(
                "/api/auth/mobile/login",
                json={"email": email, "password": "TestPass1"},
            )
            token = login.json()["access_token"]
            resp = await client.post(
                "/api/integrations/pump/push",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "events": [
                        {
                            "event_type": "bolus",
                            "event_timestamp": event_ts,
                            "units": 3.0,
                            "is_automated": False,
                        }
                    ],
                    # raw_events with a *drifted* shape: missing fields,
                    # extra fields, wrong types. None of this should matter.
                    "raw_events": [
                        {"future_field": "abc", "another_new_field": 42},
                        {"raw_bytes_b64": True},  # wrong type
                        "even a bare string",  # not even a dict
                    ],
                    # pump_info as a totally different shape than the
                    # historical one. Also fine.
                    "pump_info": {
                        "manufacturer": "Tandem",
                        "version": [3, 5, 0],
                        "extra": {"deep": {"nested": "value"}},
                    },
                    "source": "mobile",
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["accepted"] == 1
        # Deprecation header is still set because the legacy fields are
        # populated (regardless of their shape).
        assert resp.headers.get("Deprecation", "").startswith("@")

    async def test_push_without_legacy_fields_no_deprecation_header(self):
        """Newer mobile builds that omit ``raw_events`` / ``pump_info``
        should NOT get the deprecation header -- the header is the signal
        that *this* particular request was using the legacy fields."""
        from datetime import UTC, datetime, timedelta

        email = unique_email("pump_push_clean")
        event_ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": "TestPass1"},
            )
            login = await client.post(
                "/api/auth/mobile/login",
                json={"email": email, "password": "TestPass1"},
            )
            token = login.json()["access_token"]
            resp = await client.post(
                "/api/integrations/pump/push",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "events": [
                        {
                            "event_type": "bolus",
                            "event_timestamp": event_ts,
                            "units": 1.0,
                            "is_automated": False,
                        }
                    ],
                    "source": "mobile",
                },
            )
        assert resp.status_code == 200, resp.text
        assert "Deprecation" not in resp.headers
        assert "Sunset" not in resp.headers


class TestIntegrationListSurfacesRegion:
    """``GET /api/integrations`` exposes the stored region so the frontend can
    pre-populate the pickers and avoid accidental overwrites on save."""

    @patch("src.routers.integrations.validate_dexcom_credentials")
    async def test_dexcom_region_round_trips(self, mock_validate):
        mock_validate.return_value = (True, None)
        email = unique_email("dex_region_roundtrip")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _login(client, email, "SecurePass123")
            connect = await client.post(
                "/api/integrations/dexcom",
                json={
                    "username": "dex@x.com",
                    "password": "p",
                    "region": "OUS",
                },
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert connect.status_code == 201
            assert connect.json()["integration"]["region"] == "OUS"

            listing = await client.get(
                "/api/integrations",
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert listing.status_code == 200
            dexcom_row = next(
                i
                for i in listing.json()["integrations"]
                if i["integration_type"] == "dexcom"
            )
            assert dexcom_row["region"] == "OUS"

    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_tandem_country_round_trips(self, mock_validate):
        mock_validate.return_value = (True, None)
        email = unique_email("tan_country_roundtrip")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _login(client, email, "SecurePass123")
            connect = await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "t@x.com",
                    "password": "p",
                    "country": "GB",
                },
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert connect.status_code == 201
            assert connect.json()["integration"]["region"] == "GB"

            listing = await client.get(
                "/api/integrations",
                cookies={settings.jwt_cookie_name: cookie},
            )
            tandem_row = next(
                i
                for i in listing.json()["integrations"]
                if i["integration_type"] == "tandem"
            )
            assert tandem_row["region"] == "GB"
