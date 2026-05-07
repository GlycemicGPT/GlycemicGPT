"""Story 43.4: Background Nightscout sync scheduler.

The single global APScheduler job ticks on `nightscout_sync_tick_interval_minutes`
(default 1 min) and scans `nightscout_connections` for rows whose
per-connection cadence has elapsed. Due connections are synced in
parallel (bounded by `_MAX_PARALLEL_SYNCS`) -- one slow upstream NS
instance does not block other users.

Why one global tick instead of one APScheduler job per connection:
- Matches the existing Dexcom / Tandem / research-scheduler pattern in
  this codebase.
- Settings changes (sync_interval_minutes) take effect at the next
  tick automatically; no `reschedule_job` plumbing needed.
- No job-lifecycle management on connection create / delete / soft-
  delete; the discovery query is the source of truth.

Per-connection isolation:
- Each connection gets its own DB session via the shared
  `get_session_maker()`.
- A bare `try/except Exception` per row so one malformed connection
  (corrupted credential, removed user, etc.) doesn't kill the tick.
- `asyncio.Semaphore` bounds parallelism so we don't open hundreds of
  upstream sockets simultaneously.

Concurrency:
- The scheduler decides "due" by reading `last_synced_at`. The
  per-connection asyncio lock in `sync.py` prevents this tick's
  sync from racing with a manual `POST /sync` triggered through
  the UI.
- With parallel syncs, individual connections complete at different
  wall-clock instants; that's fine since each has its own session
  and translator outcome is recorded per-row.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from src.database import get_session_maker
from src.logging_config import get_logger
from src.models.nightscout_connection import (
    SYNC_INTERVAL_MAX_MINUTES,
    SYNC_INTERVAL_MIN_MINUTES,
    NightscoutConnection,
    NightscoutSyncStatus,
)
from src.services.integrations.nightscout.sync import (
    sync_nightscout_for_connection,
)

logger = get_logger(__name__)


# Statuses that exclude a connection from polling. AUTH_FAILED requires
# user intervention (re-authenticate). Other failure modes (ERROR /
# NETWORK / RATE_LIMITED) still get retried on the next tick.
#
# UNREACHABLE is intentionally NOT in this set: the model defines it
# for a future "consecutive-failure circuit breaker" but no code path
# currently sets it. Including it here would be dead code dressed up
# as a working circuit breaker. When the breaker is wired (own PR),
# add UNREACHABLE here.
_PAUSED_STATUSES = frozenset({NightscoutSyncStatus.AUTH_FAILED})

# Bound concurrent upstream connections. Most users will have 1-2
# connections; this matters when many users have the same tick window.
# Each parallel slot opens its own DB session + httpx client, so we
# also indirectly bound DB-pool and FD pressure.
_MAX_PARALLEL_SYNCS = 8

# Hard ceiling on how long a single scheduler tick may spend in the
# parallel sync phase. APScheduler is configured with `coalesce=True`
# and `max_instances=1`, so a tick that runs longer than its base
# interval (default 60s) silently delays the next tick. This budget
# is the contract: at this many seconds, in-flight syncs are
# cancelled and the tick returns. The cancelled connections will be
# re-discovered as due on the next tick (their `last_synced_at` is
# only updated on success), so no data is lost.
#
# Set below the default 60s tick interval so even a maximally slow
# tick doesn't push past the next scheduled fire.
_TICK_WALL_BUDGET_SECONDS = 45.0


async def run_nightscout_sync_all_users() -> None:
    """One tick of the scheduler.

    Discovers all active connections that are due for a sync (per their
    own `sync_interval_minutes`), then syncs each in isolation, in
    parallel up to `_MAX_PARALLEL_SYNCS`.

    This function is the APScheduler callback. It must NOT raise --
    APScheduler would log + skip the next tick. The per-connection
    error handler in `_sync_one` ensures that.
    """
    started = datetime.now(UTC)

    # Discover phase -- single short-lived session, slim SELECT.
    # Pulling the encrypted_credential blob for every active connection
    # would waste bandwidth at 1000s of rows; the refetch inside
    # `_sync_one` will hydrate the full row only for due connections.
    session_maker = get_session_maker()
    async with session_maker() as session:
        result = await session.execute(
            select(
                NightscoutConnection.id,
                NightscoutConnection.user_id,
                NightscoutConnection.sync_interval_minutes,
                NightscoutConnection.last_synced_at,
            ).where(
                NightscoutConnection.is_active.is_(True),
                NightscoutConnection.last_sync_status.notin_(list(_PAUSED_STATUSES)),
            )
        )
        rows = result.all()

    due_ids: list[tuple[uuid.UUID, uuid.UUID]] = []
    for row in rows:
        interval = _clamped_interval(row.sync_interval_minutes)
        if _is_due(row.last_synced_at, interval, now=started):
            due_ids.append((row.id, row.user_id))

    if not due_ids:
        logger.debug("nightscout_scheduler_tick_no_due_connections")
        return

    logger.info(
        "nightscout_scheduler_tick_starting",
        due_count=len(due_ids),
    )

    # Bounded parallelism: many users with the same tick window
    # shouldn't open hundreds of upstream sockets at once, but a
    # single slow upstream MUST NOT block all the others either.
    sem = asyncio.Semaphore(_MAX_PARALLEL_SYNCS)

    async def _bounded(conn_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        async with sem:
            return await _sync_one(session_maker, conn_id, user_id)

    gather_started = datetime.now(UTC)
    try:
        statuses = await asyncio.wait_for(
            asyncio.gather(
                *(_bounded(cid, uid) for (cid, uid) in due_ids),
                return_exceptions=False,
            ),
            timeout=_TICK_WALL_BUDGET_SECONDS,
        )
    except TimeoutError:
        # Past the wall budget. Cancellation propagates to every
        # in-flight `_sync_one` via the gather; any partial DB writes
        # roll back when their session context exits. Each cancelled
        # connection's `last_synced_at` was not advanced, so the next
        # tick will pick it up again -- no data lost, just a missed
        # cycle. Don't raise: APScheduler would log + skip the next
        # tick as a side-effect.
        #
        # Trade-off: a `_sync_one` that already classified a real
        # failure (e.g. AUTH_FAILED) and was about to commit a
        # `last_sync_status` update can have that write rolled back
        # by cancellation. The next tick re-runs the same connection
        # and is expected to reproduce the same failure classification,
        # so the status field self-heals on the next cycle.
        gather_duration_ms = int(
            (datetime.now(UTC) - gather_started).total_seconds() * 1000
        )
        logger.warning(
            "nightscout_scheduler_tick_budget_exceeded",
            due_count=len(due_ids),
            budget_seconds=_TICK_WALL_BUDGET_SECONDS,
            gather_duration_ms=gather_duration_ms,
            tick_duration_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
        )
        # Always emit `tick_completed` so dashboards / alerting that
        # count one per tick don't see a gap on overrun.
        logger.info(
            "nightscout_scheduler_tick_completed",
            due_count=len(due_ids),
            success=0,
            failures=0,
            cancelled=len(due_ids),
            partial=True,
            duration_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
        )
        return

    success = sum(1 for s in statuses if s is True)
    failures = sum(1 for s in statuses if s is False)

    logger.info(
        "nightscout_scheduler_tick_completed",
        due_count=len(due_ids),
        success=success,
        failures=failures,
        duration_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
    )


async def _sync_one(
    session_maker, connection_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    """Run one connection's sync. Returns True on OK, False otherwise.

    Refetches the connection inside this function's own session
    because the discovery scan only pulled identifiers + cursor
    columns. The refetch also picks up any mutation that happened
    between discovery and now (e.g. user toggled `is_active=false`
    via PATCH, or sync_interval_minutes changed). We deliberately
    do NOT re-check `_is_due` here -- the contract is "what was due
    at tick start gets synced," even if the user changed the
    interval mid-tick.

    Cooperative-shutdown signals propagate (CancelledError / SystemExit
    / KeyboardInterrupt). Any other exception is logged with traceback
    and reported as failure so the tick continues with the rest.
    """
    try:
        async with session_maker() as user_session:
            conn_result = await user_session.execute(
                select(NightscoutConnection).where(
                    NightscoutConnection.id == connection_id,
                    NightscoutConnection.is_active.is_(True),
                )
            )
            conn = conn_result.scalar_one_or_none()
            if conn is None:
                # Connection was deleted between discovery and now;
                # silently skip (not a failure).
                return True
            outcome = await sync_nightscout_for_connection(user_session, conn)
            return outcome.status == NightscoutSyncStatus.OK
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception:  # noqa: BLE001 - per-row isolation is the goal
        logger.exception(
            "nightscout_scheduler_per_row_failure",
            connection_id=str(connection_id),
            user_id=str(user_id),
        )
        return False


def _is_due(
    last_synced_at: datetime | None,
    interval_minutes: int,
    *,
    now: datetime,
) -> bool:
    """Return True when this connection is due for another sync."""
    if last_synced_at is None:
        # Never synced -- always due.
        return True
    if last_synced_at.tzinfo is None:
        # Treat naive timestamps as UTC; the column is `timezone=True`
        # so we never expect this in practice, but be defensive.
        last_synced_at = last_synced_at.replace(tzinfo=UTC)
    return now - last_synced_at >= timedelta(minutes=interval_minutes)


def _clamped_interval(value: int) -> int:
    """Defensive clamp against out-of-range column values.

    The Pydantic schema and DB constraint already bound this, but
    if the column ever ended up out of range (manual SQL update,
    older row pre-bound) we don't want a single bad row to either
    blast upstream every tick (interval=0) or stall forever
    (interval=1e9).
    """
    return max(SYNC_INTERVAL_MIN_MINUTES, min(SYNC_INTERVAL_MAX_MINUTES, value))
