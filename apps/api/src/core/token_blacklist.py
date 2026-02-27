"""Story 28.3: JWT token revocation via Redis blacklist.

Provides a Redis-backed token blacklist with TTL matching token expiry.
Tokens are blacklisted on logout, password change, and token refresh.

Graceful degradation: if Redis is unavailable, tokens are allowed through
with an error log (fail-open to avoid locking users out).

During tests, an in-memory dict is used instead of Redis so that the
blacklist logic is actually exercised by tests.
"""

import logging
import time

import redis.asyncio as aioredis

from src.config import settings

logger = logging.getLogger(__name__)

_BLACKLIST_PREFIX = "token:blacklist:"

# Lazy-initialized Redis client
_redis_client: aioredis.Redis | None = None

# In-memory blacklist for tests: {jti: expire_timestamp}
_test_blacklist: dict[str, float] = {}


def _get_redis() -> aioredis.Redis:
    """Get or create the Redis client for token blacklist operations."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


async def blacklist_token(jti: str, ttl_seconds: int) -> None:
    """Add a token's JTI to the blacklist.

    Args:
        jti: The JWT ID (jti claim) to blacklist.
        ttl_seconds: Time-to-live in seconds (should match token's remaining lifetime).
    """
    ttl_seconds = max(1, ttl_seconds)

    if settings.testing:
        _test_blacklist[jti] = time.monotonic() + ttl_seconds
        return

    try:
        client = _get_redis()
        await client.setex(f"{_BLACKLIST_PREFIX}{jti}", ttl_seconds, "1")
    except aioredis.RedisError:
        logger.error(
            "Failed to blacklist token (Redis unavailable)", extra={"jti": jti}
        )


async def consume_token_once(jti: str, ttl_seconds: int) -> bool:
    """Atomically consume a token (SET NX) -- returns True if this is the first use.

    Uses Redis SET with NX (not-exists) to ensure only one caller can consume
    a given JTI. This prevents refresh token replay races where two concurrent
    requests with the same token both pass a non-atomic check-then-set.

    Args:
        jti: The JWT ID to consume.
        ttl_seconds: TTL for the consumed marker (should match token's remaining lifetime).

    Returns:
        True if the token was successfully consumed (first caller wins).
        False if the token was already consumed (replay attempt).
    """
    ttl_seconds = max(1, ttl_seconds)

    if settings.testing:
        if jti in _test_blacklist:
            return False
        _test_blacklist[jti] = time.monotonic() + ttl_seconds
        return True

    try:
        client = _get_redis()
        # SET NX: only succeeds if key does not exist (atomic)
        result = await client.set(
            f"{_BLACKLIST_PREFIX}{jti}", "1", ex=ttl_seconds, nx=True
        )
        return result is not None
    except aioredis.RedisError:
        logger.error(
            "Redis unavailable for token consumption; allowing (fail-open)",
            extra={"jti": jti},
        )
        return True  # Fail-open: allow the refresh


async def is_token_blacklisted(jti: str) -> bool:
    """Check if a token's JTI is on the blacklist.

    Returns False (allow) if Redis is unavailable (fail-open).

    Args:
        jti: The JWT ID to check.

    Returns:
        True if the token is blacklisted, False otherwise.
    """
    if settings.testing:
        expire = _test_blacklist.get(jti)
        if expire is None:
            return False
        if time.monotonic() > expire:
            _test_blacklist.pop(jti, None)
            return False
        return True

    try:
        client = _get_redis()
        result = await client.exists(f"{_BLACKLIST_PREFIX}{jti}")
        return bool(result)
    except aioredis.RedisError:
        logger.error(
            "Redis unavailable for blacklist check; allowing token (fail-open)",
            extra={"jti": jti},
        )
        return False
