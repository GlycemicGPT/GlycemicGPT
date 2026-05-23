"""Persist mapped CareLink records into glucose_readings + pump_events.

Batched, idempotent bulk upserts using the same conflict targets the other
direct integrations use:
- glucose: ``ON CONFLICT (user_id, reading_timestamp) DO NOTHING`` (as Dexcom)
- pump events: ``ON CONFLICT (user_id, event_timestamp, event_type) WHERE
  ns_id IS NULL DO NOTHING`` (as Tandem)

so re-importing an overlapping range is safe. Rows are de-duplicated on those
keys within each batch first, so a single multi-row INSERT can't hit an
intra-statement conflict.

Timezone note: CareLink CSV timestamps are naive *pump-local* time (the export
carries no offset). Localizing them to UTC correctly requires the user's
timezone and is the orchestrator's responsibility (it knows the account). This
layer defensively coerces any naive timestamp to UTC so it never writes NULL
into the timezone-aware columns -- but callers should pass already-localized
aware datetimes for correct absolute times.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.glucose import GlucoseReading, TrendDirection
from src.models.pump_data import PumpEvent

from .carelink_mapper import MappedRecords

_CHUNK = 500


@dataclass
class CareLinkStoreResult:
    glucose_fetched: int = 0
    glucose_stored: int = 0
    events_fetched: int = 0
    events_stored: int = 0


def _aware(ts: datetime) -> datetime:
    # CareLink timestamps are pump-LOCAL; the sync layer (sync._localize)
    # attaches the user's zone before storage. A naive timestamp here would be
    # local time, and silently calling replace(tzinfo=UTC) would misdate it by
    # the user's offset -- for a medical data path we fail fast instead.
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(
            "CareLink timestamps must be timezone-aware before storage "
            "(sync._localize attaches the user's timezone)"
        )
    return ts.astimezone(UTC)


async def store_carelink_records(
    db: AsyncSession,
    user_id: uuid.UUID,
    records: MappedRecords,
    *,
    now: datetime | None = None,
) -> CareLinkStoreResult:
    """Upsert mapped glucose readings + pump events for a user. Idempotent."""
    now = now or datetime.now(UTC)
    result = CareLinkStoreResult(
        glucose_fetched=len(records.glucose), events_fetched=len(records.pump_events)
    )

    # --- Glucose readings: dedupe on reading_timestamp, keep first ---
    glucose_by_ts: dict[datetime, dict] = {}
    for g in records.glucose:
        ts = _aware(g.timestamp)
        if ts in glucose_by_ts:
            continue
        glucose_by_ts[ts] = {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "value": g.value_mgdl,
            "reading_timestamp": ts,
            # CareLink CSV has no trend arrow; we don't fabricate one.
            "trend": TrendDirection.NOT_COMPUTABLE,
            "received_at": now,
            "source": g.source,
        }
    g_rows = list(glucose_by_ts.values())
    for start in range(0, len(g_rows), _CHUNK):
        stmt = (
            insert(GlucoseReading)
            .values(g_rows[start : start + _CHUNK])
            .on_conflict_do_nothing(index_elements=["user_id", "reading_timestamp"])
        )
        res = await db.execute(stmt)
        result.glucose_stored += max(res.rowcount, 0)

    # --- Pump events: dedupe on (event_timestamp, event_type), keep first ---
    events_by_key: dict[tuple, dict] = {}
    for e in records.pump_events:
        ts = _aware(e.timestamp)
        key = (ts, e.event_type)
        if key in events_by_key:
            continue
        events_by_key[key] = {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "event_type": e.event_type,
            "event_timestamp": ts,
            "units": e.units,
            "duration_minutes": e.duration_minutes,
            "is_automated": e.is_automated,
            "control_iq_reason": e.control_iq_reason,
            "iob_at_event": e.iob_at_event,
            "cob_at_event": e.cob_at_event,
            "bg_at_event": e.bg_at_event,
            "received_at": now,
            "source": e.source,
        }
    e_rows = list(events_by_key.values())
    for start in range(0, len(e_rows), _CHUNK):
        stmt = (
            insert(PumpEvent)
            .values(e_rows[start : start + _CHUNK])
            .on_conflict_do_nothing(
                index_elements=["user_id", "event_timestamp", "event_type"],
                index_where=text("ns_id IS NULL"),
            )
        )
        res = await db.execute(stmt)
        result.events_stored += max(res.rowcount, 0)

    await db.commit()
    return result
