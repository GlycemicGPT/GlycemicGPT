"""Tests for the token blacklist degradation policy (Story 28.3 hardening).

The split policy under Redis failure:
- ``is_token_blacklisted`` fails OPEN (access-token gate; outage must not lock
  every user out).
- ``consume_token_once`` fails CLOSED by raising
  ``TokenConsumeUnavailableError`` (single-use guard for refresh/pairing
  tokens; an outage must not grant unlimited replay, but callers must be able
  to tell it apart from a replay so they can return a retryable status).
"""

import uuid

import pytest
import redis.asyncio as aioredis

from src.config import settings
from src.core import token_blacklist
from src.core.token_blacklist import (
    TokenConsumeUnavailableError,
    blacklist_token,
    consume_token_once,
    is_token_blacklisted,
)


def _jti() -> str:
    return uuid.uuid4().hex


class _FailingRedis:
    """Stub client whose every operation raises RedisError."""

    async def set(self, *args, **kwargs):
        raise aioredis.RedisError("redis down")

    async def setex(self, *args, **kwargs):
        raise aioredis.RedisError("redis down")

    async def exists(self, *args, **kwargs):
        raise aioredis.RedisError("redis down")


@pytest.fixture
def redis_down(monkeypatch):
    """Route the module at a failing Redis client, bypassing test mode."""
    monkeypatch.setattr(settings, "testing", False)
    monkeypatch.setattr(token_blacklist, "_get_redis", lambda: _FailingRedis())


class TestRedisUnavailable:
    async def test_consume_token_once_fails_closed(self, redis_down):
        with pytest.raises(TokenConsumeUnavailableError):
            await consume_token_once(_jti(), 60)

    async def test_is_token_blacklisted_fails_open(self, redis_down):
        assert await is_token_blacklisted(_jti()) is False

    async def test_blacklist_token_swallows_error(self, redis_down):
        # Best-effort: must not raise.
        await blacklist_token(_jti(), 60)


class TestSingleUseSemantics:
    async def test_consume_token_once_first_use_wins(self):
        jti = _jti()
        assert await consume_token_once(jti, 60) is True
        assert await consume_token_once(jti, 60) is False

    async def test_blacklisted_token_is_detected(self):
        jti = _jti()
        await blacklist_token(jti, 60)
        assert await is_token_blacklisted(jti) is True
        assert await is_token_blacklisted(_jti()) is False
