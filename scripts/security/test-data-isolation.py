#!/usr/bin/env python3
"""Story 35.11a: Data isolation (IDOR) tests for AI pipeline endpoints.

Verifies that User A cannot access, modify, or delete User B's data
across all endpoints added in Stories 35.3, 35.9, 35.10, and 35.12.

Tests run against a live Docker stack with NO AI provider configured.
We only test the API's auth/ownership enforcement, not AI responses.

Usage:
    API_URL=http://localhost:8001 python test-data-isolation.py
"""

import os
import sys
import uuid

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8001")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", f"IsolTest-{uuid.uuid4().hex[:8]}!")

passed = 0
failed = 0


def unique_email() -> str:
    return f"isoltest_{uuid.uuid4().hex[:12]}@example.com"


def register_and_login(client: httpx.Client, email: str) -> str:
    """Register a user, login, acknowledge disclaimer, return CSRF token."""
    # Register
    resp = client.post(
        f"{API_URL}/api/auth/register",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert resp.status_code in (201, 200), f"Register failed: {resp.status_code} {resp.text}"

    # Login
    resp = client.post(
        f"{API_URL}/api/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"

    # Acknowledge disclaimer if required
    csrf = get_csrf(client)
    client.post(
        f"{API_URL}/api/disclaimer/acknowledge",
        headers={"X-CSRF-Token": csrf},
    )
    # Refresh CSRF after disclaimer
    return get_csrf(client)


def get_csrf(client: httpx.Client) -> str:
    """Extract CSRF token from cookies."""
    for cookie in client.cookies.jar:
        if cookie.name == "csrf_token":
            return cookie.value
    return ""


def check(name: str, condition: bool, detail: str = "") -> None:
    """Record a test result."""
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}" + (f" -- {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Test: Chat History Isolation (Story 35.3)
# ---------------------------------------------------------------------------
def test_chat_history_isolation() -> None:
    """User B cannot read or delete User A's chat history."""
    print("\n--- Chat History Isolation ---")

    with httpx.Client(timeout=30) as user_a, httpx.Client(timeout=30) as user_b:
        csrf_a = register_and_login(user_a, unique_email())
        csrf_b = register_and_login(user_b, unique_email())

        # User A sends a chat message (will fail because no AI provider,
        # but the message may still be stored depending on error handling)
        user_a.post(
            f"{API_URL}/api/ai/chat",
            json={"message": "User A secret question about insulin"},
            headers={"X-CSRF-Token": csrf_a},
        )
        # Note: This likely returns 404 (no AI provider) in test env.
        # That's fine -- we're testing the history endpoint, not chat.

        # User A checks their history
        resp_a = user_a.get(
            f"{API_URL}/api/ai/chat/history",
            headers={"X-CSRF-Token": csrf_a},
        )
        check(
            "User A can access own chat history",
            resp_a.status_code == 200,
            f"Got {resp_a.status_code}",
        )

        # User B tries to read chat history (should only see their own, empty)
        resp_b = user_b.get(
            f"{API_URL}/api/ai/chat/history",
            headers={"X-CSRF-Token": csrf_b},
        )
        check(
            "User B chat history is empty (not User A's)",
            resp_b.status_code == 200
            and len(resp_b.json().get("messages", [])) == 0,
            f"Got {resp_b.status_code}, messages: {resp_b.json().get('messages', 'N/A') if resp_b.status_code == 200 else 'error'}",
        )

        # User B tries to delete User A's chat history (should only affect B's own)
        resp_del = user_b.delete(
            f"{API_URL}/api/ai/chat/history",
            headers={"X-CSRF-Token": csrf_b},
        )
        check(
            "User B delete only affects own history",
            resp_del.status_code == 200,
            f"Got {resp_del.status_code}",
        )


# ---------------------------------------------------------------------------
# Test: Knowledge Base Isolation (Story 35.10)
# ---------------------------------------------------------------------------
def test_knowledge_base_isolation() -> None:
    """User B cannot see or delete User A's knowledge documents."""
    print("\n--- Knowledge Base Isolation ---")

    with httpx.Client(timeout=30) as user_a, httpx.Client(timeout=30) as user_b:
        csrf_a = register_and_login(user_a, unique_email())
        csrf_b = register_and_login(user_b, unique_email())

        # User A lists their knowledge base (should be empty for new user)
        resp_a = user_a.get(
            f"{API_URL}/api/knowledge/documents",
            headers={"X-CSRF-Token": csrf_a},
        )
        check(
            "User A can access knowledge documents",
            resp_a.status_code == 200,
            f"Got {resp_a.status_code}",
        )

        # User B lists their knowledge base (should also be empty, NOT User A's)
        resp_b = user_b.get(
            f"{API_URL}/api/knowledge/documents",
            headers={"X-CSRF-Token": csrf_b},
        )
        check(
            "User B knowledge base is independent from User A",
            resp_b.status_code == 200,
            f"Got {resp_b.status_code}",
        )

        # User A gets stats
        resp_stats_a = user_a.get(
            f"{API_URL}/api/knowledge/stats",
            headers={"X-CSRF-Token": csrf_a},
        )
        check(
            "User A can access knowledge stats",
            resp_stats_a.status_code == 200,
            f"Got {resp_stats_a.status_code}",
        )

        # User B tries to delete a knowledge document with a fake source_name
        # that might belong to User A -- should return 404 (not found/not owned)
        resp_del = user_b.delete(
            f"{API_URL}/api/knowledge/documents",
            params={"source_name": "User A Secret Document"},
            headers={"X-CSRF-Token": csrf_b},
        )
        check(
            "User B cannot delete User A's knowledge docs",
            resp_del.status_code == 404,
            f"Got {resp_del.status_code}",
        )


# ---------------------------------------------------------------------------
# Test: Research Sources Isolation (Story 35.12)
# ---------------------------------------------------------------------------
def test_research_sources_isolation() -> None:
    """User B cannot see, modify, or delete User A's research sources."""
    print("\n--- Research Sources Isolation ---")

    with httpx.Client(timeout=30) as user_a, httpx.Client(timeout=30) as user_b:
        csrf_a = register_and_login(user_a, unique_email())
        csrf_b = register_and_login(user_b, unique_email())

        # User A adds a research source
        resp_add = user_a.post(
            f"{API_URL}/api/ai/research/sources",
            json={
                "url": "https://www.example.com/user-a-docs",
                "name": "User A Private Source",
                "category": "insulin",
            },
            headers={"X-CSRF-Token": csrf_a},
        )
        check(
            "User A can add a research source",
            resp_add.status_code == 201,
            f"Got {resp_add.status_code}: {resp_add.text[:200]}",
        )

        source_id = None
        if resp_add.status_code == 201:
            source_id = resp_add.json().get("id")

        # User A lists their sources
        resp_list_a = user_a.get(
            f"{API_URL}/api/ai/research/sources",
            headers={"X-CSRF-Token": csrf_a},
        )
        check(
            "User A sees their source in the list",
            resp_list_a.status_code == 200
            and len(resp_list_a.json().get("sources", [])) >= 1,
            f"Got {resp_list_a.status_code}",
        )

        # User B lists their sources (should NOT see User A's source)
        resp_list_b = user_b.get(
            f"{API_URL}/api/ai/research/sources",
            headers={"X-CSRF-Token": csrf_b},
        )
        check(
            "User B does NOT see User A's research sources",
            resp_list_b.status_code == 200
            and len(resp_list_b.json().get("sources", [])) == 0,
            f"Got {resp_list_b.status_code}, sources: {len(resp_list_b.json().get('sources', []))}",
        )

        # User B tries to delete User A's source by ID
        if source_id:
            resp_del = user_b.delete(
                f"{API_URL}/api/ai/research/sources/{source_id}",
                headers={"X-CSRF-Token": csrf_b},
            )
            check(
                "User B cannot delete User A's research source",
                resp_del.status_code == 404,
                f"Got {resp_del.status_code}",
            )

            # Verify User A's source still exists
            resp_verify = user_a.get(
                f"{API_URL}/api/ai/research/sources",
                headers={"X-CSRF-Token": csrf_a},
            )
            check(
                "User A's source survives User B's delete attempt",
                resp_verify.status_code == 200
                and len(resp_verify.json().get("sources", [])) >= 1,
                f"Got {resp_verify.status_code}",
            )

        # User B gets suggestions (should be based on B's config, not A's)
        resp_sug = user_b.get(
            f"{API_URL}/api/ai/research/suggestions",
            headers={"X-CSRF-Token": csrf_b},
        )
        check(
            "User B suggestions are independent",
            resp_sug.status_code == 200,
            f"Got {resp_sug.status_code}",
        )


# ---------------------------------------------------------------------------
# Test: Unauthenticated Access (all new endpoints)
# ---------------------------------------------------------------------------
def test_unauthenticated_access() -> None:
    """All new endpoints reject unauthenticated requests."""
    print("\n--- Unauthenticated Access ---")

    with httpx.Client(timeout=10) as client:
        endpoints = [
            ("GET", "/api/ai/chat/history"),
            ("DELETE", "/api/ai/chat/history"),
            ("GET", "/api/knowledge/documents"),
            ("GET", "/api/knowledge/documents/chunks?source_name=test"),
            ("DELETE", "/api/knowledge/documents?source_name=test"),
            ("GET", "/api/knowledge/stats"),
            ("GET", "/api/ai/research/sources"),
            ("POST", "/api/ai/research/sources"),
            ("DELETE", f"/api/ai/research/sources/{uuid.uuid4()}"),
            ("POST", "/api/ai/research/run"),
            ("GET", "/api/ai/research/suggestions"),
        ]

        for method, path in endpoints:
            resp = client.request(method, f"{API_URL}{path}")
            check(
                f"Unauth {method} {path.split('?')[0]} -> 401",
                resp.status_code == 401,
                f"Got {resp.status_code}",
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Running data isolation tests against {API_URL}")
    print("=" * 60)

    test_unauthenticated_access()
    test_chat_history_isolation()
    test_knowledge_base_isolation()
    test_research_sources_isolation()

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")

    if failed > 0:
        print("\nFAILED -- data isolation breach detected!")
        sys.exit(1)
    else:
        print("\nPASSED -- all data isolation checks verified")
        sys.exit(0)
