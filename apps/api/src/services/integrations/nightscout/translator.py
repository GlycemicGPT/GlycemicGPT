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
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.device_status_snapshot import DeviceStatusSnapshot
from src.models.forecast_snapshot import ForecastSnapshot
from src.models.glucose import GlucoseReading
from src.models.nightscout_profile_snapshot import NightscoutProfileSnapshot
from src.models.pump_data import PumpEvent
from src.services.integrations.nightscout._devicestatus_mapper import (
    map_devicestatus_to_snapshot,
)
from src.services.integrations.nightscout._forecast_mapper import (
    map_devicestatus_to_forecast,
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
from src.services.integrations.nightscout._pump_status_extractor import (
    extract_pump_events_from_devicestatuses,
    fetch_initial_last_state,
)
from src.services.integrations.nightscout.models import (
    NIGHTSCOUT_SOURCE_PREFIX,
    NightscoutDeviceStatus,
    NightscoutEntry,
    NightscoutProfile,
    NightscoutTreatment,
)
from src.services.pump_event_dedupe import compute_pump_event_dedupe_hash

logger = get_logger(__name__)

# Sentinel for `sorted()` on devicestatus batches when `created_at`
# is missing -- avoids TypeError from comparing datetime with str ""
# in Python 3. ISO-format string sorts before any real timestamp.
_NULL_CREATED_AT_SENTINEL = (
    datetime.min.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
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
    return f"{NIGHTSCOUT_SOURCE_PREFIX}{connection_id}"


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
    """Translate raw devicestatus dicts to device_status_snapshots upserts.

    Also extracts BATTERY / RESERVOIR / BASAL pump_events from each
    devicestatus's `pump.battery.percent` / `pump.reservoir` /
    `loop.enacted.rate`. Without that promotion, the dashboard's
    pump-status widget (which reads pump_events filtered by event_type)
    never sees Nightscout-sourced telemetry, even though the data was
    correctly stored in `device_status_snapshots`. The pump_events
    rows are deduped per-type with a 1-min min-interval guard.

    The `inserted` / `skipped` / `failed` counts in the returned
    outcome reflect the **devicestatus_snapshots** insert outcome
    only. The pump_events spawned alongside are best-effort -- a
    failure there is logged via the broader exception path but does
    not change the snapshot count, since the snapshots are the
    authoritative store.
    """
    received = received_at or datetime.now(UTC)
    snapshot_rows: list[dict[str, Any]] = []
    parsed: list[NightscoutDeviceStatus] = []
    failed = 0
    skipped = 0

    for raw in raw_devicestatuses:
        try:
            ds = NightscoutDeviceStatus.model_validate(raw)
        except Exception:
            failed += 1
            continue
        parsed.append(ds)
        row = map_devicestatus_to_snapshot(
            ds,
            user_id=user_id,
            nightscout_connection_id=connection_id,
            received_at=received,
        )
        if row is None:
            skipped += 1
            continue
        snapshot_rows.append(row)

    inserted = await _upsert_devicestatus_snapshots(session, snapshot_rows)
    skipped += len(snapshot_rows) - inserted

    # Extract closed-loop forecasts (Loop / AAPS / Trio / oref0 / iAPS)
    # to `forecast_snapshots`. Best-effort, isolated in its own
    # SAVEPOINT for the same reasons as the pump-events promotion
    # below: a forecast-side error must NOT roll back the
    # devicestatus_snapshots inserts that already landed, nor block
    # the pump-events promotion that follows. Skip the work entirely
    # when no devicestatus parsed -- avoids an empty SAVEPOINT.
    if parsed:
        forecast_rows: list[dict[str, Any]] = []
        for ds in parsed:
            row = map_devicestatus_to_forecast(
                ds,
                user_id=user_id,
                nightscout_connection_id=connection_id,
                received_at=received,
            )
            if row is not None:
                forecast_rows.append(row)
        if forecast_rows:
            try:
                async with session.begin_nested():
                    await _upsert_forecast_snapshots(session, forecast_rows)
            except Exception:
                logger.exception(
                    "nightscout_forecast_promotion_failed",
                    extra={
                        "user_id": user_id,
                        "connection_id": connection_id,
                    },
                )

    # Promote pump telemetry to pump_events for dashboard widgets.
    # Best-effort: a failure here logs + swallows so the snapshots
    # outcome (already computed above) is still returned. Sort
    # chronologically so the dedupe walk produces the right
    # value-change decisions across the batch -- NS doesn't
    # guarantee response ordering. Sort by the wire string (also a
    # str when present) and fall back to a low sentinel for missing
    # timestamps; both paths produce a string so Python 3 doesn't
    # raise TypeError on mixed-type comparison.
    parsed_sorted = sorted(
        parsed,
        key=lambda ds: ds.created_at or _NULL_CREATED_AT_SENTINEL,
    )
    source = _build_source(connection_id)
    # Wrap pump-event promotion in a SAVEPOINT so a DB-level error
    # here (constraint violation, connection hiccup, schema drift)
    # rolls back ONLY the pump-events work. Without the savepoint,
    # asyncpg + SQLAlchemy leave the underlying connection in
    # NEEDS_ROLLBACK state and the outer caller's `commit()` would
    # either silently roll back the already-inserted snapshots or
    # raise PendingRollbackError -- breaking the documented
    # "snapshot count is preserved on pump-events failure" contract.
    try:
        async with session.begin_nested():
            last_state = await fetch_initial_last_state(session, user_id, source=source)
            pump_event_rows = extract_pump_events_from_devicestatuses(
                parsed_sorted,
                user_id=user_id,
                source=source,
                last_state=last_state,
                received_at=received,
            )
            if pump_event_rows:
                # The (source, ns_id) partial unique index dedupes
                # duplicates at the DB level via ON CONFLICT DO NOTHING,
                # so a concurrent sync race (manual trigger + scheduler
                # tick on the same connection both reading the same
                # `last_state` snapshot) is caught at the storage
                # layer; we don't need a row lock.
                await _upsert_pump_events(session, pump_event_rows)
            # Now that the just-fetched devicestatus snapshots are in
            # DB, backfill IoB / COB context onto NS-sourced bolus
            # rows from the nearest preceding snapshot. Bounded to the
            # last 14 days so old boluses don't get retroactive
            # rewrites every sync.
            await _backfill_bolus_context(
                session,
                user_id=user_id,
                source=source,
                cutoff=received - timedelta(days=14),
            )
    except Exception:
        # The promotion is opportunistic: snapshots are the
        # authoritative store and have already landed. Don't let a
        # transient failure here mask the snapshot outcome.
        logger.exception(
            "nightscout_pump_events_promotion_failed",
            extra={"user_id": user_id, "connection_id": connection_id},
        )

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

    SQLAlchemy 2.x rejects `.values(rows)` when the dicts have
    mismatched keys -- bolus rows lack `duration_minutes`, temp-basal
    rows have it, and the multi-row VALUES clause renders missing
    columns as bound parameters that the dialect won't bind. We
    normalize to a uniform key set before inserting so each mapper
    can keep returning the slim type-specific dict it built.
    """
    if not rows:
        return 0
    for row in rows:
        # Cross-source dedupe (Story 43.11): a Loop/AAPS treatment relayed
        # through Nightscout collapses against the same physical bolus
        # delivered by a direct integration (Tandem cloud, mobile BLE).
        # The bare ON CONFLICT DO NOTHING below already arbitrates on the
        # `(user_id, dedupe_hash)` partial unique index.
        #
        # Rows that are half of a split meal-bolus pair (they carry a
        # `meal_event_id` linking the bolus to its sibling carb row) opt
        # OUT: if the bolus half collapsed against a direct-integration
        # bolus, the carb half (units=None, never hashed) would survive
        # with a dangling `meal_event_id` pointing at a row that was never
        # inserted. Keeping meal-paired boluses out of the cross-source
        # collapse preserves carb<->insulin pairing; same-source re-import
        # is still deduped by the `(source, ns_id)` index.
        if row.get("meal_event_id") is not None:
            row["dedupe_hash"] = None
            continue
        row["dedupe_hash"] = compute_pump_event_dedupe_hash(
            user_id=row["user_id"],
            event_type=row["event_type"],
            event_timestamp=row["event_timestamp"],
            units=row.get("units"),
            duration_minutes=row.get("duration_minutes"),
        )
    rows = _normalize_row_shapes(rows)
    stmt = (
        insert(PumpEvent).values(rows).on_conflict_do_nothing().returning(PumpEvent.id)
    )
    result = await session.execute(stmt)
    return len(result.scalars().all())


async def _backfill_bolus_context(
    session: AsyncSession,
    *,
    user_id: str,
    source: str,
    cutoff: datetime,
) -> int:
    """Copy IoB / COB context from the nearest preceding devicestatus
    snapshot onto bolus / correction pump_events that don't have it.

    Why this exists: Loop / AAPS / Trio post boluses as treatments
    WITHOUT in-band IoB / COB context -- that data lives in the
    per-cycle devicestatus posted around the same time. Without
    correlating, the dashboard's `Recent Boluses` table (which reads
    `iob_at_event` / `cob_at_event` / `bg_at_event` directly off the
    pump_event row) renders those columns as `---` for every NS-
    sourced bolus.

    Bounded by:
    - `source` -- only this NS connection's rows
    - `cutoff` -- caller-supplied lower bound (usually 14 days ago);
      old historical boluses don't get retroactive context updates.
    - 15-minute snapshot window -- if no devicestatus was posted
      within 15 min before the bolus we can't reasonably correlate
      and `iob_at_event` stays NULL (the table cell renders `---`).

    Runs after `_upsert_devicestatus_snapshots` so the just-inserted
    snapshots are visible to the join. Should be called inside the
    pump-events SAVEPOINT so a failure here doesn't poison the
    snapshot insert.

    Returns the number of rows updated.
    """
    stmt = text(  # nosemgrep: avoid-sqlalchemy-text
        """
        UPDATE pump_events AS pe
        SET iob_at_event = ds.iob_units,
            cob_at_event = ds.cob_grams
        FROM device_status_snapshots AS ds
        WHERE pe.user_id = :user_id
          AND pe.source = :source
          AND pe.event_type IN ('bolus', 'correction')
          AND pe.iob_at_event IS NULL
          AND pe.event_timestamp >= :cutoff
          AND ds.user_id = pe.user_id
          AND ds.snapshot_timestamp <= pe.event_timestamp
          AND ds.snapshot_timestamp >= pe.event_timestamp - INTERVAL '15 minutes'
          -- Pick the nearest preceding snapshot via anti-join: this
          -- row's snapshot_timestamp is the maximum within the
          -- 15-min window before the bolus.
          AND NOT EXISTS (
              SELECT 1 FROM device_status_snapshots AS ds2
              WHERE ds2.user_id = pe.user_id
                AND ds2.snapshot_timestamp <= pe.event_timestamp
                AND ds2.snapshot_timestamp >= pe.event_timestamp - INTERVAL '15 minutes'
                AND ds2.snapshot_timestamp > ds.snapshot_timestamp
          )
        """
    )
    result = await session.execute(
        stmt,
        {
            "user_id": user_id,
            "source": source,
            "cutoff": cutoff,
        },
    )
    return result.rowcount or 0


def _normalize_row_shapes(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pad each dict so every row has the same key set.

    Missing keys default to None. We don't assume any particular set
    of "expected" columns -- we just take the union of whatever the
    mappers produced. New mapper outputs (future event types,
    additional context fields) work without touching this function.
    """
    all_keys: set[str] = set()
    for r in rows:
        all_keys.update(r.keys())
    return [{k: r.get(k) for k in all_keys} for r in rows]


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


async def _upsert_forecast_snapshots(
    session: AsyncSession, rows: list[dict[str, Any]]
) -> int:
    """Bulk-insert forecast snapshots with ON CONFLICT DO NOTHING.

    Unique on `(source_engine, dedupe_key)` -- re-translating the same
    devicestatus across sync cycles produces the same row and the
    constraint dedupes it.

    DO NOTHING (not DO UPDATE) is the current conservative choice: we
    treat a forecast as immutable once issued. If an upstream uploader
    (e.g., AAPS V3's edit-and-re-upload flow) rewrites a devicestatus
    body in-place, our row keeps the original contents. This trade-off
    favors stable provenance (deferred scoring job sees the original
    forecast that was actually live at issue time) over freshness.
    Revisit if production shows real same-key churn -- the deferred
    `forecast_evaluations` scoring job would benefit from observability
    on such cases.

    `received_at` is set in the mapper at row-build time. On dedupe
    skip, the new `received_at` value is lost (the original row's
    value remains). Acceptable trade-off; would matter only if a
    future "last seen at" telemetry view requires per-sync receipt
    timestamps.
    """
    if not rows:
        return 0
    stmt = (
        insert(ForecastSnapshot)
        .values(rows)
        .on_conflict_do_nothing()
        .returning(ForecastSnapshot.id)
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
