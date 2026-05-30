"""Short-handle bundle store for the Medtronic Connect desktop helper.

Background. The helper one-liner originally carried the full Fernet pair
token (~272 chars) plus api/username/region in the query string, so the
copy-paste command landed at ~540 chars. We don't want to make the pair
token shorter (it has to remain a self-verifying credential the backend
can validate without state), so we hide it behind an opaque 12-hex-char
"install handle" instead. The handle indexes a server-side bundle that
holds the full pair token + api/username/region, with the same 15-min TTL
as the pair token itself.

Security posture is unchanged from the long-URL form:

  * Bundle TTL == pair-token TTL. Handle expires when the pair would.
  * The underlying pair-token jti is still consumed by `/exchange`; once
    consumed, the helper-endpoint gate (`is_token_blacklisted`) makes
    all install/helper URLs go dark within the next request.
  * Handles are 64-bit (16 hex chars; see ``_INSTALL_HANDLE_BYTES`` in the
    router). Inside the 15-min window, even at 1e5 guesses/sec, the
    brute-force success probability is ~5e-11 -- well below guessing a TOTP.
  * Each handle is created behind cookie+CSRF auth at /install, so an
    unauthenticated attacker can't even enumerate handles to test.

Like `token_blacklist`, this module fails open on Redis errors: if Redis
is briefly unreachable we'd rather let the install proceed than lock the
user out of their own setup. Worst case if Redis is down: the helper
endpoint can't find the bundle and 404s, the user retries.

Test mode uses an in-memory dict so the bundle-store contract is actually
exercised by tests (mirroring the token_blacklist pattern).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis

from src.config import settings

logger = logging.getLogger(__name__)

_BUNDLE_PREFIX = "medtronic_connect_install:"

_redis_client: aioredis.Redis | None = None

# Test-mode store: {handle: (expire_monotonic, bundle_json)}.
_test_store: dict[str, tuple[float, str]] = {}


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


async def store_install_bundle(
    handle: str, bundle: dict[str, Any], ttl_seconds: int
) -> None:
    """Persist an install bundle under `handle` for `ttl_seconds`.

    The bundle is JSON-encoded; callers are expected to keep it small
    (a few hundred bytes, no large blobs).
    """
    ttl_seconds = max(1, ttl_seconds)
    payload = json.dumps(bundle, separators=(",", ":"))

    if settings.testing:
        _test_store[handle] = (time.monotonic() + ttl_seconds, payload)
        return

    try:
        client = _get_redis()
        await client.setex(f"{_BUNDLE_PREFIX}{handle}", ttl_seconds, payload)
    except aioredis.RedisError:
        logger.error(
            "Failed to store Medtronic Connect install bundle (Redis unavailable)",
            extra={"handle_present": True},
        )


async def get_install_bundle(handle: str) -> dict[str, Any] | None:
    """Look up an install bundle by `handle`. Returns None if missing or expired.

    Returns None (not raise) on Redis errors; the caller is expected to
    translate "no bundle" into a 404, which is also what the user sees
    when the bundle has legitimately expired or been consumed.
    """
    if not handle:
        return None

    if settings.testing:
        entry = _test_store.get(handle)
        if entry is None:
            return None
        expire, payload = entry
        if time.monotonic() > expire:
            _test_store.pop(handle, None)
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    try:
        client = _get_redis()
        payload = await client.get(f"{_BUNDLE_PREFIX}{handle}")
    except aioredis.RedisError:
        logger.error(
            "Redis unavailable for Medtronic Connect install bundle lookup",
            extra={"handle_present": True},
        )
        return None
    if payload is None:
        return None
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        logger.error(
            "Corrupt Medtronic Connect install bundle payload; discarding",
            extra={"handle_present": True},
        )
        return None


async def discard_install_bundle(handle: str) -> None:
    """Best-effort delete (not used by normal flow; here for tests + future cleanup)."""
    if not handle:
        return
    if settings.testing:
        _test_store.pop(handle, None)
        return
    try:
        client = _get_redis()
        await client.delete(f"{_BUNDLE_PREFIX}{handle}")
    except aioredis.RedisError:
        pass
