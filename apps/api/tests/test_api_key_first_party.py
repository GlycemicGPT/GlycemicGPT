"""Tests for first-party enforcement on account/settings routes (CR-01).

Settings routes are first-party: the account owner acts through the web or
mobile app (session cookie or Bearer JWT). API keys are scoped third-party
credentials with no settings-write scope, so a key -- even a read-only one --
must never reach a settings read, mutation, or the data purge.
"""

import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.config import settings
from src.core.auth import require_first_party
from src.services.api_key_service import create_api_key


def _request(headers: dict | None = None, cookies: dict | None = None) -> Request:
    """Build a Starlette request with the given headers/cookies."""
    raw_headers: list[tuple[bytes, bytes]] = []
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode(), value.encode()))
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        raw_headers.append((b"cookie", cookie_str.encode()))
    return Request({"type": "http", "headers": raw_headers})


class TestRequireFirstPartyUnit:
    """Unit tests for the require_first_party dependency."""

    @pytest.mark.asyncio
    async def test_denies_pure_api_key_request(self):
        """An X-API-Key request with no first-party credential is rejected."""
        request = _request(headers={"X-API-Key": "ggpt_readonlykey"})
        with pytest.raises(HTTPException) as exc_info:
            await require_first_party(request)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_allows_request_without_api_key(self):
        """A request with no X-API-Key header is allowed (defaults, cookie)."""
        request = _request(headers={})
        assert await require_first_party(request) is None

    @pytest.mark.asyncio
    async def test_allows_cookie_even_with_stray_api_key_header(self):
        """A session cookie takes precedence, so the request is first-party."""
        request = _request(
            headers={"X-API-Key": "ggpt_readonlykey"},
            cookies={settings.jwt_cookie_name: "some.jwt.value"},
        )
        assert await require_first_party(request) is None

    @pytest.mark.asyncio
    async def test_allows_bearer_even_with_stray_api_key_header(self):
        """A Bearer JWT takes precedence, so the request is first-party."""
        request = _request(
            headers={
                "X-API-Key": "ggpt_readonlykey",
                "Authorization": "Bearer some.jwt.value",
            },
        )
        assert await require_first_party(request) is None


async def _register(client, email: str, password: str = "TestPass1") -> uuid.UUID:
    """Register a diabetic user and return their id."""
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 201
    return uuid.UUID(resp.json()["id"])


class TestReadOnlyApiKeyOnSettings:
    """Endpoint tests: a real read-only API key is denied on settings routes."""

    @pytest.mark.asyncio
    async def test_read_only_key_denied_on_safety_limits_patch(
        self, client, db_session
    ):
        """A read:glucose key cannot mutate safety limits (was 200 before fix)."""
        email = f"cr01_patch_{uuid.uuid4().hex[:8]}@test.com"
        user_id = await _register(client, email)
        _, raw_key = await create_api_key(
            db_session, user_id, "read-only", ["read:glucose"]
        )
        await db_session.commit()

        resp = await client.patch(
            "/api/settings/safety-limits",
            json={"min_glucose_mgdl": 40},
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_read_only_key_denied_on_data_purge(self, client, db_session):
        """A read:glucose key cannot purge all user data."""
        email = f"cr01_purge_{uuid.uuid4().hex[:8]}@test.com"
        user_id = await _register(client, email)
        _, raw_key = await create_api_key(
            db_session, user_id, "read-only", ["read:glucose"]
        )
        await db_session.commit()

        resp = await client.post(
            "/api/settings/data-retention/purge",
            json={"confirmation_text": "DELETE"},
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_read_only_key_denied_on_settings_read(self, client, db_session):
        """Settings are first-party, so even reads are denied to API keys."""
        email = f"cr01_read_{uuid.uuid4().hex[:8]}@test.com"
        user_id = await _register(client, email)
        _, raw_key = await create_api_key(
            db_session, user_id, "read-only", ["read:glucose"]
        )
        await db_session.commit()

        resp = await client.get(
            "/api/settings/safety-limits",
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_same_key_still_authenticates_on_first_party_endpoint(
        self, client, db_session
    ):
        """The key is genuinely valid: it authenticates on /api/auth/me.

        This proves the 403 on settings comes from the first-party guard, not
        from the key being rejected as invalid.
        """
        email = f"cr01_me_{uuid.uuid4().hex[:8]}@test.com"
        user_id = await _register(client, email)
        _, raw_key = await create_api_key(
            db_session, user_id, "read-only", ["read:glucose"]
        )
        await db_session.commit()

        resp = await client.get("/api/auth/me", headers={"X-API-Key": raw_key})
        assert resp.status_code == 200
        assert resp.json()["email"] == email

    @pytest.mark.asyncio
    async def test_cookie_still_allowed_on_safety_limits_patch(self, client):
        """First-party cookie auth still mutates safety limits (control)."""
        email = f"cr01_cookie_{uuid.uuid4().hex[:8]}@test.com"
        password = "TestPass1"
        await _register(client, email, password)
        login = await client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        cookie = login.cookies.get(settings.jwt_cookie_name)

        resp = await client.patch(
            "/api/settings/safety-limits",
            json={"min_glucose_mgdl": 40},
            cookies={settings.jwt_cookie_name: cookie},
        )
        assert resp.status_code == 200
