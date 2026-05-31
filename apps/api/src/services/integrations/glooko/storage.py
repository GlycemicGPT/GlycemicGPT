"""Persist mapped Glooko records into glucose_readings + pump_events. Idempotent.

Conflict targets match the existing per-source dedupe indexes so overlapping
continuous-sync and one-time-import windows are safe to re-run:

- glucose:   ``ON CONFLICT (user_id, reading_timestamp) DO NOTHING`` (graph/data
             CGM points carry no per-reading id, so the timestamp is the key).
- pump events that carry a Glooko ``guid``: ``ON CONFLICT (source, ns_id) WHERE
             ns_id IS NOT NULL DO NOTHING`` -- ``ns_id`` = the stable ``guid``, so
             two boluses in the same second never collide (the natural-key index
             would have dropped one). Any event without a guid falls back to the
             ``(user_id, event_timestamp, event_type) WHERE ns_id IS NULL`` index.

Rows are de-duplicated on those keys within each batch first so a single
multi-row INSERT can't hit an intra-statement conflict.

Timestamps must already be tz-aware UTC (the mapper resolves the pump local-time
+ offset footgun); we coerce to UTC defensively and refuse naive values rather
than risk misdating a medical record.
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

from .mapper import MappedRecords

_CHUNK = 500


@dataclass
class GlookoStoreResult:
    glucose_fetched: int = 0
    glucose_stored: int = 0
    events_fetched: int = 0
    events_stored: int = 0


def _aware(ts: datetime) -> datetime:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(
            "Glooko timestamps must be tz-aware before storage (mapper resolves UTC)"
        )
    return ts.astimezone(UTC)


async def store_glooko_records(
    db: AsyncSession,
    user_id: uuid.UUID,
    records: MappedRecords,
    *,
    now: datetime | None = None,
    commit: bool = True,
) -> GlookoStoreResult:
    """Upsert mapped glucose readings + pump events for a user. Idempotent.

    ``commit=False`` lets the caller fold this into a larger transaction (e.g. the
    scheduler commits records + the updated GlookoSyncState row atomically).
    """
    now = now or datetime.now(UTC)
    result = GlookoStoreResult(
        glucose_fetched=len(records.glucose), events_fetched=len(records.pump_events)
    )

    # --- Glucose: dedupe on reading_timestamp, keep first ---
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
            # graph/data carries no trend arrow; we don't fabricate one.
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
            # RETURNING yields one row per ACTUAL insert (conflicts return nothing),
            # so counting it is exact regardless of driver rowcount support.
            .returning(GlucoseReading.id)
        )
        res = await db.execute(stmt)
        result.glucose_stored += len(res.fetchall())

    # --- Pump events: split by whether they carry a Glooko guid (ns_id) ---
    with_guid: dict[str, dict] = {}
    without_guid: dict[tuple, dict] = {}
    for e in records.pump_events:
        ts = _aware(e.timestamp)
        row = {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "event_type": e.event_type,
            "event_timestamp": ts,
            "units": e.units,
            "duration_minutes": e.duration_minutes,
            "is_automated": e.is_automated,
            "iob_at_event": e.iob_at_event,
            "cob_at_event": e.cob_at_event,
            "bg_at_event": e.bg_at_event,
            "metadata_json": e.metadata_json,
            "received_at": now,
            "source": e.source,
            "ns_id": e.ns_id,
        }
        if e.ns_id:
            with_guid.setdefault(e.ns_id, row)
        else:
            without_guid.setdefault((ts, e.event_type), row)

    guid_rows = list(with_guid.values())
    for start in range(0, len(guid_rows), _CHUNK):
        stmt = (
            insert(PumpEvent)
            .values(guid_rows[start : start + _CHUNK])
            .on_conflict_do_nothing(
                index_elements=["source", "ns_id"],
                index_where=text("ns_id IS NOT NULL"),
            )
            .returning(PumpEvent.id)
        )
        res = await db.execute(stmt)
        result.events_stored += len(res.fetchall())

    natural_rows = list(without_guid.values())
    for start in range(0, len(natural_rows), _CHUNK):
        stmt = (
            insert(PumpEvent)
            .values(natural_rows[start : start + _CHUNK])
            .on_conflict_do_nothing(
                index_elements=["user_id", "event_timestamp", "event_type"],
                index_where=text("ns_id IS NULL"),
            )
            .returning(PumpEvent.id)
        )
        res = await db.execute(stmt)
        result.events_stored += len(res.fetchall())

    if commit:
        await db.commit()
    return result
