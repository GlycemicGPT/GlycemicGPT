#!/usr/bin/env python3
"""Story 28.11: Automated auth flow & security penetration tests.

Runs 16 security tests against a live Docker stack to verify that
rate limiting, token handling, CSRF, CORS, security headers, and
input validation all work correctly at the HTTP level.

Usage:
    API_URL=http://localhost:8001 WEB_URL=http://localhost:3001 python test-auth-flows.py
"""

import base64
import json
import os
import subprocess
import sys
import time
import uuid

import httpx
from jose import jwt

API_URL = os.environ.get("API_URL", "http://localhost:8001")
WEB_URL = os.environ.get("WEB_URL", "http://localhost:3001")
# Test secret key must be supplied via env var (matches docker-compose.test.yml)
TEST_SECRET_KEY = os.environ.get("TEST_SECRET_KEY", "")
JWT_ALGORITHM = "HS256"
# Compose project name for redis-cli access
COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "glycemicgpt-test")

PASS_COUNT = 0
FAIL_COUNT = 0
SKIP_COUNT = 0


def log_pass(name: str) -> None:
    global PASS_COUNT
    PASS_COUNT += 1
    print(f"  [PASS] {name}")


def log_fail(name: str, reason: str = "") -> None:
    global FAIL_COUNT
    FAIL_COUNT += 1
    detail = f" -- {reason}" if reason else ""
    print(f"  [FAIL] {name}{detail}")


def log_skip(name: str, reason: str) -> None:
    global SKIP_COUNT
    SKIP_COUNT += 1
    print(f"  [SKIP] {name} -- {reason}")


def unique_email() -> str:
    return f"sectest_{uuid.uuid4().hex[:12]}@example.com"


TEST_PASSWORD = os.environ.get(
    "TEST_PASSWORD", f"SecTest-{uuid.uuid4().hex[:8]}!"
)


def register_user(client: httpx.Client, email: str) -> int:
    """Register a test user and return the status code."""
    resp = client.post(
        f"{API_URL}/api/auth/register",
        json={"email": email, "password": TEST_PASSWORD},
    )
    return resp.status_code


def login_user(client: httpx.Client, email: str) -> httpx.Response:
    """Web login and return the response (cookies are stored in client)."""
    return client.post(
        f"{API_URL}/api/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
    )


def get_csrf_token(client: httpx.Client) -> str:
    """Extract CSRF token from the client's cookie jar."""
    for cookie in client.cookies.jar:
        if cookie.name == "csrf_token":
            return cookie.value
    return ""


def flush_rate_limits() -> None:
    """Flush Redis DB 0 so rate limit counters reset for the next test group.

    Uses FLUSHDB (single database) rather than FLUSHALL to avoid nuking
    other Redis databases if they exist.
    """
    try:
        result = subprocess.run(
            [
                "docker", "compose",
                "-f", "docker-compose.yml",
                "-f", "docker-compose.test.yml",
                "exec", "-T", "redis", "redis-cli", "FLUSHDB",
            ],
            capture_output=True,
            timeout=5,
            env={**os.environ, "COMPOSE_PROJECT_NAME": COMPOSE_PROJECT},
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            print(f"  [WARN] Redis FLUSHDB failed (rc={result.returncode}): {stderr}")
    except Exception as exc:
        print(f"  [WARN] Redis FLUSHDB unavailable: {exc}")


# ---------------------------------------------------------------------------
# Test 1: Rate limit on /api/auth/login
# ---------------------------------------------------------------------------
def test_rate_limit_login() -> None:
    name = "Rate limit: login"
    got_429 = False
    with httpx.Client(timeout=10) as client:
        for _ in range(12):
            resp = client.post(
                f"{API_URL}/api/auth/login",
                json={"email": "nobody@example.com", "password": "wrong"},
            )
            if resp.status_code == 429:
                got_429 = True
                break
    if got_429:
        log_pass(name)
    else:
        log_fail(name, "no 429 after 12 rapid requests")


# ---------------------------------------------------------------------------
# Test 2: Rate limit on /api/auth/mobile/login
# ---------------------------------------------------------------------------
def test_rate_limit_mobile_login() -> None:
    name = "Rate limit: mobile login"
    got_429 = False
    with httpx.Client(timeout=10) as client:
        for _ in range(12):
            resp = client.post(
                f"{API_URL}/api/auth/mobile/login",
                json={"email": "nobody@example.com", "password": "wrong"},
            )
            if resp.status_code == 429:
                got_429 = True
                break
    if got_429:
        log_pass(name)
    else:
        log_fail(name, "no 429 after 12 rapid requests")


# ---------------------------------------------------------------------------
# Test 3: Rate limit on /api/auth/mobile/refresh
# ---------------------------------------------------------------------------
def test_rate_limit_refresh() -> None:
    name = "Rate limit: mobile refresh"
    got_429 = False
    with httpx.Client(timeout=10) as client:
        for _ in range(32):
            resp = client.post(
                f"{API_URL}/api/auth/mobile/refresh",
                json={"refresh_token": "bogus"},
            )
            if resp.status_code == 429:
                got_429 = True
                break
    if got_429:
        log_pass(name)
    else:
        log_fail(name, "no 429 after 32 rapid requests")


# ---------------------------------------------------------------------------
# Test 4: Token tampering -- wrong signing key
# ---------------------------------------------------------------------------
def test_token_tampering_wrong_key() -> None:
    name = "Token tampering: wrong key"
    payload = {
        "sub": str(uuid.uuid4()),
        "email": "hacker@example.com",
        "role": "diabetic",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
        "type": "access",
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, "wrong-secret", algorithm=JWT_ALGORITHM)  # nosemgrep: jwt-python-hardcoded-secret
    with httpx.Client(timeout=10) as client:
        resp = client.get(
            f"{API_URL}/api/auth/me",
            cookies={"glycemicgpt_session": token},
        )
    if resp.status_code == 401:
        log_pass(name)
    else:
        log_fail(name, f"expected 401, got {resp.status_code}")


# ---------------------------------------------------------------------------
# Test 5: Token tampering -- algorithm confusion (HS384 + alg:none)
# ---------------------------------------------------------------------------
def test_token_tampering_alg_confusion() -> None:
    name = "Token tampering: alg confusion"
    errors = []

    payload = {
        "sub": str(uuid.uuid4()),
        "email": "hacker@example.com",
        "role": "diabetic",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
        "type": "access",
        "jti": str(uuid.uuid4()),
    }

    # Sub-test A: HS384 with wrong key (different algorithm than expected HS256)
    token_384 = jwt.encode(payload, "wrong-secret", algorithm="HS384")  # nosemgrep: jwt-python-hardcoded-secret
    with httpx.Client(timeout=10) as client:
        resp = client.get(
            f"{API_URL}/api/auth/me",
            cookies={"glycemicgpt_session": token_384},
        )
    if resp.status_code != 401:
        errors.append(f"HS384: expected 401, got {resp.status_code}")

    # Sub-test B: alg:none attack -- craft an unsigned JWT
    # Header: {"alg": "none", "typ": "JWT"}, payload, empty signature
    header_b64 = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).rstrip(b"=").decode()
    token_none = f"{header_b64}.{payload_b64}."

    with httpx.Client(timeout=10) as client:
        resp = client.get(
            f"{API_URL}/api/auth/me",
            cookies={"glycemicgpt_session": token_none},
        )
    if resp.status_code != 401:
        errors.append(f"alg:none: expected 401, got {resp.status_code}")

    if errors:
        log_fail(name, "; ".join(errors))
    else:
        log_pass(name)


# ---------------------------------------------------------------------------
# Test 6: Cookie flags
# ---------------------------------------------------------------------------
def test_cookie_flags() -> None:
    name = "Cookie flags"
    email = unique_email()
    with httpx.Client(timeout=10) as client:
        register_user(client, email)
        resp = login_user(client, email)

    # Inspect raw Set-Cookie headers
    set_cookies = resp.headers.get_list("set-cookie")
    session_cookie_header = ""
    csrf_cookie_header = ""
    for sc in set_cookies:
        lower = sc.lower()
        if "glycemicgpt_session" in lower:
            session_cookie_header = lower
        elif "csrf_token" in lower:
            csrf_cookie_header = lower

    errors = []
    if not session_cookie_header:
        errors.append("no glycemicgpt_session cookie set")
    else:
        if "httponly" not in session_cookie_header:
            errors.append("session cookie missing HttpOnly")
        if "samesite=lax" not in session_cookie_header:
            errors.append("session cookie missing SameSite=Lax")
        if "path=/" not in session_cookie_header:
            errors.append("session cookie missing Path=/")

    if csrf_cookie_header:
        if "httponly" in csrf_cookie_header:
            errors.append("csrf_token cookie should NOT have HttpOnly")
    # csrf_token may not be set if the client already had one; not an error
    # NOTE: Secure flag not checked here because test env uses COOKIE_SECURE=false.
    # Production enforces Secure=true via the default config (config.py line 48).

    if errors:
        log_fail(name, "; ".join(errors))
    else:
        log_pass(name)


# ---------------------------------------------------------------------------
# Test 7: CSRF -- missing token
# ---------------------------------------------------------------------------
def test_csrf_missing_token() -> None:
    name = "CSRF: missing token"
    email = unique_email()
    with httpx.Client(timeout=10) as client:
        register_user(client, email)
        login_user(client, email)

        # Get the session cookie but don't send CSRF header
        session_val = None
        for cookie in client.cookies.jar:
            if cookie.name == "glycemicgpt_session":
                session_val = cookie.value
                break

        if not session_val:
            log_fail(name, "no session cookie after login")
            return

    # Use a fresh client with only the session cookie (no csrf_token cookie)
    with httpx.Client(timeout=10) as client2:
        resp = client2.post(
            f"{API_URL}/api/auth/logout",
            cookies={"glycemicgpt_session": session_val},
        )
    if resp.status_code == 403:
        log_pass(name)
    else:
        log_fail(name, f"expected 403, got {resp.status_code}")


# ---------------------------------------------------------------------------
# Test 8: CSRF -- wrong token
# ---------------------------------------------------------------------------
def test_csrf_wrong_token() -> None:
    name = "CSRF: wrong token"
    email = unique_email()
    with httpx.Client(timeout=10) as client:
        register_user(client, email)
        login_user(client, email)

        session_val = None
        csrf_val = None
        for cookie in client.cookies.jar:
            if cookie.name == "glycemicgpt_session":
                session_val = cookie.value
            elif cookie.name == "csrf_token":
                csrf_val = cookie.value

        if not session_val:
            log_fail(name, "no session cookie after login")
            return

    # Send a deliberately wrong CSRF token
    with httpx.Client(timeout=10) as client2:
        resp = client2.post(
            f"{API_URL}/api/auth/logout",
            cookies={
                "glycemicgpt_session": session_val,
                "csrf_token": csrf_val or "placeholder",
            },
            headers={"X-CSRF-Token": "completely-wrong-token"},
        )
    if resp.status_code == 403:
        log_pass(name)
    else:
        log_fail(name, f"expected 403, got {resp.status_code}")


# ---------------------------------------------------------------------------
# Test 9: CORS -- reject evil origin
# ---------------------------------------------------------------------------
def test_cors_reject_evil_origin() -> None:
    name = "CORS: reject evil origin"
    errors = []
    evil_origin = "http://evil.example.com"

    with httpx.Client(timeout=10) as client:
        # Preflight check
        resp_preflight = client.options(
            f"{API_URL}/api/auth/login",
            headers={
                "Origin": evil_origin,
                "Access-Control-Request-Method": "POST",
            },
        )
        acao = resp_preflight.headers.get("access-control-allow-origin", "")
        if "evil.example.com" in acao:
            errors.append(f"preflight reflected evil origin: {acao}")

        # Actual POST with evil origin
        resp_post = client.post(
            f"{API_URL}/api/auth/login",
            json={"email": "x@x.com", "password": "x"},
            headers={"Origin": evil_origin},
        )
        acao_post = resp_post.headers.get("access-control-allow-origin", "")
        if "evil.example.com" in acao_post:
            errors.append(f"POST reflected evil origin: {acao_post}")

        acac = resp_post.headers.get("access-control-allow-credentials", "")
        if acac.lower() == "true" and acao_post == "*":
            errors.append("credentials + wildcard origin is dangerous")

    if errors:
        log_fail(name, "; ".join(errors))
    else:
        log_pass(name)


# ---------------------------------------------------------------------------
# Test 10: Security headers on web frontend
# ---------------------------------------------------------------------------
def test_security_headers() -> None:
    name = "Security headers (web)"
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        resp = client.get(WEB_URL)

    errors = []
    headers = resp.headers

    xfo = headers.get("x-frame-options", "").upper()
    if xfo != "DENY":
        errors.append(f"X-Frame-Options: expected DENY, got '{xfo}'")

    xcto = headers.get("x-content-type-options", "").lower()
    if xcto != "nosniff":
        errors.append(f"X-Content-Type-Options: expected nosniff, got '{xcto}'")

    hsts = headers.get("strict-transport-security", "")
    if "max-age=" not in hsts:
        errors.append(f"HSTS missing or invalid: '{hsts}'")

    csp = headers.get("content-security-policy", "")
    if "frame-ancestors 'none'" not in csp:
        errors.append(f"CSP missing frame-ancestors 'none': '{csp[:80]}'")

    if errors:
        log_fail(name, "; ".join(errors))
    else:
        log_pass(name)


# ---------------------------------------------------------------------------
# Test 11: Token blacklist -- logout then reuse
# ---------------------------------------------------------------------------
def test_token_blacklist_logout_reuse() -> None:
    name = "Token blacklist: logout reuse"
    email = unique_email()
    with httpx.Client(timeout=10) as client:
        register_user(client, email)
        login_user(client, email)

        session_val = None
        csrf_val = None
        for cookie in client.cookies.jar:
            if cookie.name == "glycemicgpt_session":
                session_val = cookie.value
            elif cookie.name == "csrf_token":
                csrf_val = cookie.value

        if not session_val or not csrf_val:
            log_fail(name, "no session or csrf cookie after login")
            return

        # Logout with valid CSRF
        client.post(
            f"{API_URL}/api/auth/logout",
            headers={"X-CSRF-Token": csrf_val},
        )

    # Reuse the old session cookie
    with httpx.Client(timeout=10) as client2:
        resp = client2.get(
            f"{API_URL}/api/auth/me",
            cookies={"glycemicgpt_session": session_val},
        )
    if resp.status_code == 401:
        log_pass(name)
    else:
        log_fail(name, f"expected 401, got {resp.status_code}")


# ---------------------------------------------------------------------------
# Test 12: Refresh token replay
# ---------------------------------------------------------------------------
def test_refresh_token_replay() -> None:
    name = "Refresh token replay"
    email = unique_email()
    with httpx.Client(timeout=10) as client:
        register_user(client, email)

        # Mobile login to get refresh token
        resp = client.post(
            f"{API_URL}/api/auth/mobile/login",
            json={"email": email, "password": TEST_PASSWORD},
        )
        if resp.status_code != 200:
            log_fail(name, f"mobile login failed: {resp.status_code}")
            return

        data = resp.json()
        refresh_token = data["refresh_token"]

        # First refresh -- should succeed
        resp1 = client.post(
            f"{API_URL}/api/auth/mobile/refresh",
            json={"refresh_token": refresh_token},
        )
        if resp1.status_code != 200:
            log_fail(name, f"first refresh failed: {resp1.status_code}")
            return

        # Replay the same refresh token -- should fail
        resp2 = client.post(
            f"{API_URL}/api/auth/mobile/refresh",
            json={"refresh_token": refresh_token},
        )
    if resp2.status_code == 401:
        log_pass(name)
    else:
        log_fail(name, f"expected 401 on replay, got {resp2.status_code}")


# ---------------------------------------------------------------------------
# Test 13: Password change invalidates session
# ---------------------------------------------------------------------------
def test_password_change_invalidates_session() -> None:
    name = "Password change invalidates session"
    email = unique_email()
    new_password = f"NewSec-{uuid.uuid4().hex[:8]}!"
    with httpx.Client(timeout=10) as client:
        register_user(client, email)
        login_user(client, email)

        session_val = None
        csrf_val = None
        for cookie in client.cookies.jar:
            if cookie.name == "glycemicgpt_session":
                session_val = cookie.value
            elif cookie.name == "csrf_token":
                csrf_val = cookie.value

        if not session_val or not csrf_val:
            log_fail(name, "no session or csrf cookie after login")
            return

        # Change password
        resp = client.post(
            f"{API_URL}/api/auth/change-password",
            json={
                "current_password": TEST_PASSWORD,
                "new_password": new_password,
            },
            headers={"X-CSRF-Token": csrf_val},
        )
        if resp.status_code != 200:
            log_fail(name, f"change-password returned {resp.status_code}")
            return

    # Reuse the old session cookie
    with httpx.Client(timeout=10) as client2:
        resp = client2.get(
            f"{API_URL}/api/auth/me",
            cookies={"glycemicgpt_session": session_val},
        )
    if resp.status_code == 401:
        log_pass(name)
    else:
        log_fail(name, f"expected 401, got {resp.status_code}")


# ---------------------------------------------------------------------------
# Test 14: Email enumeration prevention
# ---------------------------------------------------------------------------
def test_email_enumeration_prevention() -> None:
    name = "Email enumeration prevention"
    email = unique_email()
    errors = []

    with httpx.Client(timeout=10) as client:
        # Part A: Registration -- duplicate should use generic message
        client.post(
            f"{API_URL}/api/auth/register",
            json={"email": email, "password": TEST_PASSWORD},
        )
        resp_dup = client.post(
            f"{API_URL}/api/auth/register",
            json={"email": email, "password": TEST_PASSWORD},
        )
        detail = resp_dup.json().get("detail", "").lower()
        if "already" in detail or "exists" in detail or "taken" in detail:
            errors.append(f"register leaks email: '{resp_dup.json().get('detail')}'")

        # Part B: Login -- existing vs nonexistent email should return same
        # error message (prevents enumeration via login endpoint)
        resp_valid_email = client.post(
            f"{API_URL}/api/auth/login",
            json={"email": email, "password": "WrongPass999!"},
        )
        resp_fake_email = client.post(
            f"{API_URL}/api/auth/login",
            json={"email": unique_email(), "password": "WrongPass999!"},
        )
        msg_valid = resp_valid_email.json().get("detail", "")
        msg_fake = resp_fake_email.json().get("detail", "")
        if msg_valid != msg_fake:
            errors.append(
                f"login error differs: existing='{msg_valid}' vs "
                f"nonexistent='{msg_fake}'"
            )

    if errors:
        log_fail(name, "; ".join(errors))
    else:
        log_pass(name)


# ---------------------------------------------------------------------------
# Test 15: Expired token rejection
# ---------------------------------------------------------------------------
def test_expired_token_rejection() -> None:
    name = "Expired token rejection"
    if not TEST_SECRET_KEY:
        log_skip(name, "TEST_SECRET_KEY env var not set; cannot forge token")
        return

    payload = {
        "sub": str(uuid.uuid4()),
        "email": "expired@example.com",
        "role": "diabetic",
        "exp": int(time.time()) - 3600,  # expired 1 hour ago
        "iat": int(time.time()) - 7200,
        "type": "access",
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, TEST_SECRET_KEY, algorithm=JWT_ALGORITHM)
    with httpx.Client(timeout=10) as client:
        resp = client.get(
            f"{API_URL}/api/auth/me",
            cookies={"glycemicgpt_session": token},
        )
    if resp.status_code == 401:
        log_pass(name)
    else:
        log_fail(name, f"expected 401, got {resp.status_code}")


def test_open_redirect_prevention() -> None:
    """Verify login redirect param rejects external URLs."""
    name = "Open redirect prevention"
    errors = []

    evil_targets = [
        "https://evil.com",
        "//evil.com",
        "https://evil.com/steal-creds",
        "/\\evil.com",
    ]

    with httpx.Client(timeout=10, follow_redirects=False) as client:
        for target in evil_targets:
            resp = client.get(f"{WEB_URL}/login?redirect={target}")
            # Check that no redirect header points to the evil domain
            location = resp.headers.get("location", "")
            body = resp.text if resp.status_code == 200 else ""
            if "evil.com" in location:
                errors.append(f"Location header contains evil.com for redirect={target}")
            if "evil.com" in body and "window.location" in body:
                errors.append(f"Response body redirects to evil.com for redirect={target}")

    if errors:
        log_fail(name, "; ".join(errors))
    else:
        log_pass(name)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
# Tests that require login (run first, before rate limits are exhausted)
AUTH_TESTS = [
    test_token_tampering_wrong_key,
    test_token_tampering_alg_confusion,
    test_cookie_flags,
    test_csrf_missing_token,
    test_csrf_wrong_token,
    test_cors_reject_evil_origin,
    test_security_headers,
    test_token_blacklist_logout_reuse,
    test_refresh_token_replay,
    test_password_change_invalidates_session,
    test_email_enumeration_prevention,
    test_expired_token_rejection,
    test_open_redirect_prevention,
]

# Rate limit tests (run last -- they intentionally exhaust quotas)
RATE_LIMIT_TESTS = [
    test_rate_limit_login,
    test_rate_limit_mobile_login,
    test_rate_limit_refresh,
]

ALL_TESTS = AUTH_TESTS + RATE_LIMIT_TESTS


def main() -> int:
    print(f"=== Auth Flow & Security Tests ({len(ALL_TESTS)} tests) ===")
    print(f"API: {API_URL}  |  Web: {WEB_URL}")
    print()

    # Flush rate limits to start clean
    flush_rate_limits()

    print("--- Auth & security tests ---")
    for test_fn in AUTH_TESTS:
        try:
            test_fn()
        except Exception as exc:
            log_fail(test_fn.__name__, f"exception: {exc}")

    # Flush again before rate limit tests
    flush_rate_limits()

    print()
    print("--- Rate limit tests ---")
    for test_fn in RATE_LIMIT_TESTS:
        try:
            test_fn()
        except Exception as exc:
            log_fail(test_fn.__name__, f"exception: {exc}")

    print()
    skip_msg = f", {SKIP_COUNT} skipped" if SKIP_COUNT else ""
    print(f"Results: {PASS_COUNT} passed, {FAIL_COUNT} failed{skip_msg}")

    return 1 if FAIL_COUNT > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
