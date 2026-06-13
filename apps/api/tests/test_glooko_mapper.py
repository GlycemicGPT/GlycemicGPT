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
    # 204/180/69 valid; 20 and 500 mg/dL exercise the exact lower/upper safety
    # bounds (both kept); 19 (<20), 501 (>500), 700 (>>500), and null are dropped.
    # Bounds match the platform-wide 20-500 glucose invariant (treatment_safety).
    assert [p.value_mgdl for p in points] == [204, 180, 69, 20, 500]
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


# =============================== mapper: pen insulins =========================


def test_map_insulins_pen_doses_and_safety_skips():
    events = mapper.map_insulins(_load("insulins.json"))
    # 7 fixture records -> 2 ingested: the device-read pen dose and the manual
    # log. Skipped: prime (never entered the body), soft-deleted, incomplete
    # (unconfirmed value), basal-type Tresiba (no BASAL rate semantics for a
    # long-acting injection -- deferred), negative value (impossible).
    assert len(events) == 2
    pen, manual = events

    assert pen.event_type is PumpEventType.BOLUS
    assert pen.units == 3.0
    assert pen.ns_id == "44444444-0000-0000-0000-000000000001"
    # Pen `timestamp` is genuine UTC (live-verified) -- no local-offset footgun.
    assert pen.timestamp == datetime(2023, 9, 3, 8, 25, 2, tzinfo=UTC)
    assert pen.is_automated is False
    assert pen.metadata_json == {
        "glooko_stream": "insulins",
        "medication": "Novorapid®",
        "pen_device": "Novo Nordisk NovoPen® 6/Echo Plus",
        "device_delivered": True,
    }

    # Hand-typed Glooko log: still a dose, but flagged as not device-read.
    assert manual.units == 6.0
    assert manual.metadata_json["device_delivered"] is False
    assert "pen_device" not in manual.metadata_json


def test_map_insulins_skips_accepted_prime():
    base = _load("insulins.json")[0]
    accepted = {**base, "suspectedPrime": False, "acceptedPrime": True}
    assert mapper.map_insulins([accepted]) == []


def test_map_insulins_rejects_implausible_doses_and_foreign_units():
    base = _load("insulins.json")[0]
    cases = {
        # Above the largest single pen actuation (60 U) -- corrupt/unit-confused.
        "oversized": {**base, "value": 950.0, "currentValue": 950.0},
        # Zero: a pen's smallest real actuation is 0.5 U, and unlike a pump's
        # 0-delivered suggested bolus there is no carb/BG context worth keeping.
        "zero": {**base, "value": 0, "currentValue": 0},
        # bool is an int in Python; a True dose must not become 1.0 U.
        "bool": {**base, "value": True, "currentValue": None},
        # NaN slips through </> bounds (every comparison on it is False).
        "nan": {**base, "value": float("nan"), "currentValue": float("nan")},
        # A present-but-foreign unit of measure must refuse, not mis-ingest.
        "foreign units": {**base, "units": "mL"},
    }
    for label, corrupt in cases.items():
        assert mapper.map_insulins([corrupt]) == [], label
    # Bound edge: exactly 60 U (largest single actuation) is a real dose.
    assert (
        mapper.map_insulins([{**base, "value": 60.0, "currentValue": 60.0}])[0].units
        == 60.0
    )
    # An absent units field stays ingestible (observed records always carry it,
    # but its absence is not evidence of a foreign unit); casing is folded.
    no_units = {k: v for k, v in base.items() if k != "units"}
    assert mapper.map_insulins([no_units])[0].units == 3.0
    assert mapper.map_insulins([{**base, "units": "Units"}])[0].units == 3.0


def test_map_insulins_prefers_current_value_over_original():
    base = _load("insulins.json")[0]
    # An edited dose: Glooko keeps the original in `value` and the correction
    # in `currentValue` -- the corrected number must win.
    edited = {**base, "value": 3.0, "currentValue": 9.0, "overrideValue": 9.0}
    assert mapper.map_insulins([edited])[0].units == 9.0
    # currentValue absent -> fall back to value.
    absent = {**base, "currentValue": None}
    assert mapper.map_insulins([absent])[0].units == 3.0
    # currentValue PRESENT but implausible -> refuse the record outright rather
    # than fall back to the possibly-stale pre-edit value.
    implausible = {**base, "value": 3.0, "currentValue": 950.0}
    assert mapper.map_insulins([implausible]) == []


def test_map_normal_boluses_bounds_dose_but_keeps_zero():
    base = _load("normal_boluses.json")[0]
    # Above the single-dose bound: corrupt/unit-confused, rejected.
    assert mapper.map_normal_boluses([{**base, "insulinDelivered": 950.0}]) == []
    # bool must not become a 1.0 U dose; NaN slips through </> bounds.
    assert mapper.map_normal_boluses([{**base, "insulinDelivered": True}]) == []
    assert mapper.map_normal_boluses([{**base, "insulinDelivered": float("nan")}]) == []
    # Zero stays ingestible for pumps: a suggested bolus fully reduced by IoB
    # records 0 delivered while still carrying the meal's carb/BG context.
    zero = mapper.map_normal_boluses([{**base, "insulinDelivered": 0}])
    assert len(zero) == 1
    assert zero[0].units == 0.0


def test_map_context_and_basal_fields_reject_bool_and_nan():
    bolus = _load("normal_boluses.json")[0]
    # A bool context field must become None, not 1.0/True-as-number.
    mapped = mapper.map_normal_boluses(
        [
            {
                **bolus,
                "insulinOnBoard": True,
                "carbsInput": True,
                "bloodGlucoseInput": True,
            }
        ]
    )[0]
    assert mapped.iob_at_event is None
    assert mapped.cob_at_event is None
    assert mapped.bg_at_event is None

    basal = _load("scheduled_basals.json")[0]
    # rate=True must not become a 1.0 U/h basal; NaN rate is corrupt.
    assert mapper.map_scheduled_basals([{**basal, "rate": True}]) == []
    assert mapper.map_scheduled_basals([{**basal, "rate": float("nan")}]) == []
    # A NaN duration must drop the duration, not crash the mapper (int(nan) raises).
    nan_duration = mapper.map_scheduled_basals([{**basal, "duration": float("nan")}])[0]
    assert nan_duration.duration_minutes is None


def test_map_glooko_combines_all_series():
    rec = mapper.map_glooko(
        cgm_points=_load("cgm_points.json"),
        scheduled_basals=_load("scheduled_basals.json"),
        normal_boluses=_load("normal_boluses.json"),
        events=_load("events.json"),
        insulins=_load("insulins.json"),
    )
    assert len(rec.glucose) == 5
    # basals + boluses + events + pen insulins
    assert len(rec.pump_events) == 2 + 2 + 4 + 2


def test_map_pump_ts_refuses_missing_offset():
    # No offset -> cannot resolve a local wall-time to UTC -> record dropped (not misdated).
    out = mapper.map_scheduled_basals(
        [{"pumpTimestamp": "2023-03-30T19:10:26.000Z", "rate": 0.5, "guid": "g"}]
    )
    assert out == []


def test_map_honors_soft_deleted():
    # A record the user deleted in Glooko must not be ingested.
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
