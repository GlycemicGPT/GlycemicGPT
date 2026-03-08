"""Story 3.2: Dexcom CGM Data Sync Service.

Handles fetching glucose readings from Dexcom Share API and storing them.
"""

import uuid
from datetime import UTC, datetime

from pydexcom import Dexcom
from pydexcom import errors as dexcom_errors
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.encryption import decrypt_credential
from src.logging_config import get_logger
from src.models.glucose import PYDEXCOM_TREND_MAP, GlucoseReading, TrendDirection
from src.models.integration import (
    IntegrationCredential,
    IntegrationStatus,
    IntegrationType,
)

logger = get_logger(__name__)


class DexcomSyncError(Exception):
    """Base exception for Dexcom sync errors."""

    pass


class DexcomAuthError(DexcomSyncError):
    """Authentication failed with Dexcom."""

    pass


class DexcomConnectionError(DexcomSyncError):
    """Connection to Dexcom failed."""

    pass


def map_trend(trend_value: str | int) -> TrendDirection:
    """Map pydexcom trend value to our TrendDirection enum.

    Args:
        trend_value: Trend from pydexcom (string or int)

    Returns:
        TrendDirection enum value
    """
    if trend_value in PYDEXCOM_TREND_MAP:
        return PYDEXCOM_TREND_MAP[trend_value]
    return TrendDirection.NOT_COMPUTABLE


async def sync_dexcom_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    max_readings: int | None = None,
) -> dict:
    """Sync Dexcom glucose readings for a specific user.

    Args:
        db: Database session
        user_id: User ID to sync for
        max_readings: Maximum number of readings to fetch (default from settings)

    Returns:
        Dict with sync results (readings_fetched, readings_stored, last_reading)

    Raises:
        DexcomAuthError: If credentials are invalid
        DexcomConnectionError: If connection fails
        DexcomSyncError: For other sync errors
    """
    if max_readings is None:
        max_readings = settings.dexcom_max_readings_per_sync

    logger.info(
        "Starting Dexcom sync for user",
        user_id=str(user_id),
        max_readings=max_readings,
    )

    # Get user's Dexcom credentials
    result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == user_id,
            IntegrationCredential.integration_type == IntegrationType.DEXCOM,
        )
    )
    credential = result.scalar_one_or_none()

    if not credential:
        logger.warning("No Dexcom credentials found for user", user_id=str(user_id))
        raise DexcomSyncError("Dexcom integration not configured")

    if credential.status == IntegrationStatus.DISCONNECTED:
        logger.warning("Dexcom integration is disconnected", user_id=str(user_id))
        raise DexcomSyncError("Dexcom integration is disconnected")

    # Decrypt credentials
    try:
        username = decrypt_credential(credential.encrypted_username)
        password = decrypt_credential(credential.encrypted_password)
    except ValueError as e:
        logger.error(
            "Failed to decrypt Dexcom credentials",
            user_id=str(user_id),
            error=str(e),
        )
        credential.status = IntegrationStatus.ERROR
        credential.last_error = "Credential decryption failed"
        await db.commit()
        raise DexcomSyncError("Failed to decrypt credentials") from e

    # Connect to Dexcom
    try:
        dexcom = Dexcom(username=username, password=password)
    except dexcom_errors.AccountError as e:
        logger.warning(
            "Dexcom authentication failed",
            user_id=str(user_id),
            error=str(e),
        )
        credential.status = IntegrationStatus.ERROR
        credential.last_error = "Authentication failed - check credentials"
        await db.commit()
        raise DexcomAuthError("Invalid Dexcom credentials") from e
    except Exception as e:
        logger.error(
            "Failed to connect to Dexcom",
            user_id=str(user_id),
            error=str(e),
        )
        credential.status = IntegrationStatus.ERROR
        credential.last_error = f"Connection failed: {str(e)}"
        await db.commit()
        raise DexcomConnectionError(f"Failed to connect: {str(e)}") from e

    # Fetch glucose readings
    try:
        readings = dexcom.get_glucose_readings(minutes=60, max_count=max_readings)
    except dexcom_errors.SessionError as e:
        logger.warning(
            "Dexcom session error",
            user_id=str(user_id),
            error=str(e),
        )
        credential.status = IntegrationStatus.ERROR
        credential.last_error = "Session error - will retry"
        await db.commit()
        raise DexcomConnectionError("Session error") from e
    except Exception as e:
        logger.error(
            "Failed to fetch Dexcom readings",
            user_id=str(user_id),
            error=str(e),
        )
        credential.status = IntegrationStatus.ERROR
        credential.last_error = f"Fetch failed: {str(e)}"
        await db.commit()
        raise DexcomSyncError(f"Failed to fetch readings: {str(e)}") from e

    if not readings:
        logger.info("No new readings from Dexcom", user_id=str(user_id))
        credential.status = IntegrationStatus.CONNECTED
        credential.last_sync_at = datetime.now(UTC)
        credential.last_error = None
        await db.commit()
        return {
            "readings_fetched": 0,
            "readings_stored": 0,
            "last_reading": None,
        }

    # Store readings (using upsert to handle duplicates)
    now = datetime.now(UTC)
    stored_count = 0
    last_reading = None

    for reading in readings:
        # Get reading timestamp - pydexcom returns datetime
        reading_time = (
            reading.datetime if hasattr(reading, "datetime") else reading.time
        )

        # Map trend
        trend = map_trend(
            reading.trend if hasattr(reading, "trend") else reading.trend_direction
        )

        # Get trend rate if available
        trend_rate = None
        if hasattr(reading, "trend_rate"):
            trend_rate = reading.trend_rate

        # Use PostgreSQL upsert (INSERT ON CONFLICT DO NOTHING)
        stmt = (
            insert(GlucoseReading)
            .values(
                id=uuid.uuid4(),
                user_id=user_id,
                value=reading.value,
                reading_timestamp=reading_time,
                trend=trend,
                trend_rate=trend_rate,
                received_at=now,
                source="dexcom",
            )
            .on_conflict_do_nothing(index_elements=["user_id", "reading_timestamp"])
        )

        result = await db.execute(stmt)
        if result.rowcount > 0:
            stored_count += 1

        # Track the most recent reading
        if last_reading is None or reading_time > last_reading["timestamp"]:
            last_reading = {
                "value": reading.value,
                "timestamp": reading_time,
                "trend": trend.value,
            }

    # Update integration status
    credential.status = IntegrationStatus.CONNECTED
    credential.last_sync_at = now
    credential.last_error = None
    await db.commit()

    logger.info(
        "Dexcom sync completed",
        user_id=str(user_id),
        readings_fetched=len(readings),
        readings_stored=stored_count,
        last_value=last_reading["value"] if last_reading else None,
    )

    return {
        "readings_fetched": len(readings),
        "readings_stored": stored_count,
        "last_reading": last_reading,
    }


async def get_latest_glucose_reading(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> GlucoseReading | None:
    """Get the most recent glucose reading for a user.

    Args:
        db: Database session
        user_id: User ID

    Returns:
        Most recent GlucoseReading or None
    """
    result = await db.execute(
        select(GlucoseReading)
        .where(GlucoseReading.user_id == user_id)
        .order_by(GlucoseReading.reading_timestamp.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_glucose_readings(
    db: AsyncSession,
    user_id: uuid.UUID,
    minutes: int = 180,
    limit: int = 36,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[GlucoseReading]:
    """Get recent glucose readings for a user.

    Args:
        db: Database session
        user_id: User ID
        minutes: Number of minutes of history (default 3 hours)
        limit: Maximum readings to return
        start: Optional absolute start of date range (overrides minutes)
        end: Optional absolute end of date range (overrides minutes)

    Returns:
        List of GlucoseReading objects, ordered by timestamp descending
    """
    from datetime import timedelta

    if start is not None and end is not None:
        cutoff = start
        upper = end
    else:
        cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
        upper = None

    conditions = [
        GlucoseReading.user_id == user_id,
        GlucoseReading.reading_timestamp >= cutoff,
    ]
    if upper is not None:
        conditions.append(GlucoseReading.reading_timestamp <= upper)

    result = await db.execute(
        select(GlucoseReading)
        .where(*conditions)
        .order_by(GlucoseReading.reading_timestamp.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
