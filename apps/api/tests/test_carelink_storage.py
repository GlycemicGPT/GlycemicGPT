"""Tests for CareLink record storage (idempotent upserts) against the DB."""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

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
from src.services.pump_event_dedupe import compute_pump_event_dedupe_hash

# Anchor on a 30-second epoch boundary (HH:MM:00) so timestamp offsets land in
# the dedupe bucket we intend regardless of when the suite runs.
_BUCKET_BASE = datetime(2025, 1, 31, 12, 0, 0, tzinfo=UTC)


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


async def _bolus_count(db, user_id) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(PumpEvent)
            .where(
                PumpEvent.user_id == user_id,
                PumpEvent.event_type == PumpEventType.BOLUS,
            )
        )
    ).scalar_one()


async def _insert_other_source(db, user_id, *, ts, units, source):
    """Insert a non-CareLink delivery row via the production bare insert path."""
    row = {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "event_type": PumpEventType.BOLUS,
        "event_timestamp": ts,
        "units": units,
        "duration_minutes": None,
        "is_automated": False,
        "received_at": datetime.now(UTC),
        "source": source,
        "ns_id": f"other-{uuid.uuid4().hex}",
        "dedupe_hash": compute_pump_event_dedupe_hash(
            user_id=user_id,
            event_type=PumpEventType.BOLUS,
            event_timestamp=ts,
            units=units,
            duration_minutes=None,
        ),
    }
    stmt = (
        insert(PumpEvent).values([row]).on_conflict_do_nothing().returning(PumpEvent.id)
    )
    res = await db.execute(stmt)
    await db.commit()
    return len(res.fetchall())


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


async def test_same_dose_two_sources_collapses():
    # A dose relayed via Nightscout careportal then the same physical dose synced
    # from CareLink (0.03 U apart, same 30 s bucket, distinct seconds so the
    # natural key would NOT collapse them) -> one row, first writer wins.
    async with get_session_maker()() as db:
        uid = await _make_user(db)
        t_ns = _BUCKET_BASE + timedelta(seconds=4)
        t_cl = _BUCKET_BASE + timedelta(seconds=12)
        assert (
            await _insert_other_source(
                db, uid, ts=t_ns, units=2.50, source="nightscout:1"
            )
            == 1
        )

        res = await store_carelink_records(
            db,
            uid,
            MappedRecords(
                pump_events=[
                    MappedPumpEvent(PumpEventType.BOLUS, t_cl, units=2.53),
                ]
            ),
        )
        assert res.events_stored == 0  # suppressed by dedupe_hash
        assert await _bolus_count(db, uid) == 1
        kept = await db.execute(
            select(PumpEvent.source).where(PumpEvent.user_id == uid)
        )
        assert kept.scalar_one() == "nightscout:1"


async def test_distinct_doses_31s_apart_both_persist():
    # 31 s apart -> different 30 s buckets -> different hashes -> both kept.
    async with get_session_maker()() as db:
        uid = await _make_user(db)
        t_ns = _BUCKET_BASE
        t_cl = _BUCKET_BASE + timedelta(seconds=31)
        assert (
            await _insert_other_source(
                db, uid, ts=t_ns, units=2.50, source="nightscout:1"
            )
            == 1
        )

        res = await store_carelink_records(
            db,
            uid,
            MappedRecords(
                pump_events=[MappedPumpEvent(PumpEventType.BOLUS, t_cl, units=2.50)]
            ),
        )
        assert res.events_stored == 1
        assert await _bolus_count(db, uid) == 2


async def test_delivery_rows_hashed_telemetry_opts_out():
    # BOLUS/BASAL participate in the cross-source index; a no-units SUSPEND
    # opts out (dedupe_hash is None).
    async with get_session_maker()() as db:
        uid = await _make_user(db)
        await store_carelink_records(
            db,
            uid,
            MappedRecords(
                pump_events=[
                    MappedPumpEvent(PumpEventType.BOLUS, _BUCKET_BASE, units=3.0),
                    MappedPumpEvent(
                        PumpEventType.BASAL,
                        _BUCKET_BASE + timedelta(minutes=5),
                        units=0.8,
                    ),
                    MappedPumpEvent(
                        PumpEventType.SUSPEND, _BUCKET_BASE + timedelta(minutes=10)
                    ),
                ]
            ),
        )
        rows = await db.execute(
            select(PumpEvent.event_type, PumpEvent.dedupe_hash).where(
                PumpEvent.user_id == uid
            )
        )
        by_type = dict(rows.all())
        assert by_type[PumpEventType.BOLUS] is not None
        assert by_type[PumpEventType.BASAL] is not None
        assert by_type[PumpEventType.SUSPEND] is None
