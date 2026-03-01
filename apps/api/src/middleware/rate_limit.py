"""Rate limiting middleware using slowapi.

Protects auth and data push endpoints from abuse.
Debug builds get relaxed limits via configuration.
"""

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import settings

# Use in-memory storage during tests (no Redis dependency), otherwise Redis
_storage_uri = (
    "memory://"
    if settings.testing
    else (settings.redis_url if settings.redis_url else "memory://")
)


def _get_real_client_ip(request: Request) -> str:
    """Extract real client IP, respecting X-Forwarded-For behind reverse proxies."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # Take the first (leftmost) IP -- the original client
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(
    key_func=_get_real_client_ip,
    storage_uri=_storage_uri,
    enabled=not settings.testing,
)

# Rate limits are applied per-endpoint via @limiter.limit() decorators:
# Auth login endpoints: 10/minute
# Refresh endpoint: 30/minute
# Device registration: 10/minute
# Pump push: 60/minute
# API key creation: 5/minute


def is_debug_build(request: Request) -> bool:
    """Check if the current request came from a debug build.

    Inspects request.state for build_type set during auth (API key or
    device registration context).
    """
    key_scopes = getattr(request.state, "_api_key_scopes", None)
    if key_scopes is not None:
        # API key auth -- check key's build_type stored on state
        return getattr(request.state, "_api_key_build_type", None) == "debug"
    return False


async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Return a 429 JSON response when rate limit is exceeded."""
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )
