"""Extract BATTERY / RESERVOIR / BASAL pump_events from Nightscout devicestatus.

Real Loop / AAPS / Trio / oref0 don't post Nightscout `treatments` for
pump telemetry (battery percent, reservoir level, the loop's enacted
basal rate). They post that data inside the per-cycle devicestatus
record's `pump`, `loop.enacted`, and `openaps.suggested` subtrees.

The dashboard's pump-status widget (`get_latest_pump_status` in
`tandem_sync.py`) reads from `pump_events` filtered by event_type
BATTERY / RESERVOIR / BASAL. Without this extractor those rows
were never written for Nightscout-sourced data, so the widget
showed nothing for any Loop / AAPS / Trio / oref0 user.

This module also annotates `iob_at_event` / `cob_at_event` /
`bg_at_event` onto each emitted BATTERY row, taken from the same
devicestatus's `loop.iob.iob` / `loop.cob.cob` (and equivalents).
That gives `get_last_iob` (in iob_projection.py) an authoritative
anchor so it doesn't fall back to summing recent dose units --
which under our emulator's compressed time produced wildly inflated
IoB readings (29 U vs. the real ~3-5 U).

Dedupe rules:
- Emit a row only when the value changed from the most-recently-
  emitted value of that same type.
- AND only when at least `_MIN_INTERVAL_SECONDS` have elapsed since
  the most-recent row of that type (defends against value oscillation
  hammering the table).
- "Most-recent" spans both the in-batch state (built up while we
  walk this batch) and the pre-batch DB state (passed in via the
  `last_state` dict).

ns_id is suffixed per type so multiple events from one devicestatus
have distinct ns_ids and the per-source unique index works:
`<devicestatus_id>:battery`, `<devicestatus_id>:reservoir`,
`<devicestatus_id>:basal`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from src.models.pump_data import PumpEventType
from src.services.integrations.nightscout.models import NightscoutDeviceStatus

# Minimum time between consecutive rows of the same type for the
# same user. Even if a value oscillates (battery flickering between
# two reads, basal rate flapping), we cap at one row per minute per
# type. This is a bug-fence, not a freshness guarantee -- the upper
# bound on row volume is 60 rows/hour/type.
_MIN_INTERVAL_SECONDS = 60.0

# Per-type epsilon for the value-change comparison. Battery comes
# in as int so equality is exact. Basal rate is set by the loop
# algorithm in clean increments. Reservoir is the only one where
# uploaders may emit slightly different floats for the "same"
# reading (`145.5` vs `145.5000000001`); a tiny epsilon prevents
# float-drift from triggering unnecessary inserts.
_VALUE_EPSILON = {
    "battery": 0.0,  # int-valued, exact equality safe
    "reservoir": 0.05,  # one-tenth of a unit; tighter than uploader rounding
    "basal": 0.0,  # loop chooses clean rates, exact equality safe
}


class _LastEmittedRow(TypedDict, total=False):
    """One slot in the carry-over state passed across batches."""

    value: float
    timestamp: datetime


# Keyed by event_type name ("battery", "reservoir", "basal").
LastEmittedState = dict[str, _LastEmittedRow]


def empty_last_state() -> LastEmittedState:
    """Initial state when no prior rows exist in the DB."""
    return {}


def _parse_created_at(value: str | None) -> datetime | None:
    if not value:
        return None
    s = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _should_emit(
    event_kind: str,
    new_value: float,
    new_ts: datetime,
    last_state: LastEmittedState,
) -> bool:
    """Apply value-change AND min-interval gates for one event type."""
    last = last_state.get(event_kind)
    if last is None:
        # First time we've ever seen this event_kind for this user --
        # always emit so the dashboard has an anchor immediately.
        return True
    last_value = last.get("value")
    last_ts = last.get("timestamp")
    if last_value is None or last_ts is None:
        return True
    epsilon = _VALUE_EPSILON.get(event_kind, 0.0)
    if abs(new_value - last_value) <= epsilon:
        return False
    return (new_ts - last_ts).total_seconds() >= _MIN_INTERVAL_SECONDS


def _extract_loop_enacted_rate(ds: NightscoutDeviceStatus) -> float | None:
    """Loop's `loop.enacted.rate` carries the most recent enacted temp.

    Returns None when:
    - There's no `loop` subtree (oref0 / AAPS-only payload)
    - There's no `enacted` (loop.failureReason path)
    - `enacted.rate` is missing or non-numeric
    """
    if not ds.loop:
        return None
    enacted = ds.loop.get("enacted")
    if not isinstance(enacted, dict):
        return None
    rate = enacted.get("rate")
    if isinstance(rate, int | float) and not isinstance(rate, bool):
        return float(rate)
    return None


def _extract_cob_value(ds: NightscoutDeviceStatus) -> float | None:
    """Pull COB out of whichever subtree carries it.

    Mirrors `_devicestatus_mapper._extract_cob` but inlined here to
    avoid a cross-module dependency on a private helper.
    """
    if ds.loop and isinstance(ds.loop.get("cob"), dict):
        v = ds.loop["cob"].get("cob")
        if isinstance(v, int | float) and not isinstance(v, bool):
            return float(v)
    if ds.openaps:
        suggested = ds.openaps.get("suggested")
        if isinstance(suggested, dict):
            v = suggested.get("COB")
            if isinstance(v, int | float) and not isinstance(v, bool):
                return float(v)
        iob_subtree = ds.openaps.get("iob")
        if isinstance(iob_subtree, dict):
            v = iob_subtree.get("cob")
            if isinstance(v, int | float) and not isinstance(v, bool):
                return float(v)
    return None


def extract_pump_events_from_devicestatuses(
    devicestatuses: list[NightscoutDeviceStatus],
    *,
    user_id: str,
    source: str,
    last_state: LastEmittedState,
    received_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Walk a chronologically-sorted batch of devicestatuses, emit
    pump_events for BATTERY / RESERVOIR / BASAL with dedupe.

    Mutates `last_state` in place so the caller can carry the
    final state back to the DB or to a subsequent batch.

    Each emitted BATTERY row also carries `iob_at_event` /
    `cob_at_event` from the same devicestatus, so a single row
    serves both the pump-status widget and the IoB-anchor query.

    Returns the list of pump_event row dicts, ready to bulk-insert
    via translator._upsert_pump_events.
    """
    received = received_at or datetime.now(UTC)
    rows: list[dict[str, Any]] = []

    for ds in devicestatuses:
        if not ds.id:
            # Without a server-assigned _id we can't form a stable
            # ns_id for dedupe across re-syncs. Skip rather than
            # invent one.
            continue
        ts = _parse_created_at(ds.created_at)
        if ts is None:
            continue

        battery_pct = ds.pump_battery_percent
        reservoir_units = ds.pump_reservoir
        basal_rate = _extract_loop_enacted_rate(ds)
        iob_value = ds.iob_value
        cob_value = _extract_cob_value(ds)

        if battery_pct is not None and _should_emit(
            "battery", float(battery_pct), ts, last_state
        ):
            rows.append(
                {
                    "user_id": user_id,
                    "event_type": PumpEventType.BATTERY,
                    "event_timestamp": ts,
                    "received_at": received,
                    "source": source,
                    "ns_id": f"{ds.id}:battery",
                    "units": float(battery_pct),
                    # IoB / COB / BG context attached here so the
                    # dashboard's `get_last_iob` query has an anchor
                    # without us creating a separate event row just
                    # for that purpose.
                    "iob_at_event": iob_value,
                    "cob_at_event": cob_value,
                    # Convention from `integrations.py:1347`: for
                    # BATTERY events, `is_automated` stores the
                    # uploader's `isCharging` flag. Coerce None to
                    # False so the NOT-NULL column constraint passes
                    # when uploaders don't report charging state.
                    "is_automated": bool(ds.is_charging)
                    if ds.is_charging is not None
                    else False,
                }
            )
            last_state["battery"] = {"value": float(battery_pct), "timestamp": ts}

        if reservoir_units is not None and _should_emit(
            "reservoir", float(reservoir_units), ts, last_state
        ):
            rows.append(
                {
                    "user_id": user_id,
                    "event_type": PumpEventType.RESERVOIR,
                    "event_timestamp": ts,
                    "received_at": received,
                    "source": source,
                    "ns_id": f"{ds.id}:reservoir",
                    "units": float(reservoir_units),
                    # Status reading, not an action -- always False.
                    "is_automated": False,
                }
            )
            last_state["reservoir"] = {
                "value": float(reservoir_units),
                "timestamp": ts,
            }

        if basal_rate is not None and _should_emit("basal", basal_rate, ts, last_state):
            rows.append(
                {
                    "user_id": user_id,
                    "event_type": PumpEventType.BASAL,
                    "event_timestamp": ts,
                    "received_at": received,
                    "source": source,
                    "ns_id": f"{ds.id}:basal",
                    "units": basal_rate,
                    # `loop.enacted` is by definition automated.
                    "is_automated": True,
                }
            )
            last_state["basal"] = {"value": basal_rate, "timestamp": ts}

    return rows


async def fetch_initial_last_state(
    session, user_id: str, *, source: str
) -> LastEmittedState:
    """Query the DB for the most recent BATTERY / RESERVOIR / BASAL
    rows for this user AND this NS connection's source string, so a
    fresh sync's first devicestatus respects the 1-min min-interval
    against any pre-existing rows.

    Filters on `source` so a user running both a direct integration
    (Tandem cloud writes BATTERY rows with `source = "tandem"`,
    `ns_id IS NULL`) AND a Nightscout connection doesn't seed the
    NS-side dedupe state from cross-source rows. Without this filter,
    a Tandem row written 30s ago would suppress a legitimate NS-side
    BATTERY row, and the value-change comparison would be against a
    value the NS uploader never saw.

    Imported lazily by the translator to keep this module
    SQLAlchemy-free at the unit-test boundary -- the extractor proper
    is pure and trivially testable, the DB lookup lives in a
    separate function.
    """
    from sqlalchemy import desc, select

    from src.models.pump_data import PumpEvent

    state: LastEmittedState = {}
    type_to_kind = {
        PumpEventType.BATTERY: "battery",
        PumpEventType.RESERVOIR: "reservoir",
        PumpEventType.BASAL: "basal",
    }
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    for et, kind in type_to_kind.items():
        stmt = (
            select(PumpEvent.units, PumpEvent.event_timestamp)
            .where(
                PumpEvent.user_id == user_id,
                PumpEvent.source == source,
                PumpEvent.event_type == et,
                PumpEvent.event_timestamp >= cutoff,
            )
            .order_by(desc(PumpEvent.event_timestamp))
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.first()
        if row and row[0] is not None:
            state[kind] = {"value": float(row[0]), "timestamp": row[1]}
    return state
