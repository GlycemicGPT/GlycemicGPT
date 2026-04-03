"""Security response headers middleware.

Adds standard security headers to every HTTP response to mitigate
common web vulnerabilities (clickjacking, MIME sniffing, etc.).

Headers that belong on the reverse proxy (e.g. Strict-Transport-Security)
are intentionally omitted -- the API may run behind HTTP internally.

Uses a pure ASGI middleware (not BaseHTTPMiddleware) to avoid buffering
the full response body -- critical for SSE streaming endpoints.
"""

from collections.abc import Callable, MutableMapping
from typing import Any

# ASGI type aliases
Scope = MutableMapping[str, Any]
Receive = Callable[..., Any]
Send = Callable[..., Any]

# Headers applied to every response, pre-encoded for ASGI.
_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    # X-XSS-Protection: 0 disables the legacy XSS auditor (which can
    # introduce vulnerabilities in modern browsers).
    (b"x-xss-protection", b"0"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]

# Header names we manage -- used to strip duplicates from upstream responses.
_MANAGED_HEADER_NAMES: set[bytes] = {h[0] for h in _SECURITY_HEADERS}


class SecurityHeadersMiddleware:
    """Pure ASGI middleware that injects security headers into every response."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                # Strip any existing values for headers we manage to avoid
                # duplicates when a reverse proxy also sets them.
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k not in _MANAGED_HEADER_NAMES
                ]
                headers.extend(_SECURITY_HEADERS)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
