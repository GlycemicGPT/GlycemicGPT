"""Nightscout translator -- orchestrates input parsing + ORM upserts.

Public entry points:
- `translate_entries()` -- list of raw entry dicts -> count of glucose
  reading rows upserted
- `translate_treatments()` -- list of raw treatment dicts -> counts of
  glucose-reading + pump-event rows upserted
- `translate_devicestatuses()` -- list of raw devicestatus dicts ->
  count of snapshot rows upserted
- `translate_profile()` -- raw profile dict -> True/False (snapshot
  upserted, or skipped because the profile has no active store)

All four entry points:
1. Validate input via the Pydantic input models (PR1's parsers)
2. Route via per-target mappers (per-mapper module under this package)
3. Issue PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` upserts via
   the connection's user_id and a per-target dedupe key

Source attribution: every persisted row carries
`source = "nightscout:<connection_id>"` at the table level. Sub-
attribution (uploader, raw device string, raw enteredBy string) lives
in `metadata_json` for pump_events; for glucose_readings we rely on
the table-level `source` column alone (uploader sub-attribution is
recoverable by joining back to the connection's recent treatments if
needed).

Conflict resolution semantics:

- Same source, same `ns_id`: re-fetch is a no-op (per-source partial
  unique index dedupes).
- Cross-source on glucose_readings (`user_id`, `reading_timestamp`):
  ON CONFLICT DO NOTHING keeps whichever was inserted first. Direct
  integrations (Tandem cloud, etc.) typically write before the
  Nightscout sync runs, so in practice they win the race -- but this
  is **first-writer-wins, not enforced priority**. A Nightscout-only
  user gets Nightscout-attributed rows; a user with both has whichever
  source ran first per timestamp.
- Cross-source on pump_events: the pre-existing
  `(user_id, event_timestamp, event_type)` unique index now applies
  only WHERE `ns_id IS NULL` (i.e. to direct-integration rows).
  Nightscout-sourced rows dedupe via the partial unique index on
  `(source, ns_id) WHERE ns_id IS NOT NULL`. This avoids the bug where
  two AAPS SMBs at the same second would silently drop one.

`received_at` is set on insert and is **not** updated on conflict --
think of it as `first_received_at`. There is currently no
`last_observed_at` column; if a downstream consumer needs to know when
we last re-saw a record, that's a follow-up.

Soft-delete propagation is **not yet implemented**: when an upstream
record is soft-deleted (`isValid: false`) on Nightscout, the input
model returns `semantic_kind == "unknown"` and the translator drops
the record on the parse side. A pre-existing row in our DB with the
same `ns_id` is left in place. Tracked as a known limitation; needs
either an `is_retracted` column or DELETE-on-soft-delete logic.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.device_status_snapshot import DeviceStatusSnapshot
from src.models.glucose import GlucoseReading
from src.models.nightscout_profile_snapshot import NightscoutProfileSnapshot
from src.models.pump_data import PumpEvent
from src.services.integrations.nightscout._devicestatus_mapper import (
    map_devicestatus_to_snapshot,
)
from src.services.integrations.nightscout._glucose_mapper import (
    map_bg_check_treatment_to_glucose_reading,
    map_entry_to_glucose_reading,
)
from src.services.integrations.nightscout._profile_mapper import (
    map_profile_to_snapshot,
)
from src.services.integrations.nightscout._pump_events_mapper import (
    map_treatment_to_pump_events,
)
from src.services.integrations.nightscout.models import (
    NightscoutDeviceStatus,
    NightscoutEntry,
    NightscoutProfile,
    NightscoutTreatment,
)


@dataclass(frozen=True)
class TranslateOutcome:
    """Counts of rows upserted by a single translate_* call.

    Inserted = newly written. Skipped = duplicate (caught by the
    ON CONFLICT clause) OR rejected by the mapper (gap reading,
    soft-delete, missing timestamp, etc.). Failed = caller-visible
    parser failure (the input dict couldn't be coerced into the
    Pydantic model at all).
    """

    inserted: int = 0
    skipped: int = 0
    failed: int = 0

    def __add__(self, other: TranslateOutcome) -> TranslateOutcome:
        return TranslateOutcome(
            inserted=self.inserted + other.inserted,
            skipped=self.skipped + other.skipped,
            failed=self.failed + other.failed,
        )


def _build_source(connection_id: str) -> str:
    """Build the `source` column value for this connection."""
    return f"nightscout:{connection_id}"


# ---------------------------------------------------------------------------
# Entries -> glucose_readings
# ---------------------------------------------------------------------------


async def translate_entries(
    raw_entries: Iterable[dict[str, Any]],
    *,
    session: AsyncSession,
    user_id: str,
    connection_id: str,
    received_at: datetime | None = None,
) -> TranslateOutcome:
    """Translate raw Nightscout entry dicts to glucose_readings upserts."""
    source = _build_source(connection_id)
    received = received_at or datetime.now(UTC)

    rows: list[dict[str, Any]] = []
    failed = 0
    skipped = 0

    for raw in raw_entries:
        try:
            entry = NightscoutEntry.model_validate(raw)
        except Exception:
            failed += 1
            continue
        row = map_entry_to_glucose_reading(
            entry,
            user_id=user_id,
            source=source,
            received_at=received,
        )
        if row is None:
            skipped += 1
            continue
        rows.append(row)

    inserted = await _upsert_glucose_readings(session, rows)
    # Anything in `rows` that didn't insert lost the ON CONFLICT race
    # to a prior write -- count it as skipped.
    skipped += len(rows) - inserted
    return TranslateOutcome(inserted=inserted, skipped=skipped, failed=failed)


# ---------------------------------------------------------------------------
# Treatments -> pump_events (+ glucose_readings for fingerstick path)
# ---------------------------------------------------------------------------


async def translate_treatments(
    raw_treatments: Iterable[dict[str, Any]],
    *,
    session: AsyncSession,
    user_id: str,
    connection_id: str,
    received_at: datetime | None = None,
) -> tuple[TranslateOutcome, TranslateOutcome]:
    """Translate raw Nightscout treatment dicts.

    Returns a (pump_events_outcome, glucose_readings_outcome) pair.
    The fingerstick BG-Check path writes to glucose_readings; all
    other treatment kinds write to pump_events.
    """
    source = _build_source(connection_id)
    received = received_at or datetime.now(UTC)

    pump_rows: list[dict[str, Any]] = []
    glucose_rows: list[dict[str, Any]] = []
    pump_skipped = 0
    glucose_skipped = 0
    failed = 0

    for raw in raw_treatments:
        try:
            treatment = NightscoutTreatment.model_validate(raw)
        except Exception:
            failed += 1
            continue

        if treatment.is_fingerstick_treatment:
            row = map_bg_check_treatment_to_glucose_reading(
                treatment,
                user_id=user_id,
                source=source,
                received_at=received,
            )
            if row is None:
                glucose_skipped += 1
            else:
                glucose_rows.append(row)
            continue

        events = map_treatment_to_pump_events(
            treatment,
            user_id=user_id,
            source=source,
            received_at=received,
        )
        if not events:
            pump_skipped += 1
            continue
        pump_rows.extend(events)

    pump_inserted = await _upsert_pump_events(session, pump_rows)
    pump_skipped += len(pump_rows) - pump_inserted

    glucose_inserted = await _upsert_glucose_readings(session, glucose_rows)
    glucose_skipped += len(glucose_rows) - glucose_inserted

    return (
        TranslateOutcome(inserted=pump_inserted, skipped=pump_skipped, failed=failed),
        TranslateOutcome(inserted=glucose_inserted, skipped=glucose_skipped, failed=0),
    )


# ---------------------------------------------------------------------------
# Devicestatus -> device_status_snapshots
# ---------------------------------------------------------------------------


async def translate_devicestatuses(
    raw_devicestatuses: Iterable[dict[str, Any]],
    *,
    session: AsyncSession,
    user_id: str,
    connection_id: str,
    received_at: datetime | None = None,
) -> TranslateOutcome:
    """Translate raw devicestatus dicts to device_status_snapshots upserts."""
    received = received_at or datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    failed = 0
    skipped = 0

    for raw in raw_devicestatuses:
        try:
            ds = NightscoutDeviceStatus.model_validate(raw)
        except Exception:
            failed += 1
            continue
        row = map_devicestatus_to_snapshot(
            ds,
            user_id=user_id,
            nightscout_connection_id=connection_id,
            received_at=received,
        )
        if row is None:
            skipped += 1
            continue
        rows.append(row)

    inserted = await _upsert_devicestatus_snapshots(session, rows)
    skipped += len(rows) - inserted
    return TranslateOutcome(inserted=inserted, skipped=skipped, failed=failed)


# ---------------------------------------------------------------------------
# Profile -> nightscout_profile_snapshots (one row per connection, upsert)
# ---------------------------------------------------------------------------


async def translate_profile(
    raw_profile: dict[str, Any],
    *,
    session: AsyncSession,
    user_id: str,
    connection_id: str,
    fetched_at: datetime | None = None,
) -> bool:
    """Translate a raw Nightscout profile to a snapshot upsert.

    Returns True when a row was inserted or updated; False when the
    profile was skipped (no active store or parse failure).
    """
    try:
        profile = NightscoutProfile.model_validate(raw_profile)
    except Exception:
        return False

    row = map_profile_to_snapshot(
        profile,
        user_id=user_id,
        nightscout_connection_id=connection_id,
        fetched_at=fetched_at or datetime.now(UTC),
    )
    if row is None:
        return False
    await _upsert_profile_snapshot(session, row)
    return True


# ---------------------------------------------------------------------------
# Upsert helpers (per-target)
# ---------------------------------------------------------------------------


async def _upsert_glucose_readings(
    session: AsyncSession, rows: list[dict[str, Any]]
) -> int:
    """Bulk-insert glucose readings with ON CONFLICT DO NOTHING.

    Two unique constraints can hit:
    1. `ix_glucose_readings_user_reading` on (user_id, reading_timestamp)
       -- catches cross-source duplicates (Tandem direct + Nightscout-
       relayed at same timestamp).
    2. `ix_glucose_readings_source_nsid` on (source, ns_id) WHERE
       ns_id IS NOT NULL -- catches re-fetch of the same NS record
       across sync cycles.

    Either constraint firing means the row is a duplicate; skip it.
    Uses `RETURNING id` to count actual inserts because
    `result.rowcount` is not reliable under ON CONFLICT DO NOTHING
    across drivers (asyncpg returns -1 / None for various edge cases
    and SQLAlchemy explicitly documents rowcount as unreliable here).
    """
    if not rows:
        return 0
    stmt = (
        insert(GlucoseReading)
        .values(rows)
        .on_conflict_do_nothing()
        .returning(GlucoseReading.id)
    )
    result = await session.execute(stmt)
    return len(result.scalars().all())


async def _upsert_pump_events(session: AsyncSession, rows: list[dict[str, Any]]) -> int:
    """Bulk-insert pump events with ON CONFLICT DO NOTHING.

    Uses RETURNING to count actual inserts (rowcount is unreliable
    under ON CONFLICT DO NOTHING).
    """
    if not rows:
        return 0
    stmt = (
        insert(PumpEvent).values(rows).on_conflict_do_nothing().returning(PumpEvent.id)
    )
    result = await session.execute(stmt)
    return len(result.scalars().all())


async def _upsert_devicestatus_snapshots(
    session: AsyncSession, rows: list[dict[str, Any]]
) -> int:
    """Bulk-insert devicestatus snapshots with ON CONFLICT DO NOTHING.

    Per-connection unique on (nightscout_connection_id, ns_id). Uses
    RETURNING to count actual inserts.
    """
    if not rows:
        return 0
    stmt = (
        insert(DeviceStatusSnapshot)
        .values(rows)
        .on_conflict_do_nothing()
        .returning(DeviceStatusSnapshot.id)
    )
    result = await session.execute(stmt)
    return len(result.scalars().all())


async def _upsert_profile_snapshot(session: AsyncSession, row: dict[str, Any]) -> None:
    """Upsert a single profile snapshot (one per user+connection).

    Unlike the other upserts, profile snapshots use ON CONFLICT DO
    UPDATE because the wizard wants the latest values, not the first.
    Re-fetching the same connection's profile must overwrite.
    """
    update_cols = {
        "fetched_at": row["fetched_at"],
        "source_default_profile_name": row["source_default_profile_name"],
        "source_units": row["source_units"],
        "source_timezone": row["source_timezone"],
        "source_dia_hours": row["source_dia_hours"],
        "source_start_date": row["source_start_date"],
        "basal_segments": row["basal_segments"],
        "carb_ratio_segments": row["carb_ratio_segments"],
        "sensitivity_segments": row["sensitivity_segments"],
        "target_low_segments": row["target_low_segments"],
        "target_high_segments": row["target_high_segments"],
        "profile_json_full": row["profile_json_full"],
    }
    stmt = (
        insert(NightscoutProfileSnapshot)
        .values(row)
        .on_conflict_do_update(
            index_elements=["user_id", "nightscout_connection_id"],
            set_=update_cols,
        )
    )
    await session.execute(stmt)
