"""Per-connection Nightscout sync.

Drives the four translator entry points against a single
`NightscoutConnection`. Used by:

- The manual `POST /api/integrations/nightscout/{id}/sync` endpoint
  (Story 43.4 AC10) so a user can pull "now" from the UI.
- The Story 43.4 background scheduler (`run_nightscout_sync_all_users`)
  which calls this once per due connection on each tick.

`since` semantics:
- First sync (no `last_synced_at`): default backfill window from
  `initial_sync_window_days` (0 = unbounded for entries/treatments;
  always capped at 30 days for devicestatus to bound blast radius).
- Subsequent syncs: `last_synced_at` (timezone-aware UTC).

`last_synced_at` advancement: only on full success (all four
translate calls returned without raising). On any partial failure the
status / error are recorded but the cursor stays put so the next run
re-fetches the same window. Documented + tested in `test_sync.py`.

Exception mapping:
- NightscoutAuthError              -> AUTH_FAILED
- NightscoutRateLimitError         -> RATE_LIMITED
- NightscoutNetworkError           -> NETWORK
- NightscoutValidationError / etc. -> ERROR
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.encryption import decrypt_credential
from src.logging_config import get_logger
from src.models.nightscout_connection import (
    NightscoutConnection,
    NightscoutSyncStatus,
)
from src.services.integrations.nightscout.client import NightscoutClient
from src.services.integrations.nightscout.errors import (
    NightscoutAuthError,
    NightscoutError,
    NightscoutNetworkError,
    NightscoutRateLimitError,
)
from src.services.integrations.nightscout.translator import (
    TranslateOutcome,
    translate_devicestatuses,
    translate_entries,
    translate_profile,
    translate_treatments,
)

logger = get_logger(__name__)

# Cap the devicestatus initial backfill regardless of
# `initial_sync_window_days` — high-volume tables on busy uploaders
# can have tens of thousands of rows per day.
_DEVICESTATUS_INITIAL_CAP_DAYS = 30

# Per-connection in-flight guard. Two concurrent sync calls for the
# same connection (manual button + scheduler tick, or two browser tabs)
# would both fetch the same window upstream, double the API calls, and
# race on cursor writes. Translators are dedupe-safe via the partial
# unique indexes, but the wasted I/O and last_sync_error flapping is
# real. The lock is process-local (one API replica) and held only for
# the duration of one sync; cross-replica concurrency is bounded by
# the scheduler tick spacing in Story 43.4.
#
# Entries are evicted opportunistically when the lock is released and
# no one else is waiting on it (see `_release_lock`), so the dict size
# tracks "currently-syncing connections" rather than "every connection
# ever seen by this worker."
_in_flight_locks: dict[uuid.UUID, asyncio.Lock] = {}


def _lock_for(connection_id: uuid.UUID) -> asyncio.Lock:
    lock = _in_flight_locks.get(connection_id)
    if lock is None:
        lock = asyncio.Lock()
        _in_flight_locks[connection_id] = lock
    return lock


def _release_lock(connection_id: uuid.UUID, lock: asyncio.Lock) -> None:
    """Drop the lock entry if no one else is contending for it.

    Called after we exit the `async with` block. `lock.locked()` is
    False at this point (we just released). If `_waiters` is empty,
    no other task is queued for it and we can let the entry go.
    A subsequent call to `_lock_for` will lazily re-create one.
    """
    waiters = getattr(lock, "_waiters", None)
    if not waiters:
        _in_flight_locks.pop(connection_id, None)


@dataclass(frozen=True)
class SyncResult:
    """Outcome of a single connection sync."""

    connection_id: str
    status: NightscoutSyncStatus
    entries_inserted: int
    entries_skipped: int
    entries_failed: int
    treatments_inserted_pump: int
    treatments_inserted_glucose: int
    treatments_failed: int
    devicestatuses_inserted: int
    devicestatuses_failed: int
    profile_synced: bool
    duration_ms: int
    error: str | None


def _resolve_since(
    last_synced_at: datetime | None,
    initial_sync_window_days: int,
    now: datetime,
    *,
    cap_days: int | None = None,
) -> datetime | None:
    """Pick the `since` cursor for one fetch call.

    - If we have a `last_synced_at`, use it as the lower bound.
    - Otherwise, this is the first sync; fall back to
      `now - initial_sync_window_days` (0 means "unbounded").
    - `cap_days`: if the chosen window is older than this many days,
      clamp to it. Used for devicestatus to bound blast radius.
    """
    if last_synced_at is not None:
        return last_synced_at
    if initial_sync_window_days <= 0 and cap_days is None:
        return None
    days = initial_sync_window_days if initial_sync_window_days > 0 else cap_days
    if cap_days is not None and (days is None or days > cap_days):
        days = cap_days
    if days is None:
        return None
    return now - timedelta(days=days)


def _classify_exception(exc: BaseException) -> NightscoutSyncStatus:
    if isinstance(exc, NightscoutAuthError):
        return NightscoutSyncStatus.AUTH_FAILED
    if isinstance(exc, NightscoutRateLimitError):
        return NightscoutSyncStatus.RATE_LIMITED
    if isinstance(exc, NightscoutNetworkError):
        return NightscoutSyncStatus.NETWORK
    return NightscoutSyncStatus.ERROR


async def sync_nightscout_for_connection(
    session: AsyncSession,
    conn: NightscoutConnection,
) -> SyncResult:
    """Pull-and-translate one connection's data into the canonical tables.

    **Session ownership**: this function takes exclusive ownership of
    the passed session for its lifetime and commits before returning.
    Callers must NOT have other pending writes staged on the same
    session; the manual-sync endpoint hands in a request-scoped
    session that's only used here, and the Story 43.4 scheduler
    opens a fresh per-connection session for the same reason.

    **Exception handling**: NightscoutError is classified into a
    NightscoutSyncStatus and surfaced via the result + connection row.
    `asyncio.CancelledError` / `SystemExit` / `KeyboardInterrupt`
    propagate so the runtime can shut down or cancel cleanly. Any
    other exception is logged with traceback and recorded as ERROR
    -- this swallow is intentional so the scheduler's per-row
    isolation holds and one buggy connection doesn't kill the tick.

    **Concurrency**: a per-connection asyncio lock prevents two
    concurrent sync calls (e.g. manual button + scheduler tick) from
    racing on the cursor and doubling upstream API load. Within one
    process; cross-replica concurrency is bounded by scheduler tick
    spacing in Story 43.4.
    """
    lock = _lock_for(conn.id)
    async with lock:
        try:
            return await _do_sync(session, conn)
        finally:
            _release_lock(conn.id, lock)


async def _do_sync(session: AsyncSession, conn: NightscoutConnection) -> SyncResult:
    started = time.monotonic()
    now = datetime.now(UTC)
    user_id_str = str(conn.user_id)
    connection_id_str = str(conn.id)
    last_synced = conn.last_synced_at
    window_days = conn.initial_sync_window_days

    entries_outcome = TranslateOutcome()
    pump_outcome = TranslateOutcome()
    glucose_from_treatments_outcome = TranslateOutcome()
    devicestatus_outcome = TranslateOutcome()
    profile_synced = False
    error_msg: str | None = None
    status = NightscoutSyncStatus.OK

    try:
        async with await NightscoutClient.create(
            base_url=conn.base_url,
            auth_type=conn.auth_type,
            credential=decrypt_credential(conn.encrypted_credential),
            api_version=conn.api_version,
        ) as client:
            entries = await client.fetch_entries(
                since=_resolve_since(last_synced, window_days, now)
            )
            treatments = await client.fetch_treatments(
                since=_resolve_since(last_synced, window_days, now)
            )
            devicestatuses = await client.fetch_devicestatus(
                since=_resolve_since(
                    last_synced,
                    window_days,
                    now,
                    cap_days=_DEVICESTATUS_INITIAL_CAP_DAYS,
                )
            )
            profiles = await client.fetch_profile()

        entries_outcome = await translate_entries(
            entries,
            session=session,
            user_id=user_id_str,
            connection_id=connection_id_str,
        )
        pump_outcome, glucose_from_treatments_outcome = await translate_treatments(
            treatments,
            session=session,
            user_id=user_id_str,
            connection_id=connection_id_str,
        )
        devicestatus_outcome = await translate_devicestatuses(
            devicestatuses,
            session=session,
            user_id=user_id_str,
            connection_id=connection_id_str,
        )
        if profiles:
            await translate_profile(
                profiles[0],
                session=session,
                user_id=user_id_str,
                connection_id=connection_id_str,
            )
            profile_synced = True

    except NightscoutError as exc:
        status = _classify_exception(exc)
        error_msg = str(exc)
        logger.warning(
            "nightscout_sync_failed",
            connection_id=connection_id_str,
            user_id=user_id_str,
            status=status.value,
            error=error_msg,
        )
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        # Cooperative shutdown / cancellation must propagate so the
        # runtime can drain cleanly. We do NOT update the connection
        # row in this case -- the next sync will re-evaluate.
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced via SyncResult
        status = NightscoutSyncStatus.ERROR
        error_msg = str(exc)
        logger.exception(
            "nightscout_sync_unexpected_error",
            connection_id=connection_id_str,
            user_id=user_id_str,
        )

    # Persist status + (only on success) advance the cursor.
    conn.last_sync_status = status
    conn.last_sync_error = error_msg
    if status == NightscoutSyncStatus.OK:
        conn.last_synced_at = now
    await session.commit()

    duration_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "nightscout_sync_completed",
        connection_id=connection_id_str,
        user_id=user_id_str,
        status=status.value,
        entries_inserted=entries_outcome.inserted,
        entries_skipped=entries_outcome.skipped,
        treatments_inserted=pump_outcome.inserted
        + glucose_from_treatments_outcome.inserted,
        devicestatuses_inserted=devicestatus_outcome.inserted,
        profile_synced=profile_synced,
        duration_ms=duration_ms,
    )

    return SyncResult(
        connection_id=connection_id_str,
        status=status,
        entries_inserted=entries_outcome.inserted,
        entries_skipped=entries_outcome.skipped,
        entries_failed=entries_outcome.failed,
        treatments_inserted_pump=pump_outcome.inserted,
        treatments_inserted_glucose=glucose_from_treatments_outcome.inserted,
        # `translate_treatments` returns two outcomes (pump rows + glucose
        # rows for fingerstick treatments). Sum both failure counts so a
        # parser failure on a fingerstick treatment isn't silently dropped.
        treatments_failed=pump_outcome.failed + glucose_from_treatments_outcome.failed,
        devicestatuses_inserted=devicestatus_outcome.inserted,
        devicestatuses_failed=devicestatus_outcome.failed,
        profile_synced=profile_synced,
        duration_ms=duration_ms,
        error=error_msg,
    )
