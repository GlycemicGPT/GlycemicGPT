"""Story 3.2 & 3.4: Background job scheduler.

APScheduler-based background task scheduler for data sync jobs.
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from src.config import settings
from src.database import get_session_maker
from src.logging_config import get_logger
from src.models import glooko_sync_state as glooko_state
from src.models.glooko_sync_state import GlookoSyncState
from src.models.integration import (
    IntegrationCredential,
    IntegrationStatus,
    IntegrationType,
)
from src.models.medtronic_connect_state import (
    STATUS_CONNECTED,
    STATUS_ERROR,
    STATUS_PENDING,
    MedtronicConnectState,
)
from src.models.tandem_sync_state import TandemSyncState
from src.services.dexcom_sync import DexcomSyncError, sync_dexcom_for_user
from src.services.integrations.glooko.sync import (
    GlookoSyncRunError,
    sync_glooko_for_user,
)
from src.services.integrations.medtronic.connect_sync import (
    ConnectSyncError,
    sync_connect_for_user,
)
from src.services.integrations.nightscout.scheduler import (
    run_nightscout_sync_all_users,
)
from src.services.predictive_alerts import evaluate_alerts_for_user
from src.services.tandem_sync import TandemSyncError, sync_tandem_for_user

logger = get_logger(__name__)

# Global scheduler instance
scheduler: AsyncIOScheduler | None = None


async def sync_all_dexcom_users() -> None:
    """Sync Dexcom data for all users with configured credentials.

    This job runs on a schedule and syncs data for all users
    who have connected their Dexcom accounts.
    """
    logger.info("Starting scheduled Dexcom sync for all users")

    async with get_session_maker()() as db:
        # Find all users with active Dexcom integration
        result = await db.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.integration_type == IntegrationType.DEXCOM,
                IntegrationCredential.status.in_(
                    [
                        IntegrationStatus.CONNECTED,
                        IntegrationStatus.ERROR,  # Retry errors
                    ]
                ),
            )
        )
        credentials = result.scalars().all()

        if not credentials:
            logger.info("No users with Dexcom integration to sync")
            return

        logger.info(
            "Found users for Dexcom sync",
            user_count=len(credentials),
        )

        # Sync each user
        success_count = 0
        error_count = 0

        for credential in credentials:
            try:
                # Create a new session for each user to isolate errors
                async with get_session_maker()() as user_db:
                    result = await sync_dexcom_for_user(user_db, credential.user_id)
                    logger.debug(
                        "Dexcom sync completed for user",
                        user_id=str(credential.user_id),
                        readings_fetched=result["readings_fetched"],
                        readings_stored=result["readings_stored"],
                    )
                    success_count += 1

            except DexcomSyncError as e:
                logger.warning(
                    "Scheduled Dexcom sync failed for user",
                    user_id=str(credential.user_id),
                    error=str(e),
                )
                error_count += 1

            except Exception as e:
                logger.error(
                    "Unexpected error in scheduled Dexcom sync",
                    user_id=str(credential.user_id),
                    error=str(e),
                )
                error_count += 1

            # Small delay between users to avoid rate limiting
            await asyncio.sleep(1)

    logger.info(
        "Scheduled Dexcom sync completed",
        success_count=success_count,
        error_count=error_count,
    )


# Hard ceiling on adaptive lookback so a long-dormant or never-synced user
# doesn't trigger a multi-year fetch on their first scheduled sync.
_TANDEM_MAX_LOOKBACK_HOURS = 168  # 7 days


def _tandem_is_due(
    pacing_at: datetime | None,
    interval_minutes: int,
    *,
    now: datetime,
) -> bool:
    """Return True when a user is due for another Tandem sync attempt.

    ``pacing_at`` is the last *attempt* time (success or failure). ``None``
    means never attempted -> always due. Pacing by attempt (not by the
    credential's success-only ``last_sync_at``) ensures a persistently
    failing user is retried once per interval, not on every short tick.
    """
    if pacing_at is None:
        return True
    if pacing_at.tzinfo is None:
        pacing_at = pacing_at.replace(tzinfo=UTC)
    return now - pacing_at >= timedelta(minutes=interval_minutes)


def _tandem_lookback_hours(
    last_sync_at: datetime | None,
    *,
    now: datetime,
) -> int:
    """Hours of history to fetch so the window always covers the gap since
    the last successful sync (plus a buffer), bounded by a hard ceiling.

    A fixed 24h window would miss events for users on long intervals once
    tick drift pushes the elapsed time past 24h. Sizing the window to the
    actual elapsed time closes that gap.
    """
    # Clamp the default too, so a misconfigured tandem_sync_hours_back can't
    # trigger an oversized pull for never-synced users.
    default_h = min(settings.tandem_sync_hours_back, _TANDEM_MAX_LOOKBACK_HOURS)
    if last_sync_at is None:
        return default_h
    if last_sync_at.tzinfo is None:
        last_sync_at = last_sync_at.replace(tzinfo=UTC)
    elapsed_h = (now - last_sync_at).total_seconds() / 3600.0
    # +2h buffer absorbs tick drift and clock skew.
    return max(default_h, min(int(elapsed_h) + 2, _TANDEM_MAX_LOOKBACK_HOURS))


async def _record_tandem_attempt(
    user_id: uuid.UUID, *, now: datetime, events_stored: int | None
) -> None:
    """Record a scheduled sync attempt on the user's TandemSyncState.

    Upserts the row (auto-create with defaults == backward-compatible
    "enabled@default") and stamps ``last_attempt_at`` so the next tick paces
    by attempt. On success, also bumps the cumulative ``events_pulled_total``.
    Runs in its own session, isolated from the sync's session state, and is
    best-effort: a bookkeeping failure must not abort the tick.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    try:
        async with get_session_maker()() as book_db:
            await book_db.execute(
                pg_insert(TandemSyncState)
                .values(user_id=user_id, last_attempt_at=now)
                .on_conflict_do_nothing(index_elements=["user_id"])
            )
            row = (
                await book_db.execute(
                    select(TandemSyncState)
                    .where(TandemSyncState.user_id == user_id)
                    .with_for_update()
                )
            ).scalar_one()
            row.last_attempt_at = now
            if events_stored:
                row.events_pulled_total += events_stored
            await book_db.commit()
    except Exception as e:  # noqa: BLE001 - bookkeeping must not kill the tick
        logger.warning(
            "Failed to record Tandem sync attempt",
            user_id=str(user_id),
            error=str(e),
        )


async def sync_all_tandem_users() -> None:
    """One scheduler tick: sync each due, enabled Tandem user.

    Runs on ``tandem_sync_tick_interval_minutes``. For every connected
    Tandem credential it reads the per-user ``TandemSyncState`` and:
      - skips users who explicitly disabled sync (state row, enabled=False);
      - a user with NO state row is treated as enabled at the default
        interval -- backward-compatible with the prior global sync;
      - paces by ``last_attempt_at`` (falling back to the credential's
        ``last_sync_at`` until the first attempt is recorded) so failing
        users retry once per interval, not every tick.
    Every attempt (success or failure) is recorded via
    ``_record_tandem_attempt`` (which also bumps the cumulative counter on
    success); the lookback window is sized to the elapsed gap.
    """
    now = datetime.now(UTC)
    logger.info("Starting scheduled Tandem sync tick")

    async with get_session_maker()() as db:
        # Left-join state so one query yields credential + control. A user
        # with no row gets state=None (-> effective enabled@default).
        result = await db.execute(
            select(IntegrationCredential, TandemSyncState)
            .outerjoin(
                TandemSyncState,
                TandemSyncState.user_id == IntegrationCredential.user_id,
            )
            .where(
                IntegrationCredential.integration_type == IntegrationType.TANDEM,
                IntegrationCredential.status.in_(
                    [
                        IntegrationStatus.CONNECTED,
                        IntegrationStatus.ERROR,  # Retry errors
                    ]
                ),
            )
        )
        rows = result.all()

        # Decide who is due (before opening per-user sessions). Capture the
        # per-user lookback now while we hold the credential's last_sync_at.
        due: list[tuple[uuid.UUID, int]] = []
        for credential, state in rows:
            if state is not None and not state.enabled:
                continue
            interval = (
                state.sync_interval_minutes
                if state is not None
                else settings.tandem_sync_interval_minutes
            )
            # Pace by last *attempt*; fall back to last success until the
            # first attempt is stamped.
            pacing_at = (
                state.last_attempt_at
                if state is not None and state.last_attempt_at is not None
                else credential.last_sync_at
            )
            if _tandem_is_due(pacing_at, interval, now=now):
                lookback = _tandem_lookback_hours(credential.last_sync_at, now=now)
                due.append((credential.user_id, lookback))

        if not due:
            logger.info("No Tandem users due for sync this tick")
            return

        logger.info("Found Tandem users due for sync", user_count=len(due))

    success_count = 0
    error_count = 0

    for user_id, lookback in due:
        events_stored: int | None = None
        try:
            # New session per user to isolate errors.
            async with get_session_maker()() as user_db:
                sync_result = await sync_tandem_for_user(
                    user_db, user_id, hours_back=lookback
                )
                events_stored = sync_result["events_stored"]
                logger.info(
                    "Tandem sync completed for user",
                    user_id=str(user_id),
                    events_fetched=sync_result["events_fetched"],
                    events_stored=events_stored,
                )
                success_count += 1

        except TandemSyncError as e:
            logger.warning(
                "Scheduled Tandem sync failed for user",
                user_id=str(user_id),
                error=str(e),
            )
            error_count += 1

        except Exception as e:
            logger.error(
                "Unexpected error in scheduled Tandem sync",
                user_id=str(user_id),
                error=str(e),
            )
            error_count += 1

        # Record the attempt (success or failure) so the next tick paces by
        # it -- this is what prevents failing users from being hammered every
        # tick. Best-effort, isolated session.
        await _record_tandem_attempt(
            user_id, now=datetime.now(UTC), events_stored=events_stored
        )

        # Small delay between users to avoid rate limiting
        await asyncio.sleep(1)

    logger.info(
        "Scheduled Tandem sync tick completed",
        success_count=success_count,
        error_count=error_count,
    )


async def sync_all_medtronic_connect_users() -> None:
    """One scheduler tick: sync each due, enabled Medtronic Connect user.

    Runs on ``medtronic_connect_tick_interval_minutes``. Unlike Tandem, the
    ``MedtronicConnectState`` row IS the credential (self-contained), so absence
    of a row means "not connected" -- only rows that are enabled and not
    disconnected are considered. Pacing is by ``last_attempt_at`` (reusing the
    Tandem pacing rule) so a failing user retries once per interval, not every
    tick. ``sync_connect_for_user`` updates the row (status, freshness, rotated
    refresh token, counter) itself.
    """
    now = datetime.now(UTC)
    logger.info("Starting scheduled Medtronic Connect sync tick")

    async with get_session_maker()() as db:
        result = await db.execute(
            select(MedtronicConnectState).where(
                MedtronicConnectState.enabled.is_(True),
                MedtronicConnectState.status.in_(
                    [STATUS_CONNECTED, STATUS_ERROR, STATUS_PENDING]
                ),
            )
        )
        due_ids = [
            state.user_id
            for state in result.scalars().all()
            if _tandem_is_due(
                state.last_attempt_at, state.sync_interval_minutes, now=now
            )
        ]

    if not due_ids:
        logger.info("No Medtronic Connect users due for sync this tick")
        return

    logger.info("Found Medtronic Connect users due for sync", user_count=len(due_ids))

    success_count = 0
    error_count = 0
    for user_id in due_ids:
        try:
            # New session per user to isolate errors; re-read the row inside it.
            async with get_session_maker()() as user_db:
                state = (
                    await user_db.execute(
                        select(MedtronicConnectState).where(
                            MedtronicConnectState.user_id == user_id
                        )
                    )
                ).scalar_one_or_none()
                if state is None:
                    continue
                await sync_connect_for_user(user_db, state)
                success_count += 1
        except ConnectSyncError as e:
            logger.warning(
                "Scheduled Medtronic Connect sync failed for user",
                user_id=str(user_id),
                error=str(e),
            )
            error_count += 1
        except Exception as e:
            logger.error(
                "Unexpected error in scheduled Medtronic Connect sync",
                user_id=str(user_id),
                error=str(e),
            )
            error_count += 1

        # Small delay between users to avoid rate limiting.
        await asyncio.sleep(1)

    logger.info(
        "Scheduled Medtronic Connect sync tick completed",
        success_count=success_count,
        error_count=error_count,
    )


async def sync_all_glooko_users() -> None:
    """One scheduler tick: sync each due, enabled Glooko user.

    Runs on ``glooko_sync_tick_interval_minutes``. Like Medtronic (and unlike
    Tandem), the ``GlookoSyncState`` row IS the credential (self-contained), so
    absence of a row means "not connected" -- only rows that are enabled and not
    ``disconnected`` are considered (a disconnected row = a dead credential the
    decrypt-flood guard suspended; re-including it would retry a hopeless login
    every tick). Pacing is by ``last_attempt_at`` (reusing the Tandem pacing rule)
    so a failing user retries once per interval, not every tick.
    ``sync_glooko_for_user`` updates the row (status, freshness, error, advanced
    cursor, counter) itself.
    """
    now = datetime.now(UTC)
    logger.info("Starting scheduled Glooko sync tick")

    async with get_session_maker()() as db:
        result = await db.execute(
            select(GlookoSyncState).where(
                GlookoSyncState.enabled.is_(True),
                GlookoSyncState.status.in_(
                    [
                        glooko_state.STATUS_CONNECTED,
                        glooko_state.STATUS_ERROR,
                        glooko_state.STATUS_PENDING,
                    ]
                ),
            )
        )
        due_ids = [
            state.user_id
            for state in result.scalars().all()
            if _tandem_is_due(
                state.last_attempt_at, state.sync_interval_minutes, now=now
            )
        ]

    if not due_ids:
        logger.info("No Glooko users due for sync this tick")
        return

    logger.info("Found Glooko users due for sync", user_count=len(due_ids))

    success_count = 0
    error_count = 0
    for user_id in due_ids:
        try:
            # New session per user to isolate errors; re-read the row inside it.
            async with get_session_maker()() as user_db:
                state = (
                    await user_db.execute(
                        select(GlookoSyncState).where(
                            GlookoSyncState.user_id == user_id
                        )
                    )
                ).scalar_one_or_none()
                if state is None:
                    continue
                await sync_glooko_for_user(user_db, state)
                success_count += 1
        except GlookoSyncRunError as e:
            logger.warning(
                "Scheduled Glooko sync failed for user",
                user_id=str(user_id),
                error=str(e),
            )
            error_count += 1
        except Exception as e:
            logger.error(
                "Unexpected error in scheduled Glooko sync",
                user_id=str(user_id),
                error=str(e),
            )
            error_count += 1

        # Small delay between users to avoid rate limiting.
        await asyncio.sleep(1)

    logger.info(
        "Scheduled Glooko sync tick completed",
        success_count=success_count,
        error_count=error_count,
    )


async def check_alerts_all_users() -> None:
    """Run predictive alert evaluation for all users with active integrations.

    This job runs on a schedule and evaluates alerts for all users
    who have any active glucose data integration (Dexcom or Tandem).
    """
    logger.info("Starting scheduled alert check for all users")

    async with get_session_maker()() as db:
        result = await db.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.integration_type.in_(
                    [IntegrationType.DEXCOM, IntegrationType.TANDEM]
                ),
                IntegrationCredential.status == IntegrationStatus.CONNECTED,
            )
        )
        credentials = result.scalars().all()

        # Deduplicate by user_id (a user may have both Dexcom and Tandem)
        seen_user_ids = set()
        unique_credentials = []
        for cred in credentials:
            if cred.user_id not in seen_user_ids:
                seen_user_ids.add(cred.user_id)
                unique_credentials.append(cred)
        credentials = unique_credentials

        if not credentials:
            logger.info("No users with active integrations for alert check")
            return

        alert_count = 0
        error_count = 0

        for credential in credentials:
            try:
                async with get_session_maker()() as user_db:
                    new_alerts = await evaluate_alerts_for_user(
                        user_db, credential.user_id
                    )
                    alert_count += len(new_alerts)
            except Exception as e:
                logger.error(
                    "Alert check failed for user",
                    user_id=str(credential.user_id),
                    error=str(e),
                )
                error_count += 1

            await asyncio.sleep(0.5)

    logger.info(
        "Scheduled alert check completed",
        alerts_created=alert_count,
        errors=error_count,
    )


async def check_escalations_all_users() -> None:
    """Run escalation checks for users with unacknowledged critical alerts.

    This job runs frequently (every 1 minute) to ensure timely escalations.
    Only queries users who actually have unacked URGENT/EMERGENCY alerts,
    avoiding unnecessary work for users with no escalatable alerts.
    """
    from datetime import UTC, datetime

    from sqlalchemy import and_, distinct

    from src.models.alert import Alert, AlertSeverity
    from src.models.user import User
    from src.services.escalation_engine import process_escalations_for_user

    logger.info("Starting scheduled escalation check")

    now = datetime.now(UTC)

    async with get_session_maker()() as db:
        # Only find users who have unacknowledged critical alerts
        user_ids_result = await db.execute(
            select(distinct(Alert.user_id)).where(
                and_(
                    Alert.acknowledged.is_(False),
                    Alert.expires_at > now,
                    Alert.severity.in_([AlertSeverity.URGENT, AlertSeverity.EMERGENCY]),
                )
            )
        )
        user_ids = [row[0] for row in user_ids_result.all()]

        if not user_ids:
            logger.info("No users with unacknowledged critical alerts")
            return

        # Fetch user details for those with critical alerts
        result = await db.execute(
            select(User).where(User.id.in_(user_ids), User.is_active.is_(True))
        )
        users = result.scalars().all()

        if not users:
            logger.info("No active users for escalation check")
            return

        escalation_count = 0
        error_count = 0

        for user in users:
            try:
                async with get_session_maker()() as user_db:
                    count = await process_escalations_for_user(
                        user_db, user.id, user.email
                    )
                    escalation_count += count
            except Exception as e:
                logger.error(
                    "Escalation check failed for user",
                    user_id=str(user.id),
                    error=str(e),
                )
                error_count += 1

            await asyncio.sleep(0.1)

    logger.info(
        "Scheduled escalation check completed",
        escalations_triggered=escalation_count,
        errors=error_count,
    )


async def enforce_data_retention_all_users() -> None:
    """Enforce data retention policies for all users with configured retention settings.

    This job runs daily and deletes records older than each user's
    configured retention period.
    """
    from src.models.data_retention_config import DataRetentionConfig
    from src.services.data_retention_config import enforce_retention_for_user

    logger.info("Starting scheduled data retention enforcement")

    # Collect user IDs with retention configs, then close the session
    # before iterating to avoid DetachedInstanceError
    async with get_session_maker()() as db:
        result = await db.execute(select(DataRetentionConfig.user_id))
        user_ids = [row[0] for row in result.all()]

    if not user_ids:
        logger.info("No users with data retention config to enforce")
        return

    success_count = 0
    error_count = 0
    total_deleted = 0

    for user_id in user_ids:
        try:
            async with get_session_maker()() as user_db:
                # Fetch config fresh in this session
                config_result = await user_db.execute(
                    select(DataRetentionConfig).where(
                        DataRetentionConfig.user_id == user_id
                    )
                )
                user_config = config_result.scalar_one_or_none()
                if user_config is None:
                    continue
                deleted = await enforce_retention_for_user(
                    user_id, user_config, user_db
                )
                total_deleted += sum(deleted.values())
                success_count += 1
        except Exception as e:
            logger.error(
                "Data retention enforcement failed for user",
                user_id=str(user_id),
                error=str(e),
            )
            error_count += 1

    logger.info(
        "Scheduled data retention enforcement completed",
        users_processed=success_count,
        errors=error_count,
        total_records_deleted=total_deleted,
    )


async def cleanup_stale_devices_job() -> None:
    """Remove devices not seen in 30 days."""
    from src.services.device_service import cleanup_stale_devices

    async with get_session_maker()() as db:
        try:
            count = await cleanup_stale_devices(db, max_age_days=30)
            if count > 0:
                logger.info("Stale device cleanup completed", removed=count)
        except Exception as e:
            logger.error("Stale device cleanup failed", error=str(e))


async def poll_telegram_updates() -> None:
    """Poll Telegram for verification /start messages.

    This job runs every N seconds when telegram_bot_token is configured.
    It processes incoming /start messages to link user accounts.
    """
    from src.services.telegram_bot import TelegramBotError, poll_for_verifications

    async with get_session_maker()() as db:
        try:
            processed = await poll_for_verifications(db)
            if processed > 0:
                logger.info(
                    "Processed Telegram verifications",
                    count=processed,
                )
        except TelegramBotError as e:
            logger.warning("Telegram polling error", error=str(e))
        except Exception as e:
            logger.error("Unexpected Telegram polling error", error=str(e))


def start_scheduler() -> AsyncIOScheduler:
    """Start the background job scheduler.

    Returns:
        The started scheduler instance
    """
    global scheduler

    if scheduler is not None:
        logger.warning("Scheduler already running")
        return scheduler

    scheduler = AsyncIOScheduler()

    # Add Dexcom sync job if enabled
    if settings.dexcom_sync_enabled:
        scheduler.add_job(
            sync_all_dexcom_users,
            trigger=IntervalTrigger(minutes=settings.dexcom_sync_interval_minutes),
            id="dexcom_sync",
            name="Dexcom CGM Data Sync",
            replace_existing=True,
        )
        logger.info(
            "Scheduled Dexcom sync job",
            interval_minutes=settings.dexcom_sync_interval_minutes,
        )

    # Add Tandem sync tick job if enabled (Story 3.4 + per-user sync).
    # Single global tick; per-user cadence (TandemSyncState.sync_interval_
    # minutes, default tandem_sync_interval_minutes) is honored inside
    # sync_all_tandem_users by checking each credential's last_sync_at.
    if settings.tandem_sync_enabled:
        scheduler.add_job(
            sync_all_tandem_users,
            trigger=IntervalTrigger(minutes=settings.tandem_sync_tick_interval_minutes),
            id="tandem_sync",
            name="Tandem Pump Data Sync Tick",
            replace_existing=True,
            # A slow tick (many due users) should not stack with the next.
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            "Scheduled Tandem sync tick job",
            tick_interval_minutes=settings.tandem_sync_tick_interval_minutes,
            default_user_interval_minutes=settings.tandem_sync_interval_minutes,
        )
    else:
        logger.warning(
            "Tandem sync scheduler DISABLED via TANDEM_SYNC_ENABLED env var. "
            "Manual sync via POST /api/integrations/tandem/sync still works; "
            "scheduled pulls will not run."
        )

    # Medtronic CareLink CarePartner (Connect) autonomous sync tick. Enabled
    # by default (MEDTRONIC_CONNECT_ENABLED); set it false to disable the whole
    # job without a redeploy. The tick no-ops safely until a user connects a
    # Medtronic account -- the per-user cadence
    # (MedtronicConnectState.sync_interval_minutes) is honored inside
    # sync_all_medtronic_connect_users.
    if settings.medtronic_connect_enabled:
        scheduler.add_job(
            sync_all_medtronic_connect_users,
            trigger=IntervalTrigger(
                minutes=settings.medtronic_connect_tick_interval_minutes
            ),
            id="medtronic_connect_sync",
            name="Medtronic Connect Data Sync Tick",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            "Scheduled Medtronic Connect sync tick job",
            tick_interval_minutes=settings.medtronic_connect_tick_interval_minutes,
        )
    else:
        logger.info(
            "Medtronic Connect sync scheduler disabled (set "
            "MEDTRONIC_CONNECT_ENABLED=true to enable). Manual sync via "
            "POST /api/integrations/medtronic/connect/sync still works."
        )

    # Glooko (Omnipod Cloud Sync) autonomous sync tick. Enabled by default
    # (GLOOKO_SYNC_ENABLED); set it false to disable the whole job without a
    # redeploy. The tick no-ops safely until a user connects a Glooko account --
    # the per-user cadence (GlookoSyncState.sync_interval_minutes) is honored
    # inside sync_all_glooko_users.
    if settings.glooko_sync_enabled:
        scheduler.add_job(
            sync_all_glooko_users,
            trigger=IntervalTrigger(minutes=settings.glooko_sync_tick_interval_minutes),
            id="glooko_sync",
            name="Glooko (Omnipod) Data Sync Tick",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            "Scheduled Glooko sync tick job",
            tick_interval_minutes=settings.glooko_sync_tick_interval_minutes,
        )
    else:
        logger.info(
            "Glooko sync scheduler disabled (set GLOOKO_SYNC_ENABLED=true to "
            "enable). Manual sync via the Glooko integration endpoints still works."
        )

    # Add Nightscout sync tick job if enabled (Story 43.4)
    # Single global tick; the per-connection cadence is honored inside
    # `run_nightscout_sync_all_users` by checking each row's
    # `sync_interval_minutes` against `last_synced_at`.
    if settings.nightscout_sync_enabled:
        scheduler.add_job(
            run_nightscout_sync_all_users,
            trigger=IntervalTrigger(
                minutes=settings.nightscout_sync_tick_interval_minutes
            ),
            id="nightscout_sync",
            name="Nightscout Sync Tick",
            replace_existing=True,
            # max_instances=1 + coalesce: a long-running tick should
            # not stack with the next one. Per-connection asyncio lock
            # in sync.py protects against manual + scheduler races.
            max_instances=1,
            coalesce=True,
        )
        logger.info(
            "Scheduled Nightscout sync tick job",
            tick_interval_minutes=settings.nightscout_sync_tick_interval_minutes,
        )

    # Add predictive alert check job if enabled (Story 6.2)
    if settings.alert_check_enabled:
        scheduler.add_job(
            check_alerts_all_users,
            trigger=IntervalTrigger(minutes=settings.alert_check_interval_minutes),
            id="alert_check",
            name="Predictive Alert Check",
            replace_existing=True,
        )
        logger.info(
            "Scheduled alert check job",
            interval_minutes=settings.alert_check_interval_minutes,
        )

    # Add escalation check job if enabled (Story 6.7)
    if settings.escalation_check_enabled:
        scheduler.add_job(
            check_escalations_all_users,
            trigger=IntervalTrigger(minutes=settings.escalation_check_interval_minutes),
            id="escalation_check",
            name="Alert Escalation Check",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "Scheduled escalation check job",
            interval_minutes=settings.escalation_check_interval_minutes,
        )

    # Add data retention enforcement job if enabled (Story 9.3)
    if settings.data_retention_enabled:
        scheduler.add_job(
            enforce_data_retention_all_users,
            trigger=IntervalTrigger(hours=settings.data_retention_check_interval_hours),
            id="data_retention",
            name="Data Retention Enforcement",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "Scheduled data retention enforcement job",
            interval_hours=settings.data_retention_check_interval_hours,
        )

    # Tandem cloud upload feature was removed in PR1c -- no scheduler job here.

    # Add stale device cleanup job (Story 16.11)
    scheduler.add_job(
        cleanup_stale_devices_job,
        trigger=IntervalTrigger(hours=24),
        id="stale_device_cleanup",
        name="Stale Device Cleanup",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled stale device cleanup job (daily)")

    # Add Telegram polling job if enabled and token configured (Story 7.1)
    if settings.telegram_polling_enabled and settings.telegram_bot_token:
        scheduler.add_job(
            poll_telegram_updates,
            trigger=IntervalTrigger(seconds=settings.telegram_polling_interval_seconds),
            id="telegram_poll",
            name="Telegram Bot Polling",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "Scheduled Telegram polling job",
            interval_seconds=settings.telegram_polling_interval_seconds,
        )

    # Add AI Research Pipeline job (Story 35.12)
    if settings.research_pipeline_enabled:
        from src.services.research_scheduler import run_research_pipeline_all_users

        scheduler.add_job(
            run_research_pipeline_all_users,
            trigger=IntervalTrigger(hours=settings.research_pipeline_interval_hours),
            id="research_pipeline",
            name="AI Research Pipeline",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "Scheduled AI research pipeline job",
            interval_hours=settings.research_pipeline_interval_hours,
        )

    scheduler.start()
    logger.info("Background scheduler started")

    return scheduler


def stop_scheduler() -> None:
    """Stop the background job scheduler."""
    global scheduler

    if scheduler is not None:
        scheduler.shutdown(wait=False)
        scheduler = None
        logger.info("Background scheduler stopped")


def get_scheduler() -> AsyncIOScheduler | None:
    """Get the current scheduler instance.

    Returns:
        The scheduler instance or None if not started
    """
    return scheduler


@asynccontextmanager
async def scheduler_lifespan() -> AsyncGenerator[None, None]:
    """Async context manager for scheduler lifecycle.

    Use this in FastAPI lifespan to manage scheduler start/stop.
    """
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
