"""Tests for the Glooko mapper (pure) + storage (DB idempotency).

Mapper fixtures are captured-real (redacted) payloads from the live capture
(`tests/fixtures/glooko/`), not invented shapes -- because invented JSON is how
mappers pass tests and then fail on real data.
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from src.database import get_session_maker
from src.models.glucose import GlucoseReading, TrendDirection
from src.models.pump_data import PumpEvent, PumpEventType
from src.models.user import User
from src.services.integrations.glooko import mapper
from src.services.integrations.glooko.mapper import (
    MappedGlucose,
    MappedPumpEvent,
    MappedRecords,
)
from src.services.integrations.glooko.storage import store_glooko_records

_FIX = Path(__file__).parent / "fixtures" / "glooko"


def _load(name: str) -> list[dict]:
    return json.loads((_FIX / name).read_text())


# =============================== mapper: CGM ==================================


def test_map_cgm_points_value_unit_and_utc():
    points = mapper.map_cgm_points(_load("cgm_points.json"))
    # 5 raw points: 204, 180, 69 valid; 700 (>600 bound) and null dropped.
    assert [p.value_mgdl for p in points] == [204, 180, 69]
    first = points[0]
    assert first.timestamp == datetime(
        2023, 6, 1, 0, 2, 8, tzinfo=UTC
    )  # genuine-UTC ts
    assert first.timestamp.tzinfo is not None
    assert all(p.source == "glooko" for p in points)


# =============================== mapper: basal ================================


def test_map_scheduled_basals_rate_duration_and_local_offset_to_utc():
    events = mapper.map_scheduled_basals(_load("scheduled_basals.json"))
    assert len(events) == 2
    e = events[0]
    assert e.event_type is PumpEventType.BASAL
    assert e.units == 0.55  # rate U/h
    assert e.duration_minutes == 5  # 318s
    assert e.ns_id == "11111111-0000-0000-0000-000000000001"
    # FOOTGUN: pumpTimestamp 19:10:26 is LOCAL at -04:00 -> 23:10:26 UTC
    assert e.timestamp == datetime(2023, 3, 30, 23, 10, 26, tzinfo=UTC)


# =============================== mapper: bolus ================================


def test_map_normal_boluses_context_and_automation():
    events = mapper.map_normal_boluses(_load("normal_boluses.json"))
    assert len(events) == 2
    manual, auto = events
    assert manual.event_type is PumpEventType.BOLUS
    assert manual.units == 14.05
    assert manual.iob_at_event == 1.2
    assert manual.cob_at_event == 85.0
    assert manual.bg_at_event is None  # bloodGlucoseInput 0 -> not stored
    assert manual.is_automated is False  # type "suggested"
    assert manual.ns_id == "22222222-0000-0000-0000-000000000001"
    # 18:27:45 local @ -04:00 -> 22:27:45 UTC
    assert manual.timestamp == datetime(2023, 3, 29, 22, 27, 45, tzinfo=UTC)

    assert auto.is_automated is True  # type "automatic" (SmartAdjust)
    assert auto.bg_at_event == 165
    assert auto.cob_at_event is None  # carbsInput 0


# =============================== mapper: events ===============================


def test_map_events_pod_suspend_resume_and_unknown_skipped():
    events = mapper.map_events(_load("events.json"))
    by_type = [(e.event_type, e.metadata_json) for e in events]
    # pod_activating + reservoir_change -> DEVICE_EVENT (glooko type in metadata);
    # insulin_suspended -> SUSPEND; insulin_resumed -> RESUME; unknown -> skipped.
    assert len(events) == 4
    assert by_type[0] == (
        PumpEventType.DEVICE_EVENT,
        {"glooko_event": "pod_activating"},
    )
    assert by_type[1] == (
        PumpEventType.DEVICE_EVENT,
        {"glooko_event": "reservoir_change"},
    )
    assert events[2].event_type is PumpEventType.SUSPEND
    assert events[3].event_type is PumpEventType.RESUME
    assert events[0].ns_id == "33333333-0000-0000-0000-000000000001"


def test_map_glooko_combines_all_series():
    rec = mapper.map_glooko(
        cgm_points=_load("cgm_points.json"),
        scheduled_basals=_load("scheduled_basals.json"),
        normal_boluses=_load("normal_boluses.json"),
        events=_load("events.json"),
    )
    assert len(rec.glucose) == 3
    assert len(rec.pump_events) == 2 + 2 + 4  # basals + boluses + events


def test_map_pump_ts_refuses_missing_offset():
    # No offset -> cannot resolve a local wall-time to UTC -> record dropped (not misdated).
    out = mapper.map_scheduled_basals(
        [{"pumpTimestamp": "2023-03-30T19:10:26.000Z", "rate": 0.5, "guid": "g"}]
    )
    assert out == []


def test_map_honors_soft_deleted():
    # A record the user deleted in Glooko must not be ingested (reverse-eng §9/§11).
    deleted = {
        "pumpTimestamp": "2023-03-29T18:27:45.000Z",
        "pumpTimestampUtcOffset": "-04:00",
        "insulinDelivered": 5.0,
        "guid": "deleted-1",
        "softDeleted": True,
    }
    assert mapper.map_normal_boluses([deleted]) == []
    assert mapper.map_scheduled_basals([{**deleted, "rate": 0.5}]) == []
    assert mapper.map_events([{**deleted, "type": "pod_activating"}]) == []


def test_map_pump_ts_trusts_a_real_offset_when_present():
    # Defensive branch: if a timestamp ever carries a genuine offset, trust it directly.
    out = mapper.map_scheduled_basals(
        [{"pumpTimestamp": "2023-03-30T19:10:26-04:00", "rate": 0.5, "guid": "g"}]
    )
    assert len(out) == 1
    assert out[0].timestamp == datetime(2023, 3, 30, 23, 10, 26, tzinfo=UTC)


# =============================== storage: DB idempotency =====================


async def _make_user(db) -> uuid.UUID:
    user = User(
        email=f"glooko_store_{uuid.uuid4().hex[:8]}@example.com", hashed_password="x"
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


def _records(ts: datetime, prefix: str) -> MappedRecords:
    # `prefix` keeps ns_id values unique PER TEST RUN: the (source, ns_id) dedupe
    # index is global (not user-scoped), so reusing literal guids would collide with
    # rows leaked by a prior run on a persistent dev DB. Real Glooko guids are
    # globally unique by construction; the test must mimic that to stay hermetic.
    return MappedRecords(
        glucose=[MappedGlucose(timestamp=ts, value_mgdl=120)],
        pump_events=[
            MappedPumpEvent(
                event_type=PumpEventType.BOLUS,
                timestamp=ts,
                units=2.0,
                ns_id=f"{prefix}-bolus",
            ),
            MappedPumpEvent(
                event_type=PumpEventType.DEVICE_EVENT,
                timestamp=ts,
                ns_id=f"{prefix}-pod",
                metadata_json={"glooko_event": "pod_activating"},
            ),
        ],
    )


async def test_store_then_reimport_is_idempotent():
    ts = datetime(2025, 2, 1, 12, 0, tzinfo=UTC)
    prefix = uuid.uuid4().hex[
        :12
    ]  # same prefix across both stores -> tests idempotency
    async with get_session_maker()() as db:
        uid = await _make_user(db)
        res = await store_glooko_records(db, uid, _records(ts, prefix))
        assert res.glucose_stored == 1
        assert res.events_stored == 2
        assert (await _count(db, GlucoseReading, uid)) == 1
        assert (await _count(db, PumpEvent, uid)) == 2
        # the glucose row got NOT_COMPUTABLE trend (graph/data has no arrow)
        trend = (
            await db.execute(
                select(GlucoseReading.trend).where(GlucoseReading.user_id == uid)
            )
        ).scalar_one()
        assert trend is TrendDirection.NOT_COMPUTABLE

        res2 = await store_glooko_records(db, uid, _records(ts, prefix))
        assert res2.glucose_stored == 0
        assert res2.events_stored == 0
        assert (await _count(db, PumpEvent, uid)) == 2


async def test_same_timestamp_different_guid_both_stored():
    # ns_id (guid) dedup -> two events at the same instant with different guids both
    # persist (the natural-key index would have dropped one).
    ts = datetime(2025, 2, 1, 12, 0, tzinfo=UTC)
    prefix = uuid.uuid4().hex[:12]
    async with get_session_maker()() as db:
        uid = await _make_user(db)
        rec = MappedRecords(
            pump_events=[
                MappedPumpEvent(
                    event_type=PumpEventType.BOLUS,
                    timestamp=ts,
                    units=1.0,
                    ns_id=f"{prefix}-a",
                ),
                MappedPumpEvent(
                    event_type=PumpEventType.BOLUS,
                    timestamp=ts,
                    units=2.0,
                    ns_id=f"{prefix}-b",
                ),
            ]
        )
        res = await store_glooko_records(db, uid, rec)
        assert res.events_stored == 2
        assert (await _count(db, PumpEvent, uid)) == 2
