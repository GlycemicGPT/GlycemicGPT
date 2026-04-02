"""Rate limiting middleware using slowapi.

Protects auth and data push endpoints from abuse.
Debug builds get relaxed limits via configuration.
"""

import ipaddress

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

# Pre-parse trusted proxy CIDRs at module load for performance.
# Only requests from these networks may set X-Forwarded-For / X-Real-IP.
_TRUSTED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
for _cidr in settings.trusted_proxy_cidrs.split(","):
    _cidr = _cidr.strip()
    if _cidr:
        _TRUSTED_NETWORKS.append(ipaddress.ip_network(_cidr, strict=False))


def _is_trusted_proxy(ip: str) -> bool:
    """Check if an IP address belongs to a trusted proxy network."""
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in _TRUSTED_NETWORKS)
    except ValueError:
        return False


def _get_real_client_ip(request: Request) -> str:
    """Extract real client IP, respecting X-Forwarded-For only from trusted proxies.

    Only trusts X-Forwarded-For / X-Real-IP headers when the direct connection
    comes from a trusted proxy CIDR (e.g. Docker internal network, load balancer).
    This prevents attackers from spoofing headers to bypass rate limits.
    """
    client_ip = request.client.host if request.client else "unknown"

    if client_ip == "unknown" or not _is_trusted_proxy(client_ip):
        return client_ip

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return client_ip


limiter = Limiter(
    key_func=_get_real_client_ip,
    default_limits=["120/minute"],  # Global default: 120 req/min per IP
    storage_uri=_storage_uri,
    enabled=not settings.testing,
)

# Rate limits:
# Global default: 120/minute per IP (catches general abuse)
# Auth login endpoints: 10/minute (stricter)
# Refresh endpoint: 30/minute
# Device registration: 10/minute
# Pump push: 60/minute
# API key creation: 5/minute
# Research trigger: 2/hour (very strict -- expensive AI operation)


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
