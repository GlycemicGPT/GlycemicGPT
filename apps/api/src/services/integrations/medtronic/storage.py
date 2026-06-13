"""Persist mapped CareLink records into glucose_readings + pump_events.

Batched, idempotent bulk upserts:
- glucose: ``ON CONFLICT (user_id, reading_timestamp) DO NOTHING`` (as Dexcom)
- pump events: a *bare* ``ON CONFLICT DO NOTHING`` (no explicit target) so a row
  is arbitrated against whichever partial unique index it violates: the
  natural-key ``(user_id, event_timestamp, event_type) WHERE ns_id IS NULL``
  (re-import idempotency, as Tandem) and the cross-source ``(user_id,
  dedupe_hash) WHERE dedupe_hash IS NOT NULL`` (Story 43.11 -- the same physical
  dose reported by CareLink AND relayed via Nightscout careportal collapses to
  one row instead of double-counting in IoB / TDD). A *targeted* clause would
  arbitrate only its named index and raise unique_violation on the other, so the
  bare form is required -- same mechanism Tandem sync, mobile push, the
  Nightscout translator, and Glooko use.

Re-importing an overlapping range is therefore safe. Rows are de-duplicated on
the natural key within each batch first, so a single multi-row INSERT can't hit
an intra-statement conflict; Postgres also collapses remaining within-statement
duplicates (incl. dedupe-hash near-matches) under DO NOTHING.

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

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.glucose import GlucoseReading, TrendDirection
from src.models.pump_data import PumpEvent
from src.services.pump_event_dedupe import compute_pump_event_dedupe_hash

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
    commit: bool = True,
) -> CareLinkStoreResult:
    """Upsert mapped glucose readings + pump events for a user. Idempotent.

    ``commit=False`` lets a caller fold this write into a larger transaction
    (e.g. the autonomous Connect sync commits the records and the updated
    connection-state row together, atomically). Defaults to committing so the
    manual CareLink import path is unchanged.
    """
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
            # RETURNING yields one row per ACTUAL insert (conflicts return
            # nothing), so the count is exact regardless of driver rowcount
            # support -- rowcount is unreliable under ON CONFLICT DO NOTHING.
            .returning(GlucoseReading.id)
        )
        res = await db.execute(stmt)
        result.glucose_stored += len(res.fetchall())

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
            # Cross-source dedupe key (Story 43.11): a CareLink dose collapses
            # against the same physical dose relayed via Nightscout careportal /
            # a direct integration. The helper returns None for non-delivery
            # events (suspend/resume, telemetry), so only BOLUS/CORRECTION/BASAL
            # rows participate in the index.
            "dedupe_hash": compute_pump_event_dedupe_hash(
                user_id=user_id,
                event_type=e.event_type,
                event_timestamp=ts,
                units=e.units,
                duration_minutes=e.duration_minutes,
            ),
        }
    e_rows = list(events_by_key.values())
    for start in range(0, len(e_rows), _CHUNK):
        # Bare ON CONFLICT DO NOTHING (see module docstring): a row may violate
        # the natural-key OR the (user_id, dedupe_hash) partial unique index, and
        # only the untargeted form skips a conflict on either rather than raising
        # unique_violation on the unnamed one. RETURNING gives a reliable insert
        # count -- rowcount is unreliable under ON CONFLICT DO NOTHING (asyncpg).
        stmt = (
            insert(PumpEvent)
            .values(e_rows[start : start + _CHUNK])
            .on_conflict_do_nothing()
            .returning(PumpEvent.id)
        )
        res = await db.execute(stmt)
        result.events_stored += len(res.fetchall())

    if commit:
        await db.commit()
    return result
