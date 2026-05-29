"""Tests for the Medtronic Connect (autonomous sync) endpoints.

The Auth0 code exchange (``exchange_code_for_tokens``) and the sync
orchestrator (``sync_connect_for_user``) are patched so these stay pure
unit/HTTP tests with a real test DB for the state row.
"""

import uuid
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.main import app
from src.services.integrations.medtronic.connect_auth import (
    ConnectTokenError,
    TokenResponse,
)
from src.services.integrations.medtronic.connect_sync import (
    ConnectSyncResult,
)

STATUS = "/api/integrations/medtronic/connect/status"
SETTINGS = "/api/integrations/medtronic/connect/settings"
DISCONNECT = "/api/integrations/medtronic/connect/disconnect"
SYNC = "/api/integrations/medtronic/connect/sync"
PAIR = "/api/integrations/medtronic/connect/pair"
AUTHZ_URL = "/api/integrations/medtronic/connect/authorize-url"
EXCHANGE = "/api/integrations/medtronic/connect/exchange"


def _email() -> str:
    return f"connect_{uuid.uuid4().hex[:8]}@example.com"


async def _login(client: AsyncClient) -> dict:
    email, pw = _email(), "SecurePass123"
    await client.post("/api/auth/register", json={"email": email, "password": pw})
    r = await client.post("/api/auth/login", json={"email": email, "password": pw})
    return {settings.jwt_cookie_name: r.cookies.get(settings.jwt_cookie_name)}


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True
    )


async def _connect(
    client,
    cookies,
    *,
    region: str = "US",
    username: str = "user@example.com",
    role: str = "patient",
    patient_id: str | None = None,
):
    """Establish a connected MedtronicConnectState via the real authorize-url +
    exchange flow (the surviving connect path), with the Auth0 code exchange
    mocked. Returns the /exchange response so callers can assert on it."""
    s = (await client.get(AUTHZ_URL, params={"region": region}, cookies=cookies)).json()
    body: dict = {
        "pkce_session": s["pkce_session"],
        "redirect_url": (
            f"com.medtronic.carepartner:/sso?code=test-code&state={s['state']}"
        ),
        "username": username,
        "role": role,
    }
    if patient_id is not None:
        body["patient_id"] = patient_id
    with patch(
        "src.routers.integrations.exchange_code_for_tokens",
        new=AsyncMock(
            return_value=TokenResponse(
                access_token="acc", expires_in=10800, refresh_token="rotated"
            )
        ),
    ):
        return await client.post(EXCHANGE, json=body, cookies=cookies)


async def test_connect_via_exchange_stores_state_and_hides_token():
    async with _client() as client:
        cookies = await _login(client)
        r = await _connect(client, cookies)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["connected"] is True
        assert data["status"] == "connected"
        assert data["enabled"] is True
        assert data["region"] == "US"
        # The (rotated) refresh token must never be echoed back anywhere.
        assert "rotated" not in r.text
        assert "refresh_token" not in data


async def test_connect_via_exchange_follower_requires_patient_id_422():
    async with _client() as client:
        cookies = await _login(client)
        r = await _connect(client, cookies, role="carepartner")
        assert r.status_code == 422


async def test_connect_via_exchange_dead_token_401():
    async with _client() as client:
        cookies = await _login(client)
        s = (
            await client.get(AUTHZ_URL, params={"region": "US"}, cookies=cookies)
        ).json()
        body = {
            "pkce_session": s["pkce_session"],
            "redirect_url": (
                f"com.medtronic.carepartner:/sso?code=test-code&state={s['state']}"
            ),
            "username": "user@example.com",
        }
        with patch(
            "src.routers.integrations.exchange_code_for_tokens",
            new=AsyncMock(side_effect=ConnectTokenError("rejected")),
        ):
            r = await client.post(EXCHANGE, json=body, cookies=cookies)
        assert r.status_code == 401


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
        assert r.json()["connected"] is True


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
        r = await client.put(
            SETTINGS,
            json={"enabled": True, "sync_interval_minutes": 5},
            cookies=cookies,
        )
        # 422 from schema bounds (fires before the 404 lookup).
        assert r.status_code == 422


async def test_disconnect_then_status_not_configured():
    async with _client() as client:
        cookies = await _login(client)
        await _connect(client, cookies)
        r = await client.post(DISCONNECT, cookies=cookies)
        assert r.status_code == 200
        r = await client.get(STATUS, cookies=cookies)
        assert r.json()["status"] == "not_configured"


async def test_sync_now_success():
    async with _client() as client:
        cookies = await _login(client)
        await _connect(client, cookies)
        with patch(
            "src.routers.integrations.sync_connect_for_user",
            new=AsyncMock(
                return_value=ConnectSyncResult(
                    glucose_fetched=10,
                    glucose_stored=8,
                    events_fetched=3,
                    events_stored=3,
                )
            ),
        ):
            r = await client.post(SYNC, cookies=cookies)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["glucose_stored"] == 8
        assert data["events_stored"] == 3


async def test_sync_now_404_when_not_configured():
    async with _client() as client:
        cookies = await _login(client)
        r = await client.post(SYNC, cookies=cookies)
        assert r.status_code == 404


# --- PKCE login (authorize-url + exchange) ---


async def test_authorize_url_returns_url_and_opaque_session():
    async with _client() as client:
        cookies = await _login(client)
        r = await client.get(AUTHZ_URL, params={"region": "US"}, cookies=cookies)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "carelink-login.minimed.com/authorize" in data["authorize_url"]
        assert data["state"] in data["authorize_url"]
        # The session blob must not leak the verifier in the clear.
        assert "code_verifier" not in data["pkce_session"]
        assert data["pkce_session"]  # opaque, non-empty


async def test_authorize_url_invalid_region_422():
    async with _client() as client:
        cookies = await _login(client)
        r = await client.get(AUTHZ_URL, params={"region": "JP"}, cookies=cookies)
        assert r.status_code == 422


async def test_exchange_full_flow_connects():
    async with _client() as client:
        cookies = await _login(client)
        # Start the login to obtain a real (encrypted) session + state.
        start = (
            await client.get(AUTHZ_URL, params={"region": "US"}, cookies=cookies)
        ).json()
        redirect = (
            f"com.medtronic.carepartner:/sso?code=auth-code&state={start['state']}"
        )
        with patch(
            "src.routers.integrations.exchange_code_for_tokens",
            new=AsyncMock(
                return_value=TokenResponse(
                    access_token="acc", expires_in=10800, refresh_token="rt"
                )
            ),
        ):
            r = await client.post(
                EXCHANGE,
                json={
                    "pkce_session": start["pkce_session"],
                    "redirect_url": redirect,
                    "username": "user@example.com",
                },
                cookies=cookies,
            )
        assert r.status_code == 200, r.text
        assert r.json()["connected"] is True
        # Verify it actually persisted.
        st = (await client.get(STATUS, cookies=cookies)).json()
        assert st["connected"] is True


async def test_exchange_state_mismatch_422():
    async with _client() as client:
        cookies = await _login(client)
        start = (
            await client.get(AUTHZ_URL, params={"region": "US"}, cookies=cookies)
        ).json()
        redirect = "com.medtronic.carepartner:/sso?code=auth-code&state=WRONG"
        r = await client.post(
            EXCHANGE,
            json={
                "pkce_session": start["pkce_session"],
                "redirect_url": redirect,
                "username": "user@example.com",
            },
            cookies=cookies,
        )
        assert r.status_code == 422


async def test_exchange_missing_code_in_redirect_422():
    async with _client() as client:
        cookies = await _login(client)
        start = (
            await client.get(AUTHZ_URL, params={"region": "US"}, cookies=cookies)
        ).json()
        r = await client.post(
            EXCHANGE,
            json={
                "pkce_session": start["pkce_session"],
                "redirect_url": "com.medtronic.carepartner:/sso?error=access_denied",
                "username": "user@example.com",
            },
            cookies=cookies,
        )
        assert r.status_code == 422


async def test_exchange_garbage_session_422():
    async with _client() as client:
        cookies = await _login(client)
        r = await client.post(
            EXCHANGE,
            json={
                "pkce_session": "not-a-valid-encrypted-blob",
                "redirect_url": "com.medtronic.carepartner:/sso?code=x&state=y",
                "username": "user@example.com",
            },
            cookies=cookies,
        )
        assert r.status_code == 422


async def test_exchange_session_bound_to_other_user_422():
    async with _client() as client:
        # User A starts the login.
        cookies_a = await _login(client)
        start = (
            await client.get(AUTHZ_URL, params={"region": "US"}, cookies=cookies_a)
        ).json()
        # User B tries to use A's session.
        cookies_b = await _login(client)
        redirect = f"com.medtronic.carepartner:/sso?code=c&state={start['state']}"
        r = await client.post(
            EXCHANGE,
            json={
                "pkce_session": start["pkce_session"],
                "redirect_url": redirect,
                "username": "user@example.com",
            },
            cookies=cookies_b,
        )
        assert r.status_code == 422


# --- Pairing token + local-CLI auth (P1) ---


async def _get_pair_token(client: AsyncClient, cookies: dict) -> str:
    r = await client.post(PAIR, cookies=cookies)
    assert r.status_code == 200, r.text
    return r.json()["pairing_token"]


async def test_pair_requires_auth():
    async with _client() as client:
        r = await client.post(PAIR)  # no cookie
        assert r.status_code == 401


async def test_pair_issues_token_for_logged_in_user():
    async with _client() as client:
        cookies = await _login(client)
        r = await client.post(PAIR, cookies=cookies)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["pairing_token"]
        assert data["expires_at"]


async def test_cli_can_connect_with_pair_token_only():
    # User logs in on the web to mint a pairing token...
    async with _client() as web:
        cookies = await _login(web)
        pair_token = await _get_pair_token(web, cookies)

    # ...the CLI (a FRESH client with NO session cookie) uses only the header.
    hdr = {"X-Connect-Pair-Token": pair_token}
    async with _client() as cli:
        start = await cli.get(AUTHZ_URL, params={"region": "US"}, headers=hdr)
        assert start.status_code == 200, start.text
        s = start.json()
        redirect = f"com.medtronic.carepartner:/sso?code=auth-code&state={s['state']}"
        with patch(
            "src.routers.integrations.exchange_code_for_tokens",
            new=AsyncMock(
                return_value=TokenResponse(
                    access_token="acc", expires_in=10800, refresh_token="rt"
                )
            ),
        ):
            r = await cli.post(
                EXCHANGE,
                json={
                    "pkce_session": s["pkce_session"],
                    "redirect_url": redirect,
                    "username": "user@example.com",
                },
                headers=hdr,
            )
        assert r.status_code == 200, r.text
        # connected=True proves the pair-token-authed exchange persisted state
        # for the paired user (no session cookie was present on this client).
        assert r.json()["connected"] is True


async def test_authorize_url_rejects_bad_pair_token():
    async with _client() as cli:
        r = await cli.get(
            AUTHZ_URL,
            params={"region": "US"},
            headers={"X-Connect-Pair-Token": "garbage-token"},
        )
        assert r.status_code == 401
        assert "garbage-token" not in r.text


async def test_authorize_url_requires_some_auth():
    async with _client() as cli:
        r = await cli.get(AUTHZ_URL, params={"region": "US"})  # no cookie, no header
        assert r.status_code == 401


async def test_pair_token_is_single_use_at_exchange():
    # Mint a pairing token (web), then simulate the CLI using it twice.
    async with _client() as web:
        cookies = await _login(web)
        pair_token = await _get_pair_token(web, cookies)

    hdr = {"X-Connect-Pair-Token": pair_token}
    tok = AsyncMock(
        return_value=TokenResponse(
            access_token="acc", expires_in=10800, refresh_token="rt"
        )
    )
    async with _client() as cli:
        # First exchange succeeds and consumes the token's jti.
        s1 = (await cli.get(AUTHZ_URL, params={"region": "US"}, headers=hdr)).json()
        redirect1 = f"com.medtronic.carepartner:/sso?code=c1&state={s1['state']}"
        with patch("src.routers.integrations.exchange_code_for_tokens", new=tok):
            r1 = await cli.post(
                EXCHANGE,
                json={
                    "pkce_session": s1["pkce_session"],
                    "redirect_url": redirect1,
                    "username": "user@example.com",
                },
                headers=hdr,
            )
        assert r1.status_code == 200, r1.text

        # authorize-url still works (it doesn't consume), but a SECOND exchange
        # with the same pairing token is rejected as already-used.
        s2 = (await cli.get(AUTHZ_URL, params={"region": "US"}, headers=hdr)).json()
        redirect2 = f"com.medtronic.carepartner:/sso?code=c2&state={s2['state']}"
        with patch("src.routers.integrations.exchange_code_for_tokens", new=tok):
            r2 = await cli.post(
                EXCHANGE,
                json={
                    "pkce_session": s2["pkce_session"],
                    "redirect_url": redirect2,
                    "username": "user@example.com",
                },
                headers=hdr,
            )
        assert r2.status_code == 401
        assert "already used" in r2.text
