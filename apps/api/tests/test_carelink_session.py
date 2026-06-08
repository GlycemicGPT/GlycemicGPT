"""Tests for CareLinkSession (self-refreshing bearer), mocked -- no network."""

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
import pytest

from src.services.integrations.medtronic.client import CareLinkAuthError
from src.services.integrations.medtronic.session import CareLinkSession

API_HOST = "carelink.minimed.com"


def _valid_to_str(delta_minutes: int) -> str:
    """A quoted Java-style c_token_valid_to value, now + delta."""
    t = datetime.now(UTC) + timedelta(minutes=delta_minutes)
    return '"' + t.strftime("%a %b %d %H:%M:%S UTC %Y") + '"'


def _bundle(token: str, valid_to: str) -> list[dict]:
    return [
        {"name": "auth_tmp_token", "value": token, "domain": API_HOST, "path": "/"},
        {
            "name": "c_token_valid_to",
            "value": valid_to,
            "domain": API_HOST,
            "path": "/",
        },
        {
            "name": "auth0",
            "value": "sess",
            "domain": "carelink-login.minimed.com",
            "path": "/",
        },
    ]


def _session(bundle: list[dict], handler) -> CareLinkSession:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return CareLinkSession(cookies=bundle, http=http)


async def test_rejects_untrusted_base_url():
    with pytest.raises(ValueError, match="untrusted host"):
        CareLinkSession(cookies=[], base_url="https://evil.example.com")


async def test_bearer_returns_token_without_refresh_when_valid():
    calls = {"sso": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/patient/sso/auth":
            calls["sso"] += 1
        return httpx.Response(200)

    async with _session(_bundle("TOK1", _valid_to_str(30)), handler) as s:
        assert s.needs_refresh() is False
        assert await s.bearer() == "TOK1"
        assert calls["sso"] == 0  # did not refresh a still-valid token


async def test_expired_token_triggers_refresh_to_new_token():
    new_valid = quote(_valid_to_str(45))  # url-encoded for the Set-Cookie value

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/patient/sso/auth":
            return httpx.Response(
                200,
                headers=[
                    ("set-cookie", f"auth_tmp_token=TOK2; Domain={API_HOST}; Path=/"),
                    (
                        "set-cookie",
                        f"c_token_valid_to={new_valid}; Domain={API_HOST}; Path=/",
                    ),
                ],
            )
        return httpx.Response(200)

    async with _session(_bundle("TOK1", _valid_to_str(-5)), handler) as s:
        assert s.needs_refresh() is True
        assert await s.bearer() == "TOK2"  # refreshed
        assert s.needs_refresh() is False  # new validity persisted


async def test_refresh_bounced_to_login_raises_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/patient/sso/auth":
            return httpx.Response(
                302, headers={"location": f"https://{API_HOST}/app/login"}
            )
        if request.url.path == "/app/login":
            return httpx.Response(200)
        return httpx.Response(404)

    async with _session(_bundle("TOK1", _valid_to_str(-5)), handler) as s:
        with pytest.raises(CareLinkAuthError, match="reconnect"):
            await s.bearer()


async def test_missing_token_raises():
    async with _session(
        [{"name": "c_token_valid_to", "value": _valid_to_str(30), "domain": API_HOST}],
        lambda r: httpx.Response(200),
    ) as s:
        with pytest.raises(CareLinkAuthError, match="No auth_tmp_token"):
            await s.bearer()


async def test_export_cookies_roundtrips_token():
    async with _session(
        _bundle("TOK1", _valid_to_str(30)), lambda r: httpx.Response(200)
    ) as s:
        names = {c["name"]: c["value"] for c in s.export_cookies()}
        assert names["auth_tmp_token"] == "TOK1"
        assert "auth0" in names  # the Auth0 session cookie is preserved


async def test_refresh_on_valid_session_keeps_token():
    """Regression (caught in live E2E): when the session is still valid,
    /patient/sso/auth is a no-op and issues no new token. refresh() must keep
    the existing token rather than dropping it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)  # no Set-Cookie -> no re-issue

    async with _session(_bundle("TOK1", _valid_to_str(30)), handler) as s:
        await s.refresh()  # forced no-op refresh
        assert await s.bearer() == "TOK1"  # token preserved, not lost
