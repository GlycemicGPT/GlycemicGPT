"""Unit tests for the per-user meal-intelligence gate helper.

The helper is the service-layer source of truth for the gate. Its fail-closed
posture (a missing user reads as disabled) is the security-relevant branch --
the opposite of the request-path default-ON -- so it is pinned explicitly here.
"""

import uuid

from src.database import get_session_maker
from src.models.user import User, UserRole
from src.services.meal_intelligence import is_meal_intelligence_enabled


async def _make_user(db, *, enabled: bool) -> User:
    user = User(
        email=f"meal_svc_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role=UserRole.DIABETIC,
        meal_intelligence_enabled=enabled,
    )
    db.add(user)
    await db.commit()
    return user


async def test_missing_user_is_fail_closed():
    # A non-existent user id reads as disabled (fail-closed), never the
    # default-ON posture the request path uses.
    async with get_session_maker()() as db:
        assert await is_meal_intelligence_enabled(db, uuid.uuid4()) is False


async def test_enabled_user_reads_true():
    async with get_session_maker()() as db:
        user = await _make_user(db, enabled=True)
        assert await is_meal_intelligence_enabled(db, user.id) is True


async def test_disabled_user_reads_false():
    async with get_session_maker()() as db:
        user = await _make_user(db, enabled=False)
        assert await is_meal_intelligence_enabled(db, user.id) is False
