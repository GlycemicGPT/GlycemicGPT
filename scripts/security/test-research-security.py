#!/usr/bin/env python3
"""Story 35.11a: Research pipeline security tests.

Tests SSRF prevention, rate limiting, source limits, and input validation
on the AI Research Pipeline endpoints (Story 35.12).

Runs against a live Docker stack. No AI provider needed -- tests validate
the API's security enforcement, not AI responses.

Usage:
    API_URL=http://localhost:8001 python test-research-security.py
"""

import os
import sys
import time
import uuid

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8001")
TEST_PASSWORD = "ResearchSec-2026!"

passed = 0
failed = 0


def unique_email() -> str:
    return f"rsrchsec_{uuid.uuid4().hex[:12]}@example.com"


def register_and_login(client: httpx.Client, email: str) -> str:
    """Register, login, acknowledge disclaimer, return CSRF token."""
    client.post(
        f"{API_URL}/api/auth/register",
        json={"email": email, "password": TEST_PASSWORD},
    )
    client.post(
        f"{API_URL}/api/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
    )
    csrf = get_csrf(client)
    client.post(
        f"{API_URL}/api/disclaimer/acknowledge",
        headers={"X-CSRF-Token": csrf},
    )
    return get_csrf(client)


def get_csrf(client: httpx.Client) -> str:
    for cookie in client.cookies.jar:
        if cookie.name == "csrf_token":
            return cookie.value
    return ""


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}" + (f" -- {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# SSRF Prevention Tests
# ---------------------------------------------------------------------------
def test_ssrf_prevention() -> None:
    """Research source URLs targeting private/internal addresses must be rejected."""
    print("\n--- SSRF Prevention ---")

    with httpx.Client(timeout=30) as client:
        csrf = register_and_login(client, unique_email())

        ssrf_urls = [
            ("Localhost", "https://127.0.0.1/api"),
            ("Localhost hostname", "https://localhost/api"),
            ("Private 10.x", "https://10.0.0.1/api"),
            ("Private 172.16.x", "https://172.16.0.1/api"),
            ("Private 192.168.x", "https://192.168.1.1/api"),
            ("AWS metadata", "https://169.254.169.254/latest/meta-data/"),
            ("GCP metadata", "https://metadata.google.internal/computeMetadata/"),
            ("IPv6 loopback", "https://[::1]/api"),
            ("HTTP (not HTTPS)", "http://www.example.com/docs"),
        ]

        for label, url in ssrf_urls:
            resp = client.post(
                f"{API_URL}/api/ai/research/sources",
                json={"url": url, "name": f"SSRF Test - {label}"},
                headers={"X-CSRF-Token": csrf},
            )
            check(
                f"SSRF blocked: {label}",
                resp.status_code == 400 or resp.status_code == 422,
                f"Got {resp.status_code}: {resp.text[:100]}",
            )


# ---------------------------------------------------------------------------
# Source Limit Tests
# ---------------------------------------------------------------------------
def test_source_limits() -> None:
    """Cannot exceed max sources per user."""
    print("\n--- Source Limits ---")

    with httpx.Client(timeout=30) as client:
        csrf = register_and_login(client, unique_email())

        # Add 10 sources (the max)
        for i in range(10):
            resp = client.post(
                f"{API_URL}/api/ai/research/sources",
                json={
                    "url": f"https://www.example{i}.com/docs",
                    "name": f"Source {i}",
                },
                headers={"X-CSRF-Token": csrf},
            )
            if i < 10:
                check(
                    f"Source {i+1}/10 added",
                    resp.status_code == 201,
                    f"Got {resp.status_code}",
                )

        # 11th should fail
        resp = client.post(
            f"{API_URL}/api/ai/research/sources",
            json={
                "url": "https://www.example11.com/docs",
                "name": "Source 11 (should fail)",
            },
            headers={"X-CSRF-Token": csrf},
        )
        check(
            "11th source rejected (limit 10)",
            resp.status_code == 400,
            f"Got {resp.status_code}",
        )


# ---------------------------------------------------------------------------
# Duplicate URL Prevention
# ---------------------------------------------------------------------------
def test_duplicate_url() -> None:
    """Cannot add the same URL twice."""
    print("\n--- Duplicate URL Prevention ---")

    with httpx.Client(timeout=30) as client:
        csrf = register_and_login(client, unique_email())

        url = "https://www.example.com/unique-test-doc"

        # First add
        resp1 = client.post(
            f"{API_URL}/api/ai/research/sources",
            json={"url": url, "name": "First Add"},
            headers={"X-CSRF-Token": csrf},
        )
        check("First URL add succeeds", resp1.status_code == 201, f"Got {resp1.status_code}")

        # Duplicate
        resp2 = client.post(
            f"{API_URL}/api/ai/research/sources",
            json={"url": url, "name": "Duplicate Add"},
            headers={"X-CSRF-Token": csrf},
        )
        check("Duplicate URL rejected", resp2.status_code == 400, f"Got {resp2.status_code}")


# ---------------------------------------------------------------------------
# Rate Limiting on Research Trigger
# ---------------------------------------------------------------------------
def test_rate_limiting() -> None:
    """POST /api/ai/research/run is rate-limited to 2/hour."""
    print("\n--- Rate Limiting ---")

    with httpx.Client(timeout=60) as client:
        csrf = register_and_login(client, unique_email())

        # First two calls should succeed (or return error because no AI, but not 429)
        for i in range(2):
            resp = client.post(
                f"{API_URL}/api/ai/research/run",
                headers={"X-CSRF-Token": csrf},
            )
            check(
                f"Research run {i+1}/2 not rate-limited",
                resp.status_code != 429,
                f"Got {resp.status_code}",
            )

        # Third call should be rate-limited
        resp = client.post(
            f"{API_URL}/api/ai/research/run",
            headers={"X-CSRF-Token": csrf},
        )
        check(
            "Research run 3/2 rate-limited (429)",
            resp.status_code == 429,
            f"Got {resp.status_code}",
        )


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------
def test_input_validation() -> None:
    """Research source creation validates inputs."""
    print("\n--- Input Validation ---")

    with httpx.Client(timeout=30) as client:
        csrf = register_and_login(client, unique_email())

        # Missing URL
        resp = client.post(
            f"{API_URL}/api/ai/research/sources",
            json={"name": "No URL"},
            headers={"X-CSRF-Token": csrf},
        )
        check("Missing URL rejected", resp.status_code == 422, f"Got {resp.status_code}")

        # Missing name
        resp = client.post(
            f"{API_URL}/api/ai/research/sources",
            json={"url": "https://www.example.com/docs"},
            headers={"X-CSRF-Token": csrf},
        )
        check("Missing name rejected", resp.status_code == 422, f"Got {resp.status_code}")

        # URL too short
        resp = client.post(
            f"{API_URL}/api/ai/research/sources",
            json={"url": "https://x", "name": "Short URL"},
            headers={"X-CSRF-Token": csrf},
        )
        check(
            "URL too short rejected",
            resp.status_code in (400, 422),
            f"Got {resp.status_code}",
        )

        # Extremely long URL (>2000 chars)
        resp = client.post(
            f"{API_URL}/api/ai/research/sources",
            json={"url": "https://www.example.com/" + "a" * 2000, "name": "Long URL"},
            headers={"X-CSRF-Token": csrf},
        )
        check(
            "Oversized URL rejected",
            resp.status_code in (400, 422),
            f"Got {resp.status_code}",
        )


# ---------------------------------------------------------------------------
# CSRF on State-Changing Endpoints
# ---------------------------------------------------------------------------
def test_csrf_enforcement() -> None:
    """POST and DELETE endpoints require CSRF token."""
    print("\n--- CSRF Enforcement ---")

    with httpx.Client(timeout=30) as client:
        csrf = register_and_login(client, unique_email())

        # POST without CSRF token
        resp = client.post(
            f"{API_URL}/api/ai/research/sources",
            json={
                "url": "https://www.example.com/no-csrf",
                "name": "No CSRF",
            },
            # Intentionally omit X-CSRF-Token header
        )
        check(
            "POST research source without CSRF -> 403",
            resp.status_code == 403,
            f"Got {resp.status_code}",
        )

        # DELETE without CSRF token
        resp = client.delete(
            f"{API_URL}/api/ai/research/sources/{uuid.uuid4()}",
            # Intentionally omit X-CSRF-Token header
        )
        check(
            "DELETE research source without CSRF -> 403",
            resp.status_code == 403,
            f"Got {resp.status_code}",
        )

        # DELETE knowledge without CSRF
        resp = client.delete(
            f"{API_URL}/api/knowledge/documents",
            params={"source_name": "test"},
            # No CSRF
        )
        check(
            "DELETE knowledge without CSRF -> 403",
            resp.status_code == 403,
            f"Got {resp.status_code}",
        )

        # DELETE chat history without CSRF
        resp = client.delete(
            f"{API_URL}/api/ai/chat/history",
            # No CSRF
        )
        check(
            "DELETE chat history without CSRF -> 403",
            resp.status_code == 403,
            f"Got {resp.status_code}",
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Running research security tests against {API_URL}")
    print("=" * 60)

    test_ssrf_prevention()
    test_source_limits()
    test_duplicate_url()
    test_rate_limiting()
    test_input_validation()
    test_csrf_enforcement()

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")

    if failed > 0:
        print("\nFAILED -- security issue detected!")
        sys.exit(1)
    else:
        print("\nPASSED -- all research security checks verified")
        sys.exit(0)
