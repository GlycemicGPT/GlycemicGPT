"""Orchestrate a CareLink sync: fetch CSV -> parse -> map -> store.

Ties the four data-pipeline layers together for one user + date range. Takes a
ready :class:`CareLinkClient` (the caller builds it with the auth/session, so
this stays decoupled from -- and testable without -- the session-capture flow).

Timezone: CareLink CSV times are naive *pump-local*. ``tz`` is REQUIRED so we
never silently store local times as UTC (which would misdate every event by
the user's offset). Pass a ``zoneinfo.ZoneInfo`` (an IANA zone like
``America/Chicago``), NOT a fixed-offset ``timezone(...)`` -- a historical
import can span DST changes, and only a real zone localizes each timestamp
with the correct offset for its own date.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, tzinfo

from sqlalchemy.ext.asyncio import AsyncSession

from .carelink_csv import parse_carelink_csv
from .carelink_mapper import MappedRecords, map_carelink_export
from .client import CareLinkClient
from .storage import store_carelink_records


@dataclass
class CareLinkSyncResult:
    patient_id: str
    start_date: date
    end_date: date
    glucose_fetched: int
    glucose_stored: int
    events_fetched: int
    events_stored: int


def _localize(records: MappedRecords, tz: tzinfo) -> None:
    """Attach ``tz`` to naive timestamps in place (pump-local -> aware)."""
    for g in records.glucose:
        if g.timestamp.tzinfo is None:
            g.timestamp = g.timestamp.replace(tzinfo=tz)
    for e in records.pump_events:
        if e.timestamp.tzinfo is None:
            e.timestamp = e.timestamp.replace(tzinfo=tz)


async def sync_carelink_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    start_date: date,
    end_date: date,
    client: CareLinkClient,
    tz: tzinfo,
) -> CareLinkSyncResult:
    """Export [start_date, end_date] from CareLink, parse + map + store it.

    ``tz`` is the user's timezone (use a ZoneInfo for DST-correctness across a
    historical range). Idempotent end to end (storage upserts on the natural
    keys), so an overlapping re-sync is safe.
    """
    patient_id = await client.get_patient_id()
    csv_text = await client.export_csv(
        patient_id=patient_id,
        start_date=start_date,
        end_date=end_date,
        client_time=datetime.now(tz),  # local time so date edges resolve right
    )
    records = map_carelink_export(parse_carelink_csv(csv_text))
    _localize(records, tz)
    stored = await store_carelink_records(db, user_id, records)
    return CareLinkSyncResult(
        patient_id=patient_id,
        start_date=start_date,
        end_date=end_date,
        glucose_fetched=stored.glucose_fetched,
        glucose_stored=stored.glucose_stored,
        events_fetched=stored.events_fetched,
        events_stored=stored.events_stored,
    )
