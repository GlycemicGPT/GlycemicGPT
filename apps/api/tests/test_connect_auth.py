"""Tests for the CarePartner Connect token provider (mocked, no network)."""

import httpx
import pytest

from src.services.integrations.medtronic.connect_auth import (
    REGIONS,
    ConnectTokenError,
    ConnectTokenProvider,
    build_authorize_url,
    exchange_code_for_tokens,
    generate_pkce,
    get_region,
    refresh_access_token,
)

US = REGIONS["US"]


def _http(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- region lookup ---


def test_get_region_case_insensitive():
    assert get_region("us").key == "US"
    assert get_region("Eu").key == "EU"


def test_get_region_unknown_raises():
    with pytest.raises(ValueError, match="Unknown CarePartner region"):
        get_region("jp")


def test_eu_region_params_match_live_carepartner_config():
    # Pinned from the live SSO config at
    # https://carelink.minimed.eu/configs/v1/carepartner_auth0_ous_sso_config_v1.json
    # (Medtronic's own discovery -> Auth0SSOConfiguration). EU covers UK/GB,
    # the EU member states, AU, ZA, ... -- a single OUS tenant.
    eu = REGIONS["EU"]
    assert eu.auth_host == "carelink-login.minimed.eu"
    assert eu.client_id == "PeAhkbhQWlQRxJiQxWfcFBiGus1lxfe9"
    assert eu.audience == "carepartner.patient.ous"
    assert eu.cloud_host == "https://clcloud.minimed.eu"
    assert eu.redirect_uri == "com.medtronic.carepartner:/sso"


def test_us_region_params_match_live_carepartner_config():
    us = REGIONS["US"]
    assert us.auth_host == "carelink-login.minimed.com"
    assert us.client_id == "0FGoNwY0SP8ZmESYSfEOgMw03c58c1hk"
    assert us.audience == "carepartner.patient.us"
    assert us.cloud_host == "https://clcloud.minimed.com"


# --- refresh_access_token ---


async def test_refresh_posts_public_client_grant_and_returns_tokens():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "carelink-login.minimed.com"
        assert request.url.path == "/oauth/token"
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "expires_in": 10800,
                "refresh_token": "rotated-refresh",
                "token_type": "Bearer",
            },
        )

    async with _http(handler) as http:
        tok = await refresh_access_token(US, "old-refresh", client=http)

    assert captured["body"]["grant_type"] == "refresh_token"
    assert captured["body"]["client_id"] == US.client_id
    assert captured["body"]["refresh_token"] == "old-refresh"
    assert "client_secret" not in captured["body"]  # public/PKCE client
    assert tok.access_token == "new-access"
    assert tok.expires_in == 10800
    assert tok.refresh_token == "rotated-refresh"


async def test_refresh_falls_back_to_sent_token_when_not_rotated():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "a", "expires_in": 3600})

    async with _http(handler) as http:
        tok = await refresh_access_token(US, "still-valid", client=http)
    assert tok.refresh_token == "still-valid"


async def test_refresh_invalid_grant_raises_token_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "invalid_grant"})

    async with _http(handler) as http:
        with pytest.raises(ConnectTokenError, match="re-login required"):
            await refresh_access_token(US, "dead-refresh", client=http)


async def test_refresh_empty_token_raises():
    with pytest.raises(ConnectTokenError, match="re-login required"):
        await refresh_access_token(US, "")


async def test_refresh_missing_access_token_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"expires_in": 3600})

    async with _http(handler) as http:
        with pytest.raises(ConnectTokenError, match="missing access_token"):
            await refresh_access_token(US, "r", client=http)


# --- ConnectTokenProvider ---


async def test_provider_caches_until_near_expiry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200, json={"access_token": f"acc-{calls['n']}", "expires_in": 3600}
        )

    clock = {"t": 1000.0}
    async with _http(handler) as http:
        provider = ConnectTokenProvider(
            region=US, refresh_token="r", client=http, now=lambda: clock["t"]
        )
        assert await provider() == "acc-1"
        # Still well within validity -> cached, no second network call.
        clock["t"] += 100
        assert await provider() == "acc-1"
        assert calls["n"] == 1
        # Past expiry (minus skew) -> refresh again.
        clock["t"] += 3600
        assert await provider() == "acc-2"
        assert calls["n"] == 2


async def test_provider_invokes_on_rotate_with_new_refresh_token():
    rotated = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "acc",
                "expires_in": 3600,
                "refresh_token": "rotated-1",
            },
        )

    async def on_rotate(new_token: str) -> None:
        rotated.append(new_token)

    async with _http(handler) as http:
        provider = ConnectTokenProvider(
            region=US, refresh_token="orig", client=http, on_rotate=on_rotate
        )
        await provider()
    assert rotated == ["rotated-1"]
    assert provider.refresh_token == "rotated-1"


# --- PKCE: generate / authorize URL / code exchange ---


def test_generate_pkce_returns_distinct_verifier_and_s256_challenge():
    import base64
    import hashlib

    v1, c1 = generate_pkce()
    v2, _ = generate_pkce()
    assert v1 != v2  # random each call
    # challenge == base64url(sha256(verifier)) without padding.
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(v1.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert c1 == expected


def test_build_authorize_url_has_pkce_and_custom_redirect():
    from urllib.parse import parse_qs, urlparse

    url = build_authorize_url(US, code_challenge="chal", state="xyz")
    parsed = urlparse(url)
    assert parsed.netloc == "carelink-login.minimed.com"
    assert parsed.path == "/authorize"
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == [US.client_id]
    assert qs["redirect_uri"] == ["com.medtronic.carepartner:/sso"]
    assert qs["code_challenge"] == ["chal"]
    assert qs["code_challenge_method"] == ["S256"]
    assert qs["response_type"] == ["code"]
    assert qs["state"] == ["xyz"]
    assert qs["audience"] == [US.audience]


async def test_exchange_posts_authorization_code_grant():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        assert request.url.path == "/oauth/token"
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "access_token": "acc",
                "expires_in": 10800,
                "refresh_token": "the-refresh",
            },
        )

    async with _http(handler) as http:
        tok = await exchange_code_for_tokens(
            US, "auth-code", "verifier-123", client=http
        )

    assert captured["body"]["grant_type"] == "authorization_code"
    assert captured["body"]["code"] == "auth-code"
    assert captured["body"]["code_verifier"] == "verifier-123"
    assert captured["body"]["redirect_uri"] == "com.medtronic.carepartner:/sso"
    assert "client_secret" not in captured["body"]
    assert tok.refresh_token == "the-refresh"


async def test_exchange_rejected_code_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "invalid_grant"})

    async with _http(handler) as http:
        with pytest.raises(ConnectTokenError, match="re-login required"):
            await exchange_code_for_tokens(US, "bad", "v", client=http)


async def test_exchange_without_refresh_token_raises():
    # offline_access not granted -> no refresh token -> autonomous sync impossible.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "a", "expires_in": 3600})

    async with _http(handler) as http:
        with pytest.raises(ConnectTokenError, match="missing refresh_token"):
            await exchange_code_for_tokens(US, "code", "v", client=http)


async def test_provider_does_not_fire_on_rotate_when_unchanged():
    rotated = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "acc", "expires_in": 3600})

    async def on_rotate(new_token: str) -> None:
        rotated.append(new_token)

    async with _http(handler) as http:
        provider = ConnectTokenProvider(
            region=US, refresh_token="orig", client=http, on_rotate=on_rotate
        )
        await provider()
    assert rotated == []
    assert provider.refresh_token == "orig"
