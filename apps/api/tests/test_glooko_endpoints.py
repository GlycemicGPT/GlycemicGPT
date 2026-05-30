"""Tests for the Glooko (Omnipod Cloud Sync) connect/sync endpoints (Milestone D).

The Glooko web login (``glooko_login``) and the sync/import/availability
orchestrators are patched so these stay pure unit/HTTP tests against a real test
DB for the ``GlookoSyncState`` row. The patched orchestrators receive the SAME
state ORM object the endpoint loaded, so a patched failure can mutate
``state.status`` exactly as the real ``_mark_failure`` would -- letting us drive
the auth-vs-transient status mapping without real network.
"""

import uuid
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.config import settings
from src.core.encryption import decrypt_credential
from src.database import get_session_maker
from src.main import app
from src.models.glooko_sync_state import STATUS_DISCONNECTED, GlookoSyncState
from src.models.user import User
from src.services.integrations.glooko.auth import GlookoSession
from src.services.integrations.glooko.errors import (
    GlookoAuthError,
    GlookoNetworkError,
)
from src.services.integrations.glooko.sync import (
    GlookoAvailability,
    GlookoSyncResult,
    GlookoSyncRunError,
)

CONNECT = "/api/integrations/glooko"
STATUS = "/api/integrations/glooko/status"
SYNC = "/api/integrations/glooko/sync"
SETTINGS = "/api/integrations/glooko/sync/settings"
AVAILABILITY = "/api/integrations/glooko/sync/availability"
IMPORT = "/api/integrations/glooko/sync/import"

# A Glooko account password we assert never leaks into any response body.
GLOOKO_PASSWORD = "Sup3r-Secret-Glooko-Pw"
GLOOKO_EMAIL = "omnipod-user@example.com"


def _email() -> str:
    return f"glooko_{uuid.uuid4().hex[:8]}@example.com"


async def _login(client: AsyncClient) -> dict:
    email, pw = _email(), "SecurePass123"
    await client.post("/api/auth/register", json={"email": email, "password": pw})
    r = await client.post("/api/auth/login", json={"email": email, "password": pw})
    return {settings.jwt_cookie_name: r.cookies.get(settings.jwt_cookie_name)}


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True
    )


def _session(region: str = "US") -> GlookoSession:
    return GlookoSession(
        region=region,
        cookies={"_logbook-web_session": "test-cookie"},
        patient_slug="slug12345",
        patient_oid="a" * 24,
    )


async def _connect(client, cookies, *, region: str = "US", accept_risk: bool = True):
    """Connect Glooko with the live login patched to succeed. Returns the
    /glooko response so callers can assert on it."""
    body = {
        "email": GLOOKO_EMAIL,
        "password": GLOOKO_PASSWORD,
        "region": region,
        "accept_risk": accept_risk,
    }
    with patch(
        "src.routers.integrations.glooko_login",
        new=AsyncMock(return_value=_session(region)),
    ):
        return await client.post(CONNECT, json=body, cookies=cookies)


# --- connect + consent ---


async def test_connect_stores_state_records_consent_and_hides_credentials():
    async with _client() as client:
        cookies = await _login(client)
        r = await _connect(client, cookies)
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["connected"] is True
        assert data["status"] == "connected"
        assert data["enabled"] is True
        assert data["region"] == "US"
        # Consent is stamped at connect time.
        assert data["consent_acknowledged_at"] is not None
        # Credentials must never be echoed back anywhere in the response.
        assert GLOOKO_PASSWORD not in r.text
        assert GLOOKO_EMAIL not in r.text
        assert "password" not in data
        assert "encrypted_email" not in data


async def test_connect_encrypts_credentials_at_rest():
    """Stored credentials must be ciphertext, not plaintext -- a regression that
    skipped encryption would still pass the response-body checks, so assert at the
    DB layer that the columns are encrypted and decrypt back to the input."""
    app_email, pw = _email(), "SecurePass123"
    async with _client() as client:
        await client.post(
            "/api/auth/register", json={"email": app_email, "password": pw}
        )
        r = await client.post(
            "/api/auth/login", json={"email": app_email, "password": pw}
        )
        cookies = {settings.jwt_cookie_name: r.cookies.get(settings.jwt_cookie_name)}
        with patch(
            "src.routers.integrations.glooko_login",
            new=AsyncMock(return_value=_session()),
        ):
            cr = await client.post(
                CONNECT,
                json={
                    "email": GLOOKO_EMAIL,
                    "password": GLOOKO_PASSWORD,
                    "region": "US",
                    "accept_risk": True,
                },
                cookies=cookies,
            )
        assert cr.status_code == 201, cr.text

    session_maker = get_session_maker()
    async with session_maker() as s:
        user = (
            await s.execute(select(User).where(User.email == app_email))
        ).scalar_one()
        state = (
            await s.execute(
                select(GlookoSyncState).where(GlookoSyncState.user_id == user.id)
            )
        ).scalar_one()
        # Ciphertext at rest -- not the plaintext we submitted.
        assert state.encrypted_email != GLOOKO_EMAIL
        assert state.encrypted_password != GLOOKO_PASSWORD
        # ...but it round-trips back to the original.
        assert decrypt_credential(state.encrypted_email) == GLOOKO_EMAIL
        assert decrypt_credential(state.encrypted_password) == GLOOKO_PASSWORD
        # Consent stamped server-side at connect time.
        assert state.consent_acknowledged_at is not None


async def test_connect_requires_consent_acknowledgment_422():
    async with _client() as client:
        cookies = await _login(client)
        # accept_risk=false is rejected by the schema validator.
        r = await _connect(client, cookies, accept_risk=False)
        assert r.status_code == 422


async def test_connect_missing_accept_risk_field_422():
    async with _client() as client:
        cookies = await _login(client)
        r = await client.post(
            CONNECT,
            json={"email": GLOOKO_EMAIL, "password": GLOOKO_PASSWORD, "region": "US"},
            cookies=cookies,
        )
        assert r.status_code == 422


async def test_connect_invalid_region_422():
    async with _client() as client:
        cookies = await _login(client)
        r = await client.post(
            CONNECT,
            json={
                "email": GLOOKO_EMAIL,
                "password": GLOOKO_PASSWORD,
                "region": "JP",
                "accept_risk": True,
            },
            cookies=cookies,
        )
        assert r.status_code == 422


async def test_connect_bad_credentials_400():
    async with _client() as client:
        cookies = await _login(client)
        with patch(
            "src.routers.integrations.glooko_login",
            new=AsyncMock(side_effect=GlookoAuthError("rejected")),
        ):
            r = await client.post(
                CONNECT,
                json={
                    "email": GLOOKO_EMAIL,
                    "password": GLOOKO_PASSWORD,
                    "region": "US",
                    "accept_risk": True,
                },
                cookies=cookies,
            )
        assert r.status_code == 400
        # Even on failure, the submitted password must not echo back.
        assert GLOOKO_PASSWORD not in r.text


async def test_connect_glooko_unreachable_503():
    async with _client() as client:
        cookies = await _login(client)
        with patch(
            "src.routers.integrations.glooko_login",
            new=AsyncMock(side_effect=GlookoNetworkError("timeout")),
        ):
            r = await client.post(
                CONNECT,
                json={
                    "email": GLOOKO_EMAIL,
                    "password": GLOOKO_PASSWORD,
                    "region": "US",
                    "accept_risk": True,
                },
                cookies=cookies,
            )
        assert r.status_code == 503


# --- status ---


async def test_status_not_configured():
    async with _client() as client:
        cookies = await _login(client)
        r = await client.get(STATUS, cookies=cookies)
        assert r.status_code == 200
        data = r.json()
        assert data["connected"] is False
        assert data["status"] == "not_configured"
        assert data["enabled"] is False


async def test_status_after_connect():
    async with _client() as client:
        cookies = await _login(client)
        await _connect(client, cookies)
        r = await client.get(STATUS, cookies=cookies)
        assert r.status_code == 200
        assert r.json()["connected"] is True
        assert GLOOKO_PASSWORD not in r.text


# --- settings ---


async def test_settings_update_and_404_when_not_configured():
    async with _client() as client:
        cookies = await _login(client)
        # 404 before connect.
        r = await client.put(
            SETTINGS,
            json={"enabled": False, "sync_interval_minutes": 60},
            cookies=cookies,
        )
        assert r.status_code == 404

        await _connect(client, cookies)
        r = await client.put(
            SETTINGS,
            json={"enabled": False, "sync_interval_minutes": 120},
            cookies=cookies,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["enabled"] is False
        assert data["sync_interval_minutes"] == 120


async def test_settings_out_of_range_422():
    async with _client() as client:
        cookies = await _login(client)
        # Schema bounds (15-1440) fire before the 404 lookup.
        r = await client.put(
            SETTINGS,
            json={"enabled": True, "sync_interval_minutes": 5},
            cookies=cookies,
        )
        assert r.status_code == 422
        r = await client.put(
            SETTINGS,
            json={"enabled": True, "sync_interval_minutes": 2000},
            cookies=cookies,
        )
        assert r.status_code == 422


# --- sync ---


async def test_sync_now_success():
    async with _client() as client:
        cookies = await _login(client)
        await _connect(client, cookies)
        with patch(
            "src.routers.integrations.sync_glooko_for_user",
            new=AsyncMock(
                return_value=GlookoSyncResult(
                    glucose_fetched=20,
                    glucose_stored=18,
                    events_fetched=4,
                    events_stored=4,
                )
            ),
        ):
            r = await client.post(SYNC, cookies=cookies)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["glucose_stored"] == 18
        assert data["events_stored"] == 4


async def test_sync_now_404_when_not_configured():
    async with _client() as client:
        cookies = await _login(client)
        r = await client.post(SYNC, cookies=cookies)
        assert r.status_code == 404


async def test_sync_now_bad_credentials_maps_to_400():
    async def _fail_disconnected(db, state, **kw):
        # Mirror _mark_failure on an auth error: flip the row to disconnected.
        state.status = STATUS_DISCONNECTED
        raise GlookoSyncRunError("auth failed")

    async with _client() as client:
        cookies = await _login(client)
        await _connect(client, cookies)
        with patch(
            "src.routers.integrations.sync_glooko_for_user", new=_fail_disconnected
        ):
            r = await client.post(SYNC, cookies=cookies)
        assert r.status_code == 400


async def test_sync_now_transient_failure_maps_to_503():
    async def _fail_transient(db, state, **kw):
        # Transient: row stays "connected" (status not flipped).
        raise GlookoSyncRunError("network blip")

    async with _client() as client:
        cookies = await _login(client)
        await _connect(client, cookies)
        with patch(
            "src.routers.integrations.sync_glooko_for_user", new=_fail_transient
        ):
            r = await client.post(SYNC, cookies=cookies)
        assert r.status_code == 503


# --- availability (read-only) ---


async def test_availability_success():
    async with _client() as client:
        cookies = await _login(client)
        await _connect(client, cookies)
        with patch(
            "src.routers.integrations.probe_glooko_availability",
            new=AsyncMock(
                return_value=GlookoAvailability(
                    cgm_available=True, earliest=None, latest=None
                )
            ),
        ):
            r = await client.get(AVAILABILITY, cookies=cookies)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["connected"] is True
        assert data["cgm_available"] is True


async def test_availability_404_when_not_configured():
    async with _client() as client:
        cookies = await _login(client)
        r = await client.get(AVAILABILITY, cookies=cookies)
        assert r.status_code == 404


async def test_availability_is_read_only_does_not_mutate_state():
    """An availability probe that fails auth returns 400 but must NOT flip the
    stored status (persist_status=False) -- the row stays connected."""
    async with _client() as client:
        cookies = await _login(client)
        await _connect(client, cookies)
        with patch(
            "src.routers.integrations.probe_glooko_availability",
            new=AsyncMock(side_effect=GlookoAuthError("bad session")),
        ):
            r = await client.get(AVAILABILITY, cookies=cookies)
        assert r.status_code == 400
        # The stored status is untouched by the failed probe.
        r = await client.get(STATUS, cookies=cookies)
        assert r.json()["status"] == "connected"


# --- import ---


async def test_import_success():
    async with _client() as client:
        cookies = await _login(client)
        await _connect(client, cookies)
        with patch(
            "src.routers.integrations.import_glooko_history_for_user",
            new=AsyncMock(
                return_value=GlookoSyncResult(
                    glucose_fetched=500,
                    glucose_stored=480,
                    events_fetched=30,
                    events_stored=30,
                )
            ),
        ):
            r = await client.post(IMPORT, cookies=cookies)
        assert r.status_code == 200, r.text
        assert r.json()["glucose_stored"] == 480


async def test_import_404_when_not_configured():
    async with _client() as client:
        cookies = await _login(client)
        r = await client.post(IMPORT, cookies=cookies)
        assert r.status_code == 404


# --- disconnect ---


async def test_disconnect_then_status_not_configured():
    async with _client() as client:
        cookies = await _login(client)
        await _connect(client, cookies)
        r = await client.request("DELETE", CONNECT, cookies=cookies)
        assert r.status_code == 200
        r = await client.get(STATUS, cookies=cookies)
        assert r.json()["status"] == "not_configured"


async def test_disconnect_is_idempotent():
    async with _client() as client:
        cookies = await _login(client)
        # Disconnect without ever connecting is a safe no-op.
        r = await client.request("DELETE", CONNECT, cookies=cookies)
        assert r.status_code == 200
