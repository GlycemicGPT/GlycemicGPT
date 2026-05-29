"""Tests for the Medtronic Connect helper-distribution endpoints.

These endpoints (helper.sh, helper.ps1, helper-binary) are intentionally gated
by the SAME short-lived pair token used for the rest of the handshake -- they
have NO surface outside an active pairing window. The tests pin that behavior
plus the script-template substitution.
"""

import uuid

from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.core.token_blacklist import consume_token_once
from src.main import app
from src.services.integrations.medtronic.connect_pairing import (
    pairing_token_jti,
)

HELPER_SH = "/api/integrations/medtronic/connect/helper.sh"
HELPER_PS1 = "/api/integrations/medtronic/connect/helper.ps1"
HELPER_BIN = "/api/integrations/medtronic/connect/helper-binary"
PAIR = "/api/integrations/medtronic/connect/pair"
INSTALL = "/api/integrations/medtronic/connect/install"
INSTALL_SH = "/api/integrations/medtronic/connect/install/{handle}.sh"
INSTALL_PS1 = "/api/integrations/medtronic/connect/install/{handle}.ps1"


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True
    )


def _email() -> str:
    return f"connect_helper_{uuid.uuid4().hex[:8]}@example.com"


async def _login(client: AsyncClient) -> dict:
    email, pw = _email(), "SecurePass123"
    await client.post("/api/auth/register", json={"email": email, "password": pw})
    r = await client.post("/api/auth/login", json={"email": email, "password": pw})
    return {settings.jwt_cookie_name: r.cookies.get(settings.jwt_cookie_name)}


async def _pair(client: AsyncClient, cookies: dict) -> str:
    r = await client.post(PAIR, cookies=cookies)
    assert r.status_code == 200, r.text
    return r.json()["pairing_token"]


# --- gating: 404 by default (no surface to fingerprint) ---


async def test_helper_sh_404_without_pair_token():
    async with _client() as c:
        r = await c.get(HELPER_SH)
        assert r.status_code == 404


async def test_helper_ps1_404_without_pair_token():
    async with _client() as c:
        r = await c.get(HELPER_PS1)
        assert r.status_code == 404


async def test_helper_binary_404_without_pair_token():
    async with _client() as c:
        r = await c.get(HELPER_BIN, params={"os": "linux", "arch": "amd64"})
        assert r.status_code == 404


async def test_helper_404_on_garbage_token():
    async with _client() as c:
        for path in (HELPER_SH, HELPER_PS1):
            r = await c.get(path, params={"pair": "not-a-fernet-blob"})
            assert r.status_code == 404


async def test_helper_404_after_token_consumed():
    # Mint a pair token, mark it consumed in Redis (like a successful /exchange
    # would), then confirm the helper surface goes dark.
    async with _client() as c:
        cookies = await _login(c)
        pair_token = await _pair(c, cookies)
    jti = pairing_token_jti(pair_token)
    # Mark consumed using the same key namespace the router uses.
    assert await consume_token_once(f"medtronic_pair:{jti}", 900)
    async with _client() as c:
        r = await c.get(
            HELPER_SH,
            params={
                "pair": pair_token,
                "api": "http://test",
                "username": "u",
                "region": "US",
            },
        )
        assert r.status_code == 404


# --- helper.sh: rendering + substitution + escaping ---


async def test_helper_sh_renders_with_substituted_values():
    async with _client() as c:
        cookies = await _login(c)
        pair_token = await _pair(c, cookies)
    async with _client() as c:
        r = await c.get(
            HELPER_SH,
            params={
                "pair": pair_token,
                "api": "https://glycemicgpt.example.com",
                "username": "testuser",
                "region": "US",
            },
        )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/x-shellscript")
    body = r.text
    assert body.startswith("#!/bin/bash")
    assert "API='https://glycemicgpt.example.com'" in body
    assert f"PAIR='{pair_token}'" in body
    assert "USERNAME='testuser'" in body
    assert "REGION='US'" in body
    # Binary download carries the pair token in a header, never the URL.
    assert "helper-binary?os=$OS&arch=$ARCH" in body
    assert "helper-binary?os=$OS&arch=$ARCH&pair=" not in body
    assert '-H "X-Connect-Pair-Token: $PAIR"' in body
    # Caches must not serve a stale tokenised script.
    assert r.headers.get("cache-control") == "no-store"


async def test_helper_sh_shell_escapes_dangerous_username():
    async with _client() as c:
        cookies = await _login(c)
        pair_token = await _pair(c, cookies)
    # An attacker who controls the username field cannot break out of the
    # single-quoted bash literal even if they include single quotes themselves.
    evil = "evil'; rm -rf /; echo 'pwned"
    async with _client() as c:
        r = await c.get(
            HELPER_SH,
            params={
                "pair": pair_token,
                "api": "http://test",
                "username": evil,
                "region": "US",
            },
        )
    assert r.status_code == 200, r.text
    # The literal "rm -rf /" must NOT appear unquoted in the script.
    assert "USERNAME='evil'\\''; rm -rf /; echo '\\''pwned'" in r.text


async def test_helper_sh_404_on_invalid_region():
    async with _client() as c:
        cookies = await _login(c)
        pair_token = await _pair(c, cookies)
    async with _client() as c:
        r = await c.get(
            HELPER_SH,
            params={
                "pair": pair_token,
                "api": "http://test",
                "username": "u",
                "region": "JP",
            },
        )
        assert r.status_code == 404


async def test_helper_sh_404_on_invalid_api_scheme():
    async with _client() as c:
        cookies = await _login(c)
        pair_token = await _pair(c, cookies)
    async with _client() as c:
        for bad_api in ("javascript:alert(1)", "file:///etc/passwd", "ftp://x", ""):
            r = await c.get(
                HELPER_SH,
                params={
                    "pair": pair_token,
                    "api": bad_api,
                    "username": "u",
                    "region": "US",
                },
            )
            assert r.status_code == 404, f"expected 404 for api={bad_api!r}"


# --- helper.ps1: rendering + PowerShell escaping (doubled single-quotes) ---


async def test_helper_ps1_renders_with_powershell_quoting():
    async with _client() as c:
        cookies = await _login(c)
        pair_token = await _pair(c, cookies)
    evil = "evil'; Remove-Item C:\\ -Recurse"
    async with _client() as c:
        r = await c.get(
            HELPER_PS1,
            params={
                "pair": pair_token,
                "api": "https://my.example",
                "username": evil,
                "region": "EU",
            },
        )
    assert r.status_code == 200, r.text
    body = r.text
    # PowerShell escapes single-quote by doubling it inside a single-quoted string.
    assert "$USERNAME = 'evil''; Remove-Item C:\\ -Recurse'" in body
    assert "$API = 'https://my.example'" in body
    assert "$REGION = 'EU'" in body
    # Binary download carries the pair token in a header, never the URL.
    assert "helper-binary?os=$OS&arch=$ARCH" in body
    assert "-Headers @{ 'X-Connect-Pair-Token' = $PAIR }" in body


# --- helper-binary: gating + os/arch allowlist + missing-file 404 ---


async def test_helper_binary_404_on_unsupported_platform():
    async with _client() as c:
        cookies = await _login(c)
        pair_token = await _pair(c, cookies)
    async with _client() as c:
        for bad in [("linux", "386"), ("openbsd", "amd64"), ("", "")]:
            r = await c.get(
                HELPER_BIN,
                params={"os": bad[0], "arch": bad[1]},
                headers={"X-Connect-Pair-Token": pair_token},
            )
            assert r.status_code == 404, f"expected 404 for {bad}"


async def test_helper_binary_404_when_file_absent_in_dev(tmp_path, monkeypatch):
    # When the multi-stage Docker builder hasn't produced the binaries, the
    # endpoint just 404s, which is what we want. Point the dist root at a
    # guaranteed-empty temp dir so this is deterministic regardless of the
    # ambient filesystem -- the prod image bakes binaries into the real
    # _CONNECT_HELPER_DIST_ROOT, so relying on its absence is flaky.
    from src.routers import integrations as ri

    monkeypatch.setattr(ri, "_CONNECT_HELPER_DIST_ROOT", tmp_path / "empty-dist")

    async with _client() as c:
        cookies = await _login(c)
        pair_token = await _pair(c, cookies)
    async with _client() as c:
        r = await c.get(
            HELPER_BIN,
            params={"os": "linux", "arch": "amd64"},
            headers={"X-Connect-Pair-Token": pair_token},
        )
        assert r.status_code == 404


async def test_helper_binary_serves_when_file_present(tmp_path, monkeypatch):
    """When the multi-stage Dockerfile produced the binary, the endpoint streams it."""
    from src.routers import integrations as ri

    # Plant a fake binary in a temp dist root and point the endpoint at it.
    dist = tmp_path / "dist"
    (dist / "linux" / "amd64").mkdir(parents=True)
    fake = dist / "linux" / "amd64" / "glycemicgpt-connect"
    fake.write_bytes(b"FAKE_GO_BINARY")
    monkeypatch.setattr(ri, "_CONNECT_HELPER_DIST_ROOT", dist)

    async with _client() as c:
        cookies = await _login(c)
        pair_token = await _pair(c, cookies)
    async with _client() as c:
        r = await c.get(
            HELPER_BIN,
            params={"os": "linux", "arch": "amd64"},
            headers={"X-Connect-Pair-Token": pair_token},
        )
    assert r.status_code == 200, r.text
    assert r.content == b"FAKE_GO_BINARY"
    assert r.headers["content-type"] == "application/octet-stream"
    assert "glycemicgpt-connect" in r.headers.get("content-disposition", "")


# --- short-handle install endpoints ---


async def _install(
    client: AsyncClient,
    cookies: dict,
    *,
    api: str = "https://glycemicgpt.example.com",
    username: str = "testuser",
    region: str = "US",
) -> dict:
    r = await client.post(
        INSTALL,
        cookies=cookies,
        json={"api_url": api, "username": username, "region": region},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_install_requires_auth():
    async with _client() as c:
        r = await c.post(
            INSTALL,
            json={"api_url": "https://x", "username": "u", "region": "US"},
        )
        assert r.status_code == 401


async def test_install_rejects_bad_inputs():
    async with _client() as c:
        cookies = await _login(c)
        for body in (
            {"api_url": "javascript:alert(1)", "username": "u", "region": "US"},
            {"api_url": "https://x", "username": "", "region": "US"},
            {"api_url": "https://x", "username": "u", "region": "JP"},
        ):
            r = await c.post(INSTALL, cookies=cookies, json=body)
            assert r.status_code == 422, (body, r.text)


async def test_install_returns_short_handle_and_pair_token():
    async with _client() as c:
        cookies = await _login(c)
        data = await _install(c, cookies)
    assert isinstance(data["handle"], str)
    assert len(data["handle"]) == 16  # 8 random bytes -> 16 hex chars
    assert all(ch in "0123456789abcdef" for ch in data["handle"])
    # The pair token must round-trip back so the in-page Python-CLI advanced
    # fallback can still build `--pair <token>` without a second backend call.
    assert isinstance(data["pairing_token"], str)
    assert len(data["pairing_token"]) > 100  # Fernet tokens are ~272 chars


async def test_install_sh_renders_bundle_values():
    async with _client() as c:
        cookies = await _login(c)
        data = await _install(
            c, cookies, api="https://glycemicgpt.example.com", username="u@x.test"
        )
    async with _client() as c:
        r = await c.get(INSTALL_SH.format(handle=data["handle"]))
    assert r.status_code == 200, r.text
    body = r.text
    assert body.startswith("#!/bin/bash")
    assert "API='https://glycemicgpt.example.com'" in body
    assert f"PAIR='{data['pairing_token']}'" in body
    assert "USERNAME='u@x.test'" in body
    assert "REGION='US'" in body
    assert r.headers.get("cache-control") == "no-store"


async def test_install_ps1_renders_bundle_values_with_ps_quoting():
    evil = "evil'; Remove-Item C:\\"
    async with _client() as c:
        cookies = await _login(c)
        data = await _install(
            c, cookies, api="https://my.example", username=evil, region="EU"
        )
    async with _client() as c:
        r = await c.get(INSTALL_PS1.format(handle=data["handle"]))
    assert r.status_code == 200, r.text
    body = r.text
    assert "$API = 'https://my.example'" in body
    assert "$REGION = 'EU'" in body
    # PowerShell single-quote escape: ' -> ''
    assert "$USERNAME = 'evil''; Remove-Item C:\\'" in body


async def test_install_sh_404_on_unknown_handle():
    async with _client() as c:
        r = await c.get(INSTALL_SH.format(handle="deadbeefcafef00d"))
        assert r.status_code == 404


async def test_install_sh_404_after_pair_token_consumed():
    async with _client() as c:
        cookies = await _login(c)
        data = await _install(c, cookies)
    # Simulate /exchange consuming the underlying pair token.
    jti = pairing_token_jti(data["pairing_token"])
    assert await consume_token_once(f"medtronic_pair:{jti}", 900)
    async with _client() as c:
        r = await c.get(INSTALL_SH.format(handle=data["handle"]))
        assert r.status_code == 404


async def test_install_sh_shell_escapes_dangerous_username():
    evil = "evil'; rm -rf /; echo 'pwned"
    async with _client() as c:
        cookies = await _login(c)
        data = await _install(c, cookies, username=evil)
    async with _client() as c:
        r = await c.get(INSTALL_SH.format(handle=data["handle"]))
    assert r.status_code == 200, r.text
    assert "USERNAME='evil'\\''; rm -rf /; echo '\\''pwned'" in r.text
