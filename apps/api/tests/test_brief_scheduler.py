"""Tests for the automatic daily-brief scheduler (issue #741).

Pure-gate unit tests (timezone / delivery_time / idempotency logic) plus a
DB-backed test of the `generate_briefs_all_users` tick against the dev DB,
mirroring `test_nightscout_scheduler.py`'s `scheduler_ctx` pattern. The heavy
`generate_daily_brief` (AI call) is patched.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, time, timedelta
from unittest.mock import MagicMock, patch

import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete

from src.database import get_session_maker
from src.models.brief_delivery_config import BriefDeliveryConfig, DeliveryChannel
from src.models.daily_brief import DailyBrief
from src.models.user import User
from src.services.daily_brief import (
    _brief_due,
    _local_day_start_utc,
    generate_briefs_all_users,
)


# ---------------------------------------------------------------------------
# Pure gate: timezone + delivery_time + idempotency
# ---------------------------------------------------------------------------
class TestBriefGate:
    def test_local_day_start_utc_honors_timezone(self):
        # 06:30 UTC is 08:30 in Berlin (CEST, UTC+2); local midnight is the prior
        # 22:00 UTC.
        now_utc = datetime(2026, 6, 15, 6, 30, tzinfo=UTC)
        now_local, local_midnight_utc = _local_day_start_utc(now_utc, "Europe/Berlin")
        assert now_local.hour == 8 and now_local.minute == 30
        assert now_local.date() == datetime(2026, 6, 15).date()
        assert local_midnight_utc == datetime(2026, 6, 14, 22, 0, tzinfo=UTC)

    def test_due_after_delivery_time_with_no_brief(self):
        now_local, _ = _local_day_start_utc(
            datetime(2026, 6, 15, 6, 30, tzinfo=UTC), "Europe/Berlin"
        )  # 08:30 local
        assert _brief_due(
            enabled=True,
            delivery_time=time(7, 0),
            now_local=now_local,
            brief_exists_today=False,
        )

    def test_timezone_decides_the_boundary(self):
        # Same instant: past 07:00 in Berlin (08:30) but not in UTC (06:30).
        now_utc = datetime(2026, 6, 15, 6, 30, tzinfo=UTC)
        berlin_local, _ = _local_day_start_utc(now_utc, "Europe/Berlin")
        utc_local, _ = _local_day_start_utc(now_utc, "UTC")
        kw = {"enabled": True, "delivery_time": time(7, 0), "brief_exists_today": False}
        assert _brief_due(now_local=berlin_local, **kw) is True
        assert _brief_due(now_local=utc_local, **kw) is False

    def test_before_delivery_time_skips(self):
        now_local, _ = _local_day_start_utc(
            datetime(2026, 6, 15, 3, 0, tzinfo=UTC), "Europe/Berlin"
        )  # 05:00 local
        assert not _brief_due(
            enabled=True,
            delivery_time=time(7, 0),
            now_local=now_local,
            brief_exists_today=False,
        )

    def test_existing_brief_today_skips(self):
        now_local, _ = _local_day_start_utc(
            datetime(2026, 6, 15, 10, 0, tzinfo=UTC), "UTC"
        )
        assert not _brief_due(
            enabled=True,
            delivery_time=time(7, 0),
            now_local=now_local,
            brief_exists_today=True,
        )

    def test_disabled_skips(self):
        now_local, _ = _local_day_start_utc(
            datetime(2026, 6, 15, 10, 0, tzinfo=UTC), "UTC"
        )
        assert not _brief_due(
            enabled=False,
            delivery_time=time(7, 0),
            now_local=now_local,
            brief_exists_today=False,
        )


# ---------------------------------------------------------------------------
# Tick against the dev DB (generate_daily_brief patched)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def brief_ctx() -> AsyncGenerator[uuid.UUID, None]:
    """A user with a brief-delivery config; cleaned up via a fresh session."""
    session_maker = get_session_maker()
    session = session_maker()
    user = User(
        email=f"brief_{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
    )
    session.add(user)
    await session.flush()
    user_id = user.id
    await session.commit()
    await session.close()
    try:
        yield user_id
    finally:
        async with session_maker() as cleanup:
            await cleanup.execute(
                delete(DailyBrief).where(DailyBrief.user_id == user_id)
            )
            await cleanup.execute(
                delete(BriefDeliveryConfig).where(
                    BriefDeliveryConfig.user_id == user_id
                )
            )
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()


async def _add_config(user_id: uuid.UUID, *, enabled: bool = True) -> None:
    async with get_session_maker()() as db:
        db.add(
            BriefDeliveryConfig(
                user_id=user_id,
                enabled=enabled,
                delivery_time=time(0, 0),  # always past -> due whenever it runs
                timezone="UTC",
                channel=DeliveryChannel.WEB_ONLY,
            )
        )
        await db.commit()


async def test_tick_generates_for_enabled_due_user(brief_ctx):
    await _add_config(brief_ctx, enabled=True)
    calls: list[uuid.UUID] = []

    async def _fake_generate(user, db, hours=24):
        calls.append(user.id)
        return MagicMock()

    with patch("src.services.daily_brief.generate_daily_brief", new=_fake_generate):
        await generate_briefs_all_users(now=datetime.now(UTC))

    assert brief_ctx in calls


async def test_tick_skips_disabled_user(brief_ctx):
    await _add_config(brief_ctx, enabled=False)
    calls: list[uuid.UUID] = []

    async def _fake_generate(user, db, hours=24):
        calls.append(user.id)
        return MagicMock()

    with patch("src.services.daily_brief.generate_daily_brief", new=_fake_generate):
        await generate_briefs_all_users(now=datetime.now(UTC))

    assert brief_ctx not in calls


async def test_tick_swallows_generation_error(brief_ctx):
    await _add_config(brief_ctx, enabled=True)

    async def _raise(user, db, hours=24):
        raise HTTPException(status_code=400, detail="Insufficient glucose data")

    with patch("src.services.daily_brief.generate_daily_brief", new=_raise):
        # Must NOT raise even though generation fails for this user.
        await generate_briefs_all_users(now=datetime.now(UTC))


async def test_tick_idempotent_when_brief_exists_today(brief_ctx):
    await _add_config(brief_ctx, enabled=True)
    now = datetime.now(UTC)
    async with get_session_maker()() as db:
        db.add(
            DailyBrief(
                user_id=brief_ctx,
                period_start=now - timedelta(hours=24),
                period_end=now,
                time_in_range_pct=80.0,
                average_glucose=120.0,
                low_count=0,
                high_count=0,
                readings_count=288,
                correction_count=0,
                ai_summary="seeded",
                ai_model="test",
                ai_provider="test",
                input_tokens=0,
                output_tokens=0,
            )
        )
        await db.commit()

    calls: list[uuid.UUID] = []

    async def _fake_generate(user, db, hours=24):
        calls.append(user.id)
        return MagicMock()

    with patch("src.services.daily_brief.generate_daily_brief", new=_fake_generate):
        await generate_briefs_all_users(now=now)

    assert brief_ctx not in calls
