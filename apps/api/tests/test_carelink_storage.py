"""Tests for CareLink record storage (idempotent upserts) against the DB."""

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from src.database import get_session_maker
from src.models.glucose import GlucoseReading
from src.models.pump_data import PumpEvent, PumpEventType
from src.models.user import User
from src.services.integrations.medtronic.carelink_mapper import (
    MappedGlucose,
    MappedPumpEvent,
    MappedRecords,
)
from src.services.integrations.medtronic.storage import store_carelink_records


async def _make_user(db) -> uuid.UUID:
    user = User(
        email=f"carelink_store_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


async def _count(db, model, user_id) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(model).where(model.user_id == user_id)
        )
    ).scalar_one()


def _sample(ts: datetime) -> MappedRecords:
    return MappedRecords(
        glucose=[MappedGlucose(timestamp=ts, value_mgdl=120)],
        pump_events=[
            MappedPumpEvent(event_type=PumpEventType.BOLUS, timestamp=ts, units=2.0),
            MappedPumpEvent(event_type=PumpEventType.BASAL, timestamp=ts, units=0.8),
        ],
    )


async def test_stores_glucose_and_events():
    ts = datetime(2025, 1, 31, 12, 0, tzinfo=UTC)
    async with get_session_maker()() as db:
        uid = await _make_user(db)
        res = await store_carelink_records(db, uid, _sample(ts))
        assert res.glucose_stored == 1
        assert res.events_stored == 2
        assert await _count(db, GlucoseReading, uid) == 1
        assert await _count(db, PumpEvent, uid) == 2


async def test_reimport_is_idempotent():
    ts = datetime(2025, 1, 31, 12, 0, tzinfo=UTC)
    async with get_session_maker()() as db:
        uid = await _make_user(db)
        await store_carelink_records(db, uid, _sample(ts))
        # Re-store the exact same range -> nothing new inserted.
        res2 = await store_carelink_records(db, uid, _sample(ts))
        assert res2.glucose_stored == 0
        assert res2.events_stored == 0
        assert await _count(db, GlucoseReading, uid) == 1
        assert await _count(db, PumpEvent, uid) == 2


async def test_intra_batch_duplicates_deduped():
    """Two glucose readings at the same timestamp in one batch -> one row."""
    ts = datetime(2025, 1, 31, 12, 0, tzinfo=UTC)
    async with get_session_maker()() as db:
        uid = await _make_user(db)
        records = MappedRecords(
            glucose=[
                MappedGlucose(timestamp=ts, value_mgdl=120),
                MappedGlucose(timestamp=ts, value_mgdl=121),  # dup key
            ],
            pump_events=[
                MappedPumpEvent(PumpEventType.SUSPEND, ts),
                MappedPumpEvent(PumpEventType.SUSPEND, ts),  # dup key
            ],
        )
        res = await store_carelink_records(db, uid, records)
        assert res.glucose_stored == 1
        assert res.events_stored == 1


async def test_naive_timestamp_is_rejected():
    # Storage requires tz-aware timestamps (sync._localize attaches the user's
    # zone). A naive pump-local time must NOT be silently coerced to UTC.
    naive = datetime(2025, 1, 31, 9, 30, 0)  # no tzinfo
    async with get_session_maker()() as db:
        uid = await _make_user(db)
        with pytest.raises(ValueError, match="timezone-aware"):
            await store_carelink_records(
                db,
                uid,
                MappedRecords(glucose=[MappedGlucose(timestamp=naive, value_mgdl=99)]),
            )


async def test_aware_timestamp_normalized_to_utc():
    # An aware non-UTC timestamp is stored as the same instant in UTC
    # (NY 09:30 EST == 14:30 UTC).
    local = datetime(2025, 1, 31, 9, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    async with get_session_maker()() as db:
        uid = await _make_user(db)
        res = await store_carelink_records(
            db,
            uid,
            MappedRecords(glucose=[MappedGlucose(timestamp=local, value_mgdl=99)]),
        )
        assert res.glucose_stored == 1
        row = (
            await db.execute(
                select(GlucoseReading).where(GlucoseReading.user_id == uid)
            )
        ).scalar_one()
        assert row.value == 99
        assert row.reading_timestamp.astimezone(UTC).hour == 14
