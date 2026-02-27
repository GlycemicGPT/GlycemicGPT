"""Story 28.4: Double-submit cookie CSRF protection middleware.

Sets a `csrf_token` cookie when absent. State-changing requests
(POST, PATCH, PUT, DELETE) from web clients (cookie-authenticated)
must include the cookie value as an `X-CSRF-Token` header.

Exempt paths:
- Login/register (no session yet)
- Mobile endpoints (Bearer auth, no cookies)
- Health check
- SSE streams (GET only)
"""

import secrets
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.config import settings

_CSRF_COOKIE_NAME = "csrf_token"
_CSRF_HEADER_NAME = "x-csrf-token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# Paths exempt from CSRF validation
_EXEMPT_PREFIXES = (
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/mobile/",
    "/api/disclaimer/",
    "/health",
    "/api/glucose/stream",
    "/api/alerts/stream",
    "/docs",
    "/openapi.json",
    "/",
)


def _is_exempt(path: str) -> bool:
    """Check if a request path is exempt from CSRF validation."""
    if path == "/":
        return True
    return any(prefix != "/" and path.startswith(prefix) for prefix in _EXEMPT_PREFIXES)


def _is_bearer_auth(request: Request) -> bool:
    """Check if the request uses Bearer token auth (mobile clients)."""
    auth_header = request.headers.get("authorization", "")
    return auth_header.startswith("Bearer ")


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF protection.

    Sets a non-httpOnly `csrf_token` cookie when absent so JavaScript can
    read it. On state-changing requests from cookie-authenticated clients,
    validates that `X-CSRF-Token` header matches the cookie.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Disable CSRF enforcement during tests
        if settings.testing:
            return await call_next(request)

        # Always let safe methods and exempt paths through
        if request.method in _SAFE_METHODS or _is_exempt(request.url.path):
            response = await call_next(request)
            self._set_csrf_cookie(request, response)
            return response

        # Bearer-auth requests (mobile) skip CSRF
        if _is_bearer_auth(request):
            return await call_next(request)

        # For cookie-authenticated state-changing requests, validate CSRF
        session_cookie = request.cookies.get(settings.jwt_cookie_name)
        if session_cookie:
            csrf_cookie = request.cookies.get(_CSRF_COOKIE_NAME)
            csrf_header = request.headers.get(_CSRF_HEADER_NAME)

            if (
                not csrf_cookie
                or not csrf_header
                or not secrets.compare_digest(csrf_cookie, csrf_header)
            ):
                return Response(
                    content='{"detail":"CSRF token missing or invalid"}',
                    status_code=403,
                    media_type="application/json",
                )

        response = await call_next(request)
        self._set_csrf_cookie(request, response)
        return response

    def _set_csrf_cookie(self, request: Request, response: Response) -> None:
        """Set the CSRF cookie on the response if not already present.

        Only sets a new token when the client has no existing CSRF cookie,
        avoiding race conditions where concurrent requests invalidate each
        other's tokens.
        """
        if request.cookies.get(_CSRF_COOKIE_NAME):
            return

        token = secrets.token_urlsafe(32)
        response.set_cookie(
            key=_CSRF_COOKIE_NAME,
            value=token,
            httponly=False,  # Must be readable by JavaScript
            secure=settings.cookie_secure,
            samesite="lax",
            path="/",
            max_age=settings.session_expire_hours * 3600,
        )
