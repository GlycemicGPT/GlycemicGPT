"""Story 3.2 & 3.4: Background job scheduler.

APScheduler-based background task scheduler for data sync jobs.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from src.config import settings
from src.database import get_session_maker
from src.logging_config import get_logger
from src.models.integration import (
    IntegrationCredential,
    IntegrationStatus,
    IntegrationType,
)
from src.services.dexcom_sync import DexcomSyncError, sync_dexcom_for_user
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


async def sync_all_tandem_users() -> None:
    """Sync Tandem data for all users with configured credentials.

    This job runs on a schedule and syncs pump data for all users
    who have connected their Tandem t:connect accounts.
    """
    logger.info("Starting scheduled Tandem sync for all users")

    async with get_session_maker()() as db:
        # Find all users with active Tandem integration
        result = await db.execute(
            select(IntegrationCredential).where(
                IntegrationCredential.integration_type == IntegrationType.TANDEM,
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
            logger.info("No users with Tandem integration to sync")
            return

        logger.info(
            "Found users for Tandem sync",
            user_count=len(credentials),
        )

        # Sync each user
        success_count = 0
        error_count = 0

        for credential in credentials:
            try:
                # Create a new session for each user to isolate errors
                async with get_session_maker()() as user_db:
                    result = await sync_tandem_for_user(user_db, credential.user_id)
                    logger.info(
                        "Tandem sync completed for user",
                        user_id=str(credential.user_id),
                        events_fetched=result["events_fetched"],
                        events_stored=result["events_stored"],
                    )
                    success_count += 1

            except TandemSyncError as e:
                logger.warning(
                    "Scheduled Tandem sync failed for user",
                    user_id=str(credential.user_id),
                    error=str(e),
                )
                error_count += 1

            except Exception as e:
                logger.error(
                    "Unexpected error in scheduled Tandem sync",
                    user_id=str(credential.user_id),
                    error=str(e),
                )
                error_count += 1

            # Small delay between users to avoid rate limiting
            await asyncio.sleep(1)

    logger.info(
        "Scheduled Tandem sync completed",
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

    # Add Tandem sync job if enabled (Story 3.4)
    if settings.tandem_sync_enabled:
        scheduler.add_job(
            sync_all_tandem_users,
            trigger=IntervalTrigger(minutes=settings.tandem_sync_interval_minutes),
            id="tandem_sync",
            name="Tandem Pump Data Sync",
            replace_existing=True,
        )
        logger.info(
            "Scheduled Tandem sync job",
            interval_minutes=settings.tandem_sync_interval_minutes,
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

    # Add Tandem cloud upload job if enabled (Story 16.6)
    if settings.tandem_upload_enabled:
        from src.services.tandem_upload_scheduler import run_tandem_cloud_uploads

        scheduler.add_job(
            run_tandem_cloud_uploads,
            trigger=IntervalTrigger(
                minutes=settings.tandem_upload_check_interval_minutes
            ),
            id="tandem_cloud_upload",
            name="Tandem Cloud Upload",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "Scheduled Tandem cloud upload job",
            interval_minutes=settings.tandem_upload_check_interval_minutes,
        )

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
