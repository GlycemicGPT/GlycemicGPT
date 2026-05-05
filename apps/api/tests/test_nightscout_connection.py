"""Story 43.1: tests for Nightscout connection management.

Mocks the connection-test stub at the httpx layer so tests don't reach
out to the real internet. We verify model + endpoints + RBAC + the
shape of what the test stub does. Story 43.2 ships proper integration
tests against a real Nightscout instance.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from src.core.encryption import decrypt_credential
from src.database import get_session_maker
from src.main import app
from src.models.nightscout_connection import (
    NightscoutConnection,
    NightscoutSyncStatus,
)
from src.models.user import User
from src.services.integrations.nightscout.connection_test import ConnectionTestOutcome

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_outcome(server_version: str = "15.0.3") -> ConnectionTestOutcome:
    return ConnectionTestOutcome(
        ok=True,
        server_version=server_version,
        api_version_detected=None,  # router fills this in from the request
        auth_validated=True,
    )


def _fail_outcome(error: str = "auth rejected") -> ConnectionTestOutcome:
    return ConnectionTestOutcome(ok=False, error=error)


def _patch_test_connection(outcome: ConnectionTestOutcome):
    """Patch the connection-test stub used by the router."""
    return patch(
        "src.routers.nightscout.test_connection",
        new=AsyncMock(return_value=outcome),
    )


def _unique_email(stem: str) -> str:
    """UUID-suffixed test email for cross-test isolation.

    Even if a test crashes between user creation and cleanup, the next
    run uses a different email so it doesn't collide with the leaked
    row.
    """
    return f"{stem}_{uuid.uuid4().hex[:10]}@example.com"


async def _register_and_login(client, email: str, password: str = "Test1234!"):
    from src.config import settings

    reg = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.text}"
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    cookie = resp.cookies.get(settings.jwt_cookie_name)
    assert cookie, "login did not set the auth cookie"
    return {settings.jwt_cookie_name: cookie}


async def _cleanup_nightscout_users(emails: list[str]) -> None:
    """Tear down rows + users we created during tests."""
    async with get_session_maker()() as db:
        result = await db.execute(User.__table__.select().where(User.email.in_(emails)))
        ids = [row.id for row in result.fetchall()]
        if ids:
            await db.execute(
                delete(NightscoutConnection).where(
                    NightscoutConnection.user_id.in_(ids)
                )
            )
            await db.execute(delete(User).where(User.id.in_(ids)))
            await db.commit()


@pytest_asyncio.fixture
async def http_client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# POST /api/integrations/nightscout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_connection_succeeds_when_test_passes(http_client):
    email = _unique_email("ns_create_ok")
    cookies = await _register_and_login(http_client, email)
    try:
        with _patch_test_connection(_ok_outcome("15.0.3")):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies,
                json={
                    "name": "My NS",
                    "base_url": "https://my-ns.example.com",
                    "auth_type": "secret",
                    "credential": "test-api-secret-12chars",
                    "api_version": "v1",
                },
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["test"]["ok"] is True
        assert body["test"]["server_version"] == "15.0.3"
        assert body["connection"]["name"] == "My NS"
        assert body["connection"]["has_credential"] is True
        assert body["connection"]["base_url"] == "https://my-ns.example.com"
        assert body["connection"]["sync_interval_minutes"] == 5
        assert body["connection"]["initial_sync_window_days"] == 7
        # Credential is never returned.
        assert "credential" not in body["connection"]
        assert "encrypted_credential" not in body["connection"]
    finally:
        await _cleanup_nightscout_users([email])


@pytest.mark.asyncio
async def test_create_connection_returns_400_when_test_fails(http_client):
    email = _unique_email("ns_create_fail")
    cookies = await _register_and_login(http_client, email)
    try:
        with _patch_test_connection(_fail_outcome("Authentication rejected")):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies,
                json={
                    "name": "Bad creds",
                    "base_url": "https://my-ns.example.com",
                    "auth_type": "secret",
                    "credential": "wrong",
                    "api_version": "v1",
                },
            )
        assert resp.status_code == 400, resp.text
        # Persists nothing on failure.
        list_resp = await http_client.get(
            "/api/integrations/nightscout", cookies=cookies
        )
        assert list_resp.status_code == 200
        assert list_resp.json()["connections"] == []
    finally:
        await _cleanup_nightscout_users([email])


@pytest.mark.asyncio
async def test_create_connection_rejects_bad_url_at_schema_layer(http_client):
    email = _unique_email("ns_bad_url")
    cookies = await _register_and_login(http_client, email)
    try:
        # No connection-test patch needed -- request rejected before we get there.
        resp = await http_client.post(
            "/api/integrations/nightscout",
            cookies=cookies,
            json={
                "name": "Bad URL",
                "base_url": "ftp://nope.example.com",
                "auth_type": "secret",
                "credential": "x",
                "api_version": "v1",
            },
        )
        assert resp.status_code == 422
    finally:
        await _cleanup_nightscout_users([email])


@pytest.mark.asyncio
async def test_create_connection_strips_trailing_slash(http_client):
    email = _unique_email("ns_trailing")
    cookies = await _register_and_login(http_client, email)
    try:
        with _patch_test_connection(_ok_outcome()):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies,
                json={
                    "name": "Trailing",
                    "base_url": "https://my-ns.example.com/",  # trailing slash
                    "auth_type": "secret",
                    "credential": "secret123",
                    "api_version": "v1",
                },
            )
        assert resp.status_code == 201
        assert resp.json()["connection"]["base_url"] == "https://my-ns.example.com"
    finally:
        await _cleanup_nightscout_users([email])


@pytest.mark.asyncio
async def test_create_connection_credential_is_encrypted_in_db(http_client):
    email = _unique_email("ns_encrypted")
    cookies = await _register_and_login(http_client, email)
    try:
        with _patch_test_connection(_ok_outcome()):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies,
                json={
                    "name": "Encrypted",
                    "base_url": "https://my-ns.example.com",
                    "auth_type": "secret",
                    "credential": "supersecret-plaintext-12chars",
                    "api_version": "v1",
                },
            )
        assert resp.status_code == 201
        connection_id = resp.json()["connection"]["id"]

        # Inspect the DB directly: the raw column must NOT contain the
        # plaintext, AND the round-trip must recover it.
        async with get_session_maker()() as db:
            row = (
                await db.execute(
                    NightscoutConnection.__table__.select().where(
                        NightscoutConnection.id == uuid.UUID(connection_id)
                    )
                )
            ).first()
            assert row is not None
            stored = row.encrypted_credential
            assert "supersecret-plaintext-12chars" not in stored
            assert decrypt_credential(stored) == "supersecret-plaintext-12chars"
    finally:
        await _cleanup_nightscout_users([email])


# ---------------------------------------------------------------------------
# GET list / single + RBAC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_only_own_connections(http_client):
    """User A and User B each create a connection. List shows only own."""
    email_a = _unique_email("ns_list_a")
    email_b = _unique_email("ns_list_b")
    cookies_a = await _register_and_login(http_client, email_a)
    cookies_b = await _register_and_login(http_client, email_b)
    try:
        with _patch_test_connection(_ok_outcome()):
            await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies_a,
                json={
                    "name": "A's NS",
                    "base_url": "https://ns-a.example.com",
                    "auth_type": "secret",
                    "credential": "secretA",
                    "api_version": "v1",
                },
            )
            await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies_b,
                json={
                    "name": "B's NS",
                    "base_url": "https://ns-b.example.com",
                    "auth_type": "secret",
                    "credential": "secretB",
                    "api_version": "v1",
                },
            )

        # User A sees only A's
        resp_a = await http_client.get(
            "/api/integrations/nightscout", cookies=cookies_a
        )
        assert resp_a.status_code == 200
        names_a = [c["name"] for c in resp_a.json()["connections"]]
        assert names_a == ["A's NS"]

        # User B sees only B's
        resp_b = await http_client.get(
            "/api/integrations/nightscout", cookies=cookies_b
        )
        assert resp_b.status_code == 200
        names_b = [c["name"] for c in resp_b.json()["connections"]]
        assert names_b == ["B's NS"]
    finally:
        await _cleanup_nightscout_users([email_a, email_b])


@pytest.mark.asyncio
async def test_get_single_rejects_cross_tenant_with_404(http_client):
    """User A cannot read User B's connection by ID -- 404 (not 403)."""
    email_a = _unique_email("ns_xt_a")
    email_b = _unique_email("ns_xt_b")
    cookies_a = await _register_and_login(http_client, email_a)
    cookies_b = await _register_and_login(http_client, email_b)
    try:
        with _patch_test_connection(_ok_outcome()):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies_b,
                json={
                    "name": "B private",
                    "base_url": "https://ns-private.example.com",
                    "auth_type": "secret",
                    "credential": "private",
                    "api_version": "v1",
                },
            )
        assert resp.status_code == 201, resp.text
        b_id = resp.json()["connection"]["id"]

        # User A tries to read B's connection -> 404, not 403.
        # Returning 404 (not 403) avoids leaking the existence of B's
        # connection IDs to A.
        resp = await http_client.get(
            f"/api/integrations/nightscout/{b_id}", cookies=cookies_a
        )
        assert resp.status_code == 404
    finally:
        await _cleanup_nightscout_users([email_a, email_b])


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(http_client):
    resp = await http_client.get("/api/integrations/nightscout")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# PATCH
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_without_url_or_credential_does_not_retest(http_client):
    """Renaming a connection should NOT trigger a re-test."""
    email = _unique_email("ns_patch_norest")
    cookies = await _register_and_login(http_client, email)
    try:
        with _patch_test_connection(_ok_outcome()):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies,
                json={
                    "name": "Original",
                    "base_url": "https://ns.example.com",
                    "auth_type": "secret",
                    "credential": "secret",
                    "api_version": "v1",
                },
            )
        cid = resp.json()["connection"]["id"]

        # Patch only the name -- re-test should NOT be invoked.
        with patch(
            "src.routers.nightscout.test_connection",
            new=AsyncMock(return_value=_ok_outcome()),
        ) as mock_test:
            resp = await http_client.patch(
                f"/api/integrations/nightscout/{cid}",
                cookies=cookies,
                json={"name": "Renamed"},
            )
        assert resp.status_code == 200
        assert resp.json()["connection"]["name"] == "Renamed"
        mock_test.assert_not_called()
    finally:
        await _cleanup_nightscout_users([email])


@pytest.mark.asyncio
async def test_patch_with_credential_change_retests(http_client):
    email = _unique_email("ns_patch_cred")
    cookies = await _register_and_login(http_client, email)
    try:
        with _patch_test_connection(_ok_outcome()):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies,
                json={
                    "name": "Cred patch",
                    "base_url": "https://ns.example.com",
                    "auth_type": "secret",
                    "credential": "old-secret",
                    "api_version": "v1",
                },
            )
        cid = resp.json()["connection"]["id"]

        with patch(
            "src.routers.nightscout.test_connection",
            new=AsyncMock(return_value=_ok_outcome()),
        ) as mock_test:
            resp = await http_client.patch(
                f"/api/integrations/nightscout/{cid}",
                cookies=cookies,
                json={"credential": "new-secret"},
            )
        assert resp.status_code == 200
        assert resp.json()["test"]["ok"] is True
        mock_test.assert_called_once()
    finally:
        await _cleanup_nightscout_users([email])


@pytest.mark.asyncio
async def test_patch_failed_retest_does_not_persist_bad_credential(
    http_client,
):
    """Bad credential update -> 400 -> old credential still works."""
    email = _unique_email("ns_patch_bad")
    cookies = await _register_and_login(http_client, email)
    try:
        with _patch_test_connection(_ok_outcome()):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies,
                json={
                    "name": "Bad patch",
                    "base_url": "https://ns.example.com",
                    "auth_type": "secret",
                    "credential": "good-secret",
                    "api_version": "v1",
                },
            )
        cid = resp.json()["connection"]["id"]

        # Attempt to patch in a bad credential.
        with patch(
            "src.routers.nightscout.test_connection",
            new=AsyncMock(return_value=_fail_outcome("rejected")),
        ):
            resp = await http_client.patch(
                f"/api/integrations/nightscout/{cid}",
                cookies=cookies,
                json={"credential": "bad-secret"},
            )
        assert resp.status_code == 400

        # Verify the stored credential is still the original one.
        async with get_session_maker()() as db:
            row = (
                await db.execute(
                    NightscoutConnection.__table__.select().where(
                        NightscoutConnection.id == uuid.UUID(cid)
                    )
                )
            ).first()
            assert decrypt_credential(row.encrypted_credential) == "good-secret"
    finally:
        await _cleanup_nightscout_users([email])


@pytest.mark.asyncio
async def test_patch_empty_body_rejected(http_client):
    email = _unique_email("ns_patch_empty")
    cookies = await _register_and_login(http_client, email)
    try:
        with _patch_test_connection(_ok_outcome()):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies,
                json={
                    "name": "Empty patch",
                    "base_url": "https://ns.example.com",
                    "auth_type": "secret",
                    "credential": "secret",
                    "api_version": "v1",
                },
            )
        cid = resp.json()["connection"]["id"]

        resp = await http_client.patch(
            f"/api/integrations/nightscout/{cid}",
            cookies=cookies,
            json={},
        )
        assert resp.status_code == 422
    finally:
        await _cleanup_nightscout_users([email])


# ---------------------------------------------------------------------------
# DELETE (soft-delete)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_soft_deletes(http_client):
    """DELETE marks is_active=false but row stays."""
    email = _unique_email("ns_delete")
    cookies = await _register_and_login(http_client, email)
    try:
        with _patch_test_connection(_ok_outcome()):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies,
                json={
                    "name": "To delete",
                    "base_url": "https://ns.example.com",
                    "auth_type": "secret",
                    "credential": "secret",
                    "api_version": "v1",
                },
            )
        cid = resp.json()["connection"]["id"]

        resp = await http_client.delete(
            f"/api/integrations/nightscout/{cid}", cookies=cookies
        )
        assert resp.status_code == 200
        assert resp.json()["deactivated"] is True

        # Row still readable, just inactive.
        resp = await http_client.get(
            f"/api/integrations/nightscout/{cid}", cookies=cookies
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
    finally:
        await _cleanup_nightscout_users([email])


@pytest.mark.asyncio
async def test_delete_other_user_returns_404(http_client):
    email_a = _unique_email("ns_del_a")
    email_b = _unique_email("ns_del_b")
    cookies_a = await _register_and_login(http_client, email_a)
    cookies_b = await _register_and_login(http_client, email_b)
    try:
        with _patch_test_connection(_ok_outcome()):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies_b,
                json={
                    "name": "B's",
                    "base_url": "https://ns-b.example.com",
                    "auth_type": "secret",
                    "credential": "secret",
                    "api_version": "v1",
                },
            )
        cid = resp.json()["connection"]["id"]

        resp = await http_client.delete(
            f"/api/integrations/nightscout/{cid}", cookies=cookies_a
        )
        assert resp.status_code == 404

        # B's connection still active.
        resp = await http_client.get(
            f"/api/integrations/nightscout/{cid}", cookies=cookies_b
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True
    finally:
        await _cleanup_nightscout_users([email_a, email_b])


# ---------------------------------------------------------------------------
# POST /{id}/test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_test_updates_status_on_success(http_client):
    email = _unique_email("ns_test_ok")
    cookies = await _register_and_login(http_client, email)
    try:
        with _patch_test_connection(_ok_outcome()):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies,
                json={
                    "name": "Test ok",
                    "base_url": "https://ns.example.com",
                    "auth_type": "secret",
                    "credential": "secret",
                    "api_version": "v1",
                },
            )
        cid = resp.json()["connection"]["id"]

        with _patch_test_connection(_ok_outcome("16.0.0")):
            resp = await http_client.post(
                f"/api/integrations/nightscout/{cid}/test", cookies=cookies
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["server_version"] == "16.0.0"

        # Status reflects the most recent test.
        resp = await http_client.get(
            f"/api/integrations/nightscout/{cid}", cookies=cookies
        )
        assert resp.json()["last_sync_status"] == NightscoutSyncStatus.OK.value
    finally:
        await _cleanup_nightscout_users([email])


@pytest.mark.asyncio
async def test_post_test_records_failure_in_status(http_client):
    email = _unique_email("ns_test_fail")
    cookies = await _register_and_login(http_client, email)
    try:
        with _patch_test_connection(_ok_outcome()):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies,
                json={
                    "name": "Test then fail",
                    "base_url": "https://ns.example.com",
                    "auth_type": "secret",
                    "credential": "secret",
                    "api_version": "v1",
                },
            )
        cid = resp.json()["connection"]["id"]

        # Auth failure (auth_validated=False, api_version_detected
        # populated -> reached the server but credential rejected)
        # should produce AUTH_FAILED status.
        from src.models.nightscout_connection import NightscoutApiVersion

        auth_fail = ConnectionTestOutcome(
            ok=False,
            api_version_detected=NightscoutApiVersion.V1,
            auth_validated=False,
            error="Authentication rejected",
        )
        with patch(
            "src.routers.nightscout.test_connection",
            new=AsyncMock(return_value=auth_fail),
        ):
            resp = await http_client.post(
                f"/api/integrations/nightscout/{cid}/test", cookies=cookies
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is False

        # Status should now be AUTH_FAILED
        resp = await http_client.get(
            f"/api/integrations/nightscout/{cid}", cookies=cookies
        )
        body = resp.json()
        assert body["last_sync_status"] == NightscoutSyncStatus.AUTH_FAILED.value
        assert body["last_sync_error"] == "Authentication rejected"
    finally:
        await _cleanup_nightscout_users([email])


# ---------------------------------------------------------------------------
# Behaviour changes from adversarial review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_leaves_last_sync_status_as_never(http_client):
    """Successful connection-test should NOT mark sync as OK -- a sync
    has not yet run. Only Story 43.4's actual sync writes OK."""
    email = _unique_email("ns_status_never")
    cookies = await _register_and_login(http_client, email)
    try:
        with _patch_test_connection(_ok_outcome()):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies,
                json={
                    "name": "Status check",
                    "base_url": "https://my-ns.example.com",
                    "auth_type": "secret",
                    "credential": "secret",
                    "api_version": "v1",
                },
            )
        assert resp.status_code == 201
        assert resp.json()["connection"]["last_sync_status"] == (
            NightscoutSyncStatus.NEVER.value
        )
        assert resp.json()["connection"]["last_synced_at"] is None
    finally:
        await _cleanup_nightscout_users([email])


@pytest.mark.asyncio
async def test_patch_with_auth_type_change_retests(http_client):
    """Flipping auth_type reinterprets the credential against a
    different protocol -- must re-validate."""
    email = _unique_email("ns_auth_change")
    cookies = await _register_and_login(http_client, email)
    try:
        with _patch_test_connection(_ok_outcome()):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies,
                json={
                    "name": "Auth flip",
                    "base_url": "https://ns.example.com",
                    "auth_type": "secret",
                    "credential": "creds",
                    "api_version": "v1",
                },
            )
        cid = resp.json()["connection"]["id"]

        with patch(
            "src.routers.nightscout.test_connection",
            new=AsyncMock(return_value=_ok_outcome()),
        ) as mock_test:
            resp = await http_client.patch(
                f"/api/integrations/nightscout/{cid}",
                cookies=cookies,
                json={"auth_type": "token"},
            )
        assert resp.status_code == 200
        mock_test.assert_called_once()
    finally:
        await _cleanup_nightscout_users([email])


@pytest.mark.asyncio
async def test_patch_with_api_version_change_retests(http_client):
    """Flipping api_version reinterprets the credential against a
    different API surface -- must re-validate."""
    email = _unique_email("ns_apiver_change")
    cookies = await _register_and_login(http_client, email)
    try:
        with _patch_test_connection(_ok_outcome()):
            resp = await http_client.post(
                "/api/integrations/nightscout",
                cookies=cookies,
                json={
                    "name": "API ver flip",
                    "base_url": "https://ns.example.com",
                    "auth_type": "secret",
                    "credential": "creds",
                    "api_version": "v1",
                },
            )
        cid = resp.json()["connection"]["id"]

        with patch(
            "src.routers.nightscout.test_connection",
            new=AsyncMock(return_value=_ok_outcome()),
        ) as mock_test:
            resp = await http_client.patch(
                f"/api/integrations/nightscout/{cid}",
                cookies=cookies,
                json={"api_version": "v3"},
            )
        assert resp.status_code == 200
        mock_test.assert_called_once()
    finally:
        await _cleanup_nightscout_users([email])


@pytest.mark.asyncio
async def test_create_rejects_url_with_query_string(http_client):
    """https://valid.com/?@evil.com style URLs must be rejected at
    schema layer before they ever reach the SSRF guard."""
    email = _unique_email("ns_url_query")
    cookies = await _register_and_login(http_client, email)
    try:
        resp = await http_client.post(
            "/api/integrations/nightscout",
            cookies=cookies,
            json={
                "name": "Query bad",
                "base_url": "https://my-ns.example.com/?evil=1",
                "auth_type": "secret",
                "credential": "x",
                "api_version": "v1",
            },
        )
        assert resp.status_code == 422
    finally:
        await _cleanup_nightscout_users([email])


@pytest.mark.asyncio
async def test_create_rejects_url_with_embedded_credentials(http_client):
    email = _unique_email("ns_url_embedcreds")
    cookies = await _register_and_login(http_client, email)
    try:
        resp = await http_client.post(
            "/api/integrations/nightscout",
            cookies=cookies,
            json={
                "name": "Embedded creds",
                "base_url": "https://user:pw@my-ns.example.com",
                "auth_type": "secret",
                "credential": "x",
                "api_version": "v1",
            },
        )
        assert resp.status_code == 422
    finally:
        await _cleanup_nightscout_users([email])


@pytest.mark.asyncio
async def test_create_rejects_url_with_fragment(http_client):
    email = _unique_email("ns_url_fragment")
    cookies = await _register_and_login(http_client, email)
    try:
        resp = await http_client.post(
            "/api/integrations/nightscout",
            cookies=cookies,
            json={
                "name": "Fragment bad",
                "base_url": "https://my-ns.example.com#hash",
                "auth_type": "secret",
                "credential": "x",
                "api_version": "v1",
            },
        )
        assert resp.status_code == 422
    finally:
        await _cleanup_nightscout_users([email])


# ---------------------------------------------------------------------------
# SSRF guard unit tests (direct, no router involvement)
# ---------------------------------------------------------------------------


class TestSsrfGuard:
    """Direct unit tests for the URL-validation function. Mock DNS so
    we don't rely on real-world DNS to test malicious-resolution paths."""

    @pytest.mark.asyncio
    async def test_rejects_aws_imds_via_dns(self):
        """A hostname that resolves to AWS IMDS must be rejected even
        if the hostname itself is a regular FQDN."""
        from src.services.integrations.nightscout import connection_test as ct

        async def fake_resolve(_hostname):
            import ipaddress as ip

            return [ip.ip_address("169.254.169.254")]

        with patch.object(ct, "_resolve_host", new=fake_resolve):
            outcome = await ct.test_connection(
                "https://attacker.example.com",
                ct.NightscoutAuthType.SECRET,
                "x",
                ct.NightscoutApiVersion.V1,
            )
        assert outcome.ok is False
        assert "metadata" in (outcome.error or "").lower()

    @pytest.mark.asyncio
    async def test_rejects_alibaba_metadata(self):
        from src.services.integrations.nightscout import connection_test as ct

        async def fake_resolve(_hostname):
            import ipaddress as ip

            return [ip.ip_address("100.100.100.200")]

        with patch.object(ct, "_resolve_host", new=fake_resolve):
            outcome = await ct.test_connection(
                "https://attacker.example.com",
                ct.NightscoutAuthType.SECRET,
                "x",
                ct.NightscoutApiVersion.V1,
            )
        assert outcome.ok is False
        assert "metadata" in (outcome.error or "").lower()

    @pytest.mark.asyncio
    async def test_rejects_oracle_metadata(self):
        from src.services.integrations.nightscout import connection_test as ct

        async def fake_resolve(_hostname):
            import ipaddress as ip

            return [ip.ip_address("192.0.0.192")]

        with patch.object(ct, "_resolve_host", new=fake_resolve):
            outcome = await ct.test_connection(
                "https://attacker.example.com",
                ct.NightscoutAuthType.SECRET,
                "x",
                ct.NightscoutApiVersion.V1,
            )
        assert outcome.ok is False
        assert "metadata" in (outcome.error or "").lower()

    @pytest.mark.asyncio
    async def test_rejects_ipv4_mapped_ipv6_metadata(self):
        """169.254.169.254 expressed as ::ffff:169.254.169.254 must
        also be blocked."""
        from src.services.integrations.nightscout import connection_test as ct

        async def fake_resolve(_hostname):
            import ipaddress as ip

            return [ip.ip_address("::ffff:169.254.169.254")]

        with patch.object(ct, "_resolve_host", new=fake_resolve):
            outcome = await ct.test_connection(
                "https://attacker.example.com",
                ct.NightscoutAuthType.SECRET,
                "x",
                ct.NightscoutApiVersion.V1,
            )
        assert outcome.ok is False
        assert "metadata" in (outcome.error or "").lower()

    @pytest.mark.asyncio
    async def test_rejects_aws_ipv6_imds(self):
        from src.services.integrations.nightscout import connection_test as ct

        async def fake_resolve(_hostname):
            import ipaddress as ip

            return [ip.ip_address("fd00:ec2::254")]

        with patch.object(ct, "_resolve_host", new=fake_resolve):
            outcome = await ct.test_connection(
                "https://attacker.example.com",
                ct.NightscoutAuthType.SECRET,
                "x",
                ct.NightscoutApiVersion.V1,
            )
        assert outcome.ok is False
        assert "metadata" in (outcome.error or "").lower()

    @pytest.mark.asyncio
    async def test_rejects_private_ip_when_homelab_disabled(self):
        from src.services.integrations.nightscout import connection_test as ct

        async def fake_resolve(_hostname):
            import ipaddress as ip

            return [ip.ip_address("10.0.0.5")]

        with (
            patch.object(ct, "_resolve_host", new=fake_resolve),
            patch.object(ct.settings, "allow_private_ai_urls", False),
        ):
            outcome = await ct.test_connection(
                "https://internal.example.com",
                ct.NightscoutAuthType.SECRET,
                "x",
                ct.NightscoutApiVersion.V1,
            )
        assert outcome.ok is False
        assert "private" in (outcome.error or "").lower()

    @pytest.mark.asyncio
    async def test_dns_resolution_failure_yields_clean_error(self):
        from src.services.integrations.nightscout import connection_test as ct

        async def fake_resolve(_hostname):
            raise ValueError("Could not resolve host: nonexistent.example.invalid")

        with patch.object(ct, "_resolve_host", new=fake_resolve):
            outcome = await ct.test_connection(
                "https://nonexistent.example.invalid",
                ct.NightscoutAuthType.SECRET,
                "x",
                ct.NightscoutApiVersion.V1,
            )
        assert outcome.ok is False
        assert "resolve" in (outcome.error or "").lower()
