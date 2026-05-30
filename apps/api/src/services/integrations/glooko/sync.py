"""Autonomous Glooko (Omnipod Cloud Sync) sync orchestrator.

Ties the pieces together for one user, one cycle:

    decrypt email/password               [core.encryption]
        -> web Devise login -> session   [auth.glooko_login]
        -> keyset-cursor pump streams +  [client.GlookoClient.fetch_stream]
           date-windowed CGM points      [client.GlookoClient.fetch_cgm_points]
        -> map -> MappedRecords          [mapper.map_glooko]
        -> upsert glucose + pump events  [storage.store_glooko_records]

and updates the user's ``GlookoSyncState`` (freshness, status, error, cumulative
counter, advanced per-stream cursor, CGM high-water mark) -- committing the mapped
records and the state row in a SINGLE final commit so a crash can't leave data
stored with the status not yet flipped to connected.

Two entry points share the per-user lock and the decrypt/login/error machinery:

  * ``sync_glooko_for_user`` -- the incremental tick (scheduler + manual "Sync
    now"). Resumes each pump stream from its stored keyset cursor and the CGM
    path from ``last_cgm_window_end``; advances both and bumps ``last_sync_at``.
  * ``import_glooko_history_for_user`` -- the one-time historical backfill
    (Milestone D's import endpoint). Paginates each pump stream from the epoch
    under a page budget and walks the CGM path back over a bounded window. It does
    NOT touch the incremental cursors or ``last_sync_at`` -- it fills the past, it
    doesn't make the connection fresher (Tandem #669 import-doesn't-bump lesson).

The Glooko session cookie is ephemeral (re-minted on 401 via the reauth callback),
so unlike the Medtronic refresh token there is nothing rotating to lose mid-cycle;
the single final commit is about glucose/state atomicity, not credential safety.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.encryption import decrypt_credential
from src.logging_config import get_logger
from src.models.glooko_sync_state import (
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    STATUS_ERROR,
    GlookoSyncState,
)

from .auth import GlookoSession, glooko_login, resolve_region
from .client import ZERO_GUID, GlookoClient
from .errors import GlookoAuthError, GlookoNetworkError, GlookoSyncError
from .mapper import map_glooko
from .storage import GlookoStoreResult, store_glooko_records

logger = get_logger(__name__)

# Pump streams this orchestrator ingests: scheduled basal, normal bolus, and
# pod-lifecycle/suspend events -- the three the mapper translates today.
# Intentionally deferred (the client can fetch them, but ``mapper`` has no
# translation yet, so syncing them would just discard the records):
#   * ``extended_boluses`` -- square/dual-wave bolus modeling (follow-up story).
#   * ``modes`` / ``alarms`` -- informational, not part of the glucose/insulin model.
# Tracked as Epic 47 follow-ups (see the Milestone F "help wanted" issues); add the
# stream here together with its mapper support, never one without the other.
SYNC_PUMP_STREAMS = ("scheduled_basals", "normal_boluses", "events")

# --- Incremental tuning ---
# First incremental sync (no stored cursor) pulls only the recent window so a
# freshly connected user's first tick isn't an implicit full-history backfill --
# that is the explicit one-time import's job.
_INITIAL_PUMP_LOOKBACK_DAYS = 7
_INITIAL_CGM_LOOKBACK_DAYS = 7
# Overlap the CGM window on each tick so a reading uploaded late (after the prior
# window closed) isn't missed. Safe to re-fetch: glucose dedupes on timestamp.
_CGM_OVERLAP_MINUTES = 30
# Page budget per stream per incremental tick. Bounds a catch-up sync after a
# long outage; the cursor persists between ticks so the rest drains next time.
_INCREMENTAL_MAX_PAGES = 10

# --- One-time import tuning ---
# Generous page budget so a single import drains full history (the stream
# terminates at ``lastPage`` first); the budget is only a runaway safety cap.
_IMPORT_MAX_PAGES = 200
# CGM backfill: how far back to walk and the per-request window size. graph/data
# is date-windowed, so we chunk to keep each request modest.
_IMPORT_CGM_DAYS = 90
_IMPORT_CGM_WINDOW_DAYS = 30


# Per-user in-flight locks. A manual "Sync now" / "Import" and the scheduled tick
# can fire for the same user concurrently; without serialization they race on the
# state row (cursors, counters) and lose updates. In-process only -- multi-replica
# overlap is a known cross-vendor follow-up (mirrors Medtronic/Nightscout).
_in_flight_locks: dict[uuid.UUID, asyncio.Lock] = {}


def _lock_for(user_id: uuid.UUID) -> asyncio.Lock:
    lock = _in_flight_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _in_flight_locks[user_id] = lock
    return lock


def _release_lock(user_id: uuid.UUID, lock: asyncio.Lock) -> None:
    """Drop the lock entry when no one else is queued for it.

    Called from the ``finally`` *inside* ``async with lock`` (we still hold the
    lock here, mirroring the Medtronic sibling), so ``lock.locked()`` is always
    True and can't tell "idle" from "held by me" -- hence the ``_waiters`` check.
    It's a CPython ``asyncio.Lock`` internal, but it's the established
    cross-vendor pattern (see the Medtronic + Nightscout siblings); a shared
    per-user-lock util is the tracked cross-vendor cleanup, not this PR's scope.
    Empty waiters -> no other task is queued -> the entry can go (a later
    ``_lock_for`` lazily re-creates one), so the dict tracks "currently syncing"
    rather than every user this worker has ever seen.
    """
    if not getattr(lock, "_waiters", None):
        _in_flight_locks.pop(user_id, None)


class GlookoSyncRunError(Exception):
    """A Glooko sync/import cycle failed (after the state row was updated)."""


@dataclass
class GlookoSyncResult:
    glucose_fetched: int = 0
    glucose_stored: int = 0
    events_fetched: int = 0
    events_stored: int = 0


def _iso_z(dt: datetime) -> str:
    """Format an instant as a millisecond ISO-Z string (graph/data window param)."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _cgm_window(last_end: datetime | None, now: datetime) -> tuple[datetime, datetime]:
    """Incremental CGM window: from the stored high-water mark (minus overlap) to now."""
    if last_end is None:
        start = now - timedelta(days=_INITIAL_CGM_LOOKBACK_DAYS)
    else:
        start = _aware(last_end) - timedelta(minutes=_CGM_OVERLAP_MINUTES)
    return start, now


def _result_from_store(store: GlookoStoreResult) -> GlookoSyncResult:
    return GlookoSyncResult(
        glucose_fetched=store.glucose_fetched,
        glucose_stored=store.glucose_stored,
        events_fetched=store.events_fetched,
        events_stored=store.events_stored,
    )


async def _decrypt_creds_or_disconnect(
    db: AsyncSession, state: GlookoSyncState
) -> tuple[str, str, str]:
    """Decrypt + validate the stored connection config, or mark disconnected.

    A bad region or credentials the current key can't decrypt is a PERMANENT
    failure -- retrying every tick would flood logs/Sentry forever. So mark the
    row ``disconnected`` (the scheduler's discovery query then skips it; recovery
    is re-connecting, which re-encrypts under the current key) and raise. This is
    the decrypt-flood guard (Epic 47 Milestone C AC4).
    """
    try:
        region = state.region
        resolve_region(region)  # ValueError on an unknown/out-of-allowlist region
        email = decrypt_credential(state.encrypted_email)
        password = decrypt_credential(state.encrypted_password)
    except ValueError as e:
        state.status = STATUS_DISCONNECTED
        state.last_error = f"Invalid stored connection data: {e}"
        await db.commit()
        raise GlookoSyncRunError(f"Glooko stored data invalid: {e}") from e
    return region, email, password


def _persist_patient_ids(state: GlookoSyncState, session: GlookoSession) -> None:
    if session.patient_slug:
        state.patient_slug = session.patient_slug
    if session.patient_oid:
        state.patient_oid = session.patient_oid


# ---------------------------------------------------------------------------
# Incremental sync
# ---------------------------------------------------------------------------
async def sync_glooko_for_user(
    db: AsyncSession,
    state: GlookoSyncState,
    *,
    now: datetime | None = None,
) -> GlookoSyncResult:
    """Run one incremental sync cycle for ``state`` under a per-user lock."""
    lock = _lock_for(state.user_id)
    async with lock:
        try:
            return await _sync_glooko_for_user_locked(db, state, now=now)
        finally:
            _release_lock(state.user_id, lock)


# A fetch plan: given an open client, retrieve ``(pump stream_records, cgm_points)``.
# The incremental and import paths differ ONLY in this callback (cursor source +
# CGM window) and in which state fields they bump afterwards -- everything else
# (decrypt, login, map, store, failure handling) is the shared spine below.
FetchPlan = Callable[
    ["GlookoClient"], Awaitable[tuple[dict[str, list[dict]], list[dict]]]
]


async def _execute_cycle(
    db: AsyncSession,
    state: GlookoSyncState,
    now: datetime,
    fetch: FetchPlan,
) -> GlookoStoreResult:
    """Decrypt -> login -> ``fetch`` -> map -> store(commit=False). Shared spine.

    Returns the store result for the caller to fold into a final commit alongside
    its own state-field updates. On any failure, stamps the state row via
    ``_mark_failure`` and raises ``GlookoSyncRunError`` (so callers never reach
    their success-path state writes).
    """
    region, email, password = await _decrypt_creds_or_disconnect(db, state)

    async def _reauth() -> GlookoSession:
        return await glooko_login(email, password, region)

    try:
        session = await glooko_login(email, password, region)
        _persist_patient_ids(state, session)
        async with GlookoClient(session, reauth=_reauth) as client:
            stream_records, cgm_points = await fetch(client)
        records = map_glooko(
            cgm_points=cgm_points,
            scheduled_basals=stream_records.get("scheduled_basals"),
            normal_boluses=stream_records.get("normal_boluses"),
            events=stream_records.get("events"),
        )
        return await store_glooko_records(
            db, state.user_id, records, now=now, commit=False
        )
    except Exception as e:
        raise await _mark_failure(db, state, e) from e


async def _sync_glooko_for_user_locked(
    db: AsyncSession,
    state: GlookoSyncState,
    *,
    now: datetime | None = None,
) -> GlookoSyncResult:
    now = now or datetime.now(UTC)
    state.last_attempt_at = now

    initial_pump_cursor = _iso_z(now - timedelta(days=_INITIAL_PUMP_LOOKBACK_DAYS))
    # Mutated by the fetch plan, read back after a successful cycle. Copy so the
    # reassignment below is a genuine change SQLAlchemy flushes (JSONB footgun).
    cursors: dict[str, dict[str, str]] = dict(state.stream_cursors or {})
    cgm_start, cgm_end = _cgm_window(state.last_cgm_window_end, now)

    async def _fetch(
        client: GlookoClient,
    ) -> tuple[dict[str, list[dict]], list[dict]]:
        stream_records: dict[str, list[dict]] = {}
        for stream in SYNC_PUMP_STREAMS:
            cur = cursors.get(stream) or {}
            page = await client.fetch_stream(
                stream,
                last_updated_at=cur.get("last_updated_at") or initial_pump_cursor,
                last_guid=cur.get("last_guid") or ZERO_GUID,
                max_pages=_INCREMENTAL_MAX_PAGES,
            )
            stream_records[stream] = page.records
            cursors[stream] = {
                "last_updated_at": page.last_updated_at,
                "last_guid": page.last_guid,
            }
        cgm_points = await client.fetch_cgm_points(_iso_z(cgm_start), _iso_z(cgm_end))
        return stream_records, cgm_points

    store = await _execute_cycle(db, state, now, _fetch)

    state.status = STATUS_CONNECTED
    state.last_sync_at = now
    state.last_error = None
    state.stream_cursors = cursors
    state.last_cgm_window_end = cgm_end
    state.readings_synced_total += store.glucose_stored
    await db.commit()

    logger.info(
        "Glooko sync completed",
        user_id=str(state.user_id),
        glucose_fetched=store.glucose_fetched,
        glucose_stored=store.glucose_stored,
        events_fetched=store.events_fetched,
        events_stored=store.events_stored,
    )
    return _result_from_store(store)


# ---------------------------------------------------------------------------
# One-time historical import
# ---------------------------------------------------------------------------
async def import_glooko_history_for_user(
    db: AsyncSession,
    state: GlookoSyncState,
    *,
    now: datetime | None = None,
) -> GlookoSyncResult:
    """Run a one-time bounded historical backfill under the per-user lock.

    Does NOT bump ``last_sync_at`` / ``last_attempt_at`` or advance the
    incremental cursors -- it fills the past independently of the live sync.
    """
    lock = _lock_for(state.user_id)
    async with lock:
        try:
            return await _import_glooko_history_locked(db, state, now=now)
        finally:
            _release_lock(state.user_id, lock)


async def _import_glooko_history_locked(
    db: AsyncSession,
    state: GlookoSyncState,
    *,
    now: datetime | None = None,
) -> GlookoSyncResult:
    now = now or datetime.now(UTC)
    truncated: list[str] = []

    async def _fetch(
        client: GlookoClient,
    ) -> tuple[dict[str, list[dict]], list[dict]]:
        stream_records: dict[str, list[dict]] = {}
        for stream in SYNC_PUMP_STREAMS:
            # Defaults = epoch + zero-UUID -> full history from the start.
            page = await client.fetch_stream(stream, max_pages=_IMPORT_MAX_PAGES)
            stream_records[stream] = page.records
            if not page.last_page:
                truncated.append(stream)
        cgm_points = await _import_cgm_points(client, now)
        return stream_records, cgm_points

    store = await _execute_cycle(db, state, now, _fetch)

    # Import proves the credentials work, so clear any stale error and surface a
    # connected status -- but leave last_sync_at / cursors / CGM high-water mark
    # untouched (they belong to the incremental path).
    state.status = STATUS_CONNECTED
    state.last_error = None
    state.readings_synced_total += store.glucose_stored
    await db.commit()

    if truncated:
        logger.info(
            "Glooko import hit the page budget; older history not fetched",
            user_id=str(state.user_id),
            streams=truncated,
            max_pages=_IMPORT_MAX_PAGES,
        )
    logger.info(
        "Glooko historical import completed",
        user_id=str(state.user_id),
        glucose_stored=store.glucose_stored,
        events_stored=store.events_stored,
    )
    return _result_from_store(store)


async def _import_cgm_points(client: GlookoClient, now: datetime) -> list[dict]:
    """Walk the CGM path back over a bounded window in fixed-size chunks."""
    points: list[dict] = []
    window_end = now
    earliest = now - timedelta(days=_IMPORT_CGM_DAYS)
    while window_end > earliest:
        window_start = max(
            earliest, window_end - timedelta(days=_IMPORT_CGM_WINDOW_DAYS)
        )
        points.extend(
            await client.fetch_cgm_points(_iso_z(window_start), _iso_z(window_end))
        )
        window_end = window_start
    return points


# ---------------------------------------------------------------------------
# Shared failure handling
# ---------------------------------------------------------------------------
async def _mark_failure(
    db: AsyncSession, state: GlookoSyncState, exc: BaseException
) -> GlookoSyncRunError:
    """Stamp the state row for a failed cycle and return the wrapped error to raise.

    Distinguishes a permanent auth failure (mark ``disconnected`` so the scheduler
    stops retrying a hopeless credential) from a transient network error (mark
    ``error`` -- the scheduler retries next interval). The catch-all best-effort
    commits so a bookkeeping/transient DB error can't escape unwrapped.

    Returns (rather than raises) the ``GlookoSyncRunError`` so the caller's
    ``raise ... from e`` keeps an honest traceback and the call site reads as the
    failure path it is.
    """
    if isinstance(exc, GlookoAuthError):
        state.status = STATUS_DISCONNECTED
        state.last_error = str(exc)
        await db.commit()
        return GlookoSyncRunError(f"Glooko auth failed: {exc}")
    if isinstance(exc, GlookoNetworkError):
        state.status = STATUS_ERROR
        state.last_error = str(exc)
        await db.commit()
        return GlookoSyncRunError(f"Glooko sync transient failure: {exc}")
    if isinstance(exc, (GlookoSyncError, ValueError)):
        state.status = STATUS_ERROR
        state.last_error = str(exc)
        await db.commit()
        return GlookoSyncRunError(f"Glooko sync failed: {exc}")
    # Unexpected (e.g. a transient DB/network error during store). Best-effort
    # commit of the error state; if the commit itself failed, roll back and still
    # surface the original failure.
    state.status = STATUS_ERROR
    state.last_error = f"Unexpected error: {exc}"
    try:
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
    return GlookoSyncRunError(f"Glooko sync failed unexpectedly: {exc}")
