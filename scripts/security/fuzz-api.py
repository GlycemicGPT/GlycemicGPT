#!/usr/bin/env python3
"""Story 28.11: OpenAPI-driven endpoint fuzzer.

Fetches /openapi.json from the live API, iterates endpoints, and sends
malicious payloads.  Asserts that no endpoint returns HTTP 500.

Supports authenticated and unauthenticated modes:
  - authenticated: fuzzes with a valid session (default behavior)
  - unauthenticated: fuzzes without cookies (attacker perspective)
  - both: runs both passes sequentially

Usage:
    python fuzz-api.py http://localhost:8001
    python fuzz-api.py http://localhost:8001 --mode both
"""

import argparse
import os
import re
import sys
import uuid

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8001")

# Endpoints to skip (docs, health, SSE streams)
SKIP_PREFIXES = ("/docs", "/openapi.json", "/redoc", "/health")
SKIP_SUFFIXES = ("/stream",)

# Regex to find {param} placeholders in paths
PATH_PARAM_RE = re.compile(r"\{[^}]+\}")

# Fuzz payloads by category
PAYLOADS: dict[str, list[str]] = {
    "sql_injection": [
        "' OR 1=1--",
        "'; DROP TABLE users;--",
        "1; SELECT * FROM information_schema.tables--",
        "' UNION SELECT NULL,NULL,NULL--",
    ],
    "xss": [
        "<script>alert(1)</script>",
        '<img onerror=alert(1) src="">',
        "javascript:alert(1)",
        '"><svg onload=alert(1)>',
    ],
    "path_traversal": [
        "../../../../etc/passwd",
        "..%2F..%2F..%2F..%2Fetc%2Fpasswd",
        "....//....//etc/passwd",
        "/etc/shadow",
    ],
    "oversized": [
        "A" * 10_000,
    ],
    "type_confusion": [
        "not-a-uuid",
        "99999999",
        "-1",
        "true",
        "null",
        '{"nested": "object"}',
    ],
    "empty": [
        "",
    ],
}

TOTAL_REQUESTS = 0
ERROR_500_COUNT = 0
CONNECT_ERROR_COUNT = 0
ENDPOINTS_TESTED = 0
MAX_CONSECUTIVE_CONNECT_ERRORS = 10


def setup_session(client: httpx.Client) -> bool:
    """Register + login a throwaway user, storing cookies on the client.

    Returns True if login succeeded (cookies are set on the client).
    """
    email = f"fuzz_{uuid.uuid4().hex[:10]}@example.com"
    password = os.environ.get("TEST_PASSWORD")
    if not password:
        print("WARNING: TEST_PASSWORD not set, generating random password")
        password = f"Fuzz-{uuid.uuid4().hex[:12]}9Xa!"

    client.post(
        f"{API_URL}/api/auth/register",
        json={"email": email, "password": password},
    )
    resp = client.post(
        f"{API_URL}/api/auth/login",
        json={"email": email, "password": password},
    )

    has_session = any(
        c.name == "glycemicgpt_session" for c in client.cookies.jar
    )
    if not has_session and resp.status_code == 200:
        # Fallback: parse Set-Cookie header manually
        for sc in resp.headers.get_list("set-cookie"):
            if "glycemicgpt_session=" in sc:
                val = sc.split("glycemicgpt_session=")[1].split(";")[0]
                client.cookies.set("glycemicgpt_session", val)
                has_session = True
                break

    return has_session


def should_skip(path: str) -> bool:
    """Check if an endpoint should be skipped."""
    for prefix in SKIP_PREFIXES:
        if path.startswith(prefix):
            return True
    for suffix in SKIP_SUFFIXES:
        if path.endswith(suffix):
            return True
    return False


def resolve_path_params(path: str, payload: str) -> str:
    """Replace {param} placeholders in the path with the fuzz payload."""
    return PATH_PARAM_RE.sub(payload, path)


def make_fuzz_body(payload: str, schema: dict | None) -> dict:
    """Build a JSON body using the payload for all string fields."""
    if not schema:
        return {"data": payload}

    # Try to populate fields from schema properties
    properties = schema.get("properties", {})
    if not properties:
        return {"data": payload}

    body: dict = {}
    for field_name, field_info in properties.items():
        field_type = field_info.get("type", "string")
        if field_type == "string":
            body[field_name] = payload
        elif field_type == "integer":
            body[field_name] = payload  # Type confusion is intentional
        elif field_type == "boolean":
            body[field_name] = payload
        elif field_type == "number":
            body[field_name] = payload
        else:
            body[field_name] = payload
    return body


def resolve_ref(ref: str, openapi: dict) -> dict:
    """Resolve a $ref pointer like '#/components/schemas/Foo'."""
    parts = ref.lstrip("#/").split("/")
    node = openapi
    for part in parts:
        node = node.get(part, {})
    return node


def get_request_schema(operation: dict, openapi: dict) -> dict | None:
    """Extract the JSON request body schema from an operation."""
    request_body = operation.get("requestBody", {})
    content = request_body.get("content", {})
    json_content = content.get("application/json", {})
    schema = json_content.get("schema", {})

    if "$ref" in schema:
        return resolve_ref(schema["$ref"], openapi)
    return schema if schema else None


def has_path_params(path: str) -> bool:
    """Check if a path has {param} placeholders."""
    return bool(PATH_PARAM_RE.search(path))


def fuzz_endpoint(
    client: httpx.Client,
    method: str,
    path: str,
    schema: dict | None,
) -> bool:
    """Send all payload categories against a single endpoint.

    Returns False if too many consecutive connection errors occurred
    (possible server crash).
    """
    global TOTAL_REQUESTS, ERROR_500_COUNT, CONNECT_ERROR_COUNT

    headers = {}
    csrf_token = ""
    for cookie in client.cookies.jar:
        if cookie.name == "csrf_token":
            csrf_token = cookie.value
            break
    if csrf_token and method.upper() in ("POST", "PUT", "PATCH", "DELETE"):
        headers["X-CSRF-Token"] = csrf_token

    consecutive_connect_errors = 0

    for category, payloads in PAYLOADS.items():
        for payload in payloads:
            TOTAL_REQUESTS += 1

            # Substitute path parameters with fuzz payload
            resolved_path = resolve_path_params(path, payload) if has_path_params(path) else path

            try:
                if method.upper() in ("GET", "HEAD", "OPTIONS"):
                    resp = client.request(
                        method,
                        f"{API_URL}{resolved_path}",
                        params={"q": payload, "id": payload},
                        headers=headers,
                        timeout=10,
                    )
                else:
                    body = make_fuzz_body(payload, schema)
                    resp = client.request(
                        method,
                        f"{API_URL}{resolved_path}",
                        json=body,
                        headers=headers,
                        timeout=10,
                    )

                consecutive_connect_errors = 0  # Reset on success

                if resp.status_code == 500:
                    ERROR_500_COUNT += 1
                    print(
                        f"  [500] {method.upper()} {resolved_path} "
                        f"({category}): {payload[:60]}"
                    )
                elif resp.status_code == 429:
                    # Rate limited -- stop hitting this endpoint
                    return True

            except httpx.TimeoutException:
                pass  # Timeouts are acceptable (e.g. SSE endpoints)
            except httpx.ConnectError:
                consecutive_connect_errors += 1
                CONNECT_ERROR_COUNT += 1
                if consecutive_connect_errors >= MAX_CONSECUTIVE_CONNECT_ERRORS:
                    print(
                        f"  [WARN] {MAX_CONSECUTIVE_CONNECT_ERRORS} consecutive "
                        f"connection errors on {method.upper()} {path} -- "
                        f"server may have crashed"
                    )
                    return False

    return True


def fetch_openapi(api_url: str) -> dict | None:
    """Fetch and return the OpenAPI spec, or None on failure."""
    print("Fetching /openapi.json ...")
    with httpx.Client(timeout=10) as client:
        resp = client.get(f"{api_url}/openapi.json")
        if resp.status_code != 200:
            print(f"Failed to fetch OpenAPI spec: {resp.status_code}")
            return None
        openapi = resp.json()
        print(f"Found {len(openapi.get('paths', {}))} paths")
        return openapi


def run_fuzz_pass(
    api_url: str,
    openapi: dict,
    pass_name: str,
    authenticated: bool,
) -> tuple[int, int, int, bool]:
    """Run a single fuzzing pass. Returns (endpoints, requests, errors_500, server_alive)."""
    global TOTAL_REQUESTS, ERROR_500_COUNT, CONNECT_ERROR_COUNT, ENDPOINTS_TESTED
    # Reset counters for this pass
    TOTAL_REQUESTS = 0
    ERROR_500_COUNT = 0
    CONNECT_ERROR_COUNT = 0
    ENDPOINTS_TESTED = 0

    print(f"--- {pass_name} ---")
    paths = openapi.get("paths", {})

    with httpx.Client(timeout=10) as client:
        if authenticated:
            print("Creating test session ...")
            if not setup_session(client):
                print("WARNING: Could not get session cookie; "
                      "some endpoints may return 401")
        else:
            print("Running without authentication (attacker perspective)")
        print()

        server_alive = True
        for path, methods in paths.items():
            if should_skip(path):
                continue
            if not server_alive:
                break

            for method, operation in methods.items():
                if method.lower() not in ("get", "post", "put", "patch", "delete"):
                    continue
                if not isinstance(operation, dict):
                    continue

                ENDPOINTS_TESTED += 1
                schema = get_request_schema(operation, openapi)
                summary = operation.get("summary", "")
                print(f"  Fuzzing {method.upper()} {path} ({summary})")
                server_alive = fuzz_endpoint(client, method, path, schema)
                if not server_alive:
                    print("  Aborting fuzz run due to server connectivity issues")
                    break

    print()
    print(f"  Endpoints tested: {ENDPOINTS_TESTED}")
    print(f"  Total requests: {TOTAL_REQUESTS}")
    print(f"  500 errors: {ERROR_500_COUNT}")
    if CONNECT_ERROR_COUNT > 0:
        print(f"  Connection errors: {CONNECT_ERROR_COUNT}")

    return ENDPOINTS_TESTED, TOTAL_REQUESTS, ERROR_500_COUNT, server_alive


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenAPI-driven endpoint fuzzer")
    parser.add_argument("api_url", nargs="?", default=API_URL, help="API base URL")
    parser.add_argument(
        "--mode",
        default="both",
        choices=["authenticated", "unauthenticated", "both"],
        help="Fuzzing mode: authenticated, unauthenticated, or both (default: both)",
    )
    args = parser.parse_args()
    api_url = args.api_url

    print("=== OpenAPI Endpoint Fuzzer ===")
    print(f"API: {api_url}")
    print(f"Mode: {args.mode}")
    print()

    openapi = fetch_openapi(api_url)
    if not openapi:
        return 1
    print()

    total_500s = 0
    all_alive = True

    if args.mode in ("authenticated", "both"):
        _, _, errors, alive = run_fuzz_pass(
            api_url, openapi, "Authenticated Fuzzing Pass", authenticated=True,
        )
        total_500s += errors
        all_alive = all_alive and alive
        print()

    if args.mode in ("unauthenticated", "both"):
        _, _, errors, alive = run_fuzz_pass(
            api_url, openapi, "Unauthenticated Fuzzing Pass", authenticated=False,
        )
        total_500s += errors
        all_alive = all_alive and alive
        print()

    if total_500s > 0 or not all_alive:
        if not all_alive:
            print("FAIL: Server became unreachable during fuzzing")
        else:
            print(f"FAIL: {total_500s} total 500 errors across all passes")
        return 1

    print("PASS: No 500 errors detected in any pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
