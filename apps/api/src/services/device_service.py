"""Device registration service.

Manages mobile device registration for alert delivery with
fingerprint-based binding and per-user device limits.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.logging_config import get_logger
from src.models.device_registration import DeviceRegistration

logger = get_logger(__name__)


async def register_device(
    db: AsyncSession,
    user_id: uuid.UUID,
    device_token: str,
    device_name: str,
    platform: str = "android",
    device_fingerprint: str | None = None,
    app_version: str | None = None,
    build_type: str | None = None,
) -> DeviceRegistration:
    """Register or update a device for alert delivery.

    Uses upsert semantics: if device_token already exists, updates
    last_seen_at and user association.

    Raises:
        ValueError: If per-user device limit is exceeded or fingerprint
            is already bound to a different user.
    """
    from sqlalchemy.exc import IntegrityError

    now = datetime.now(UTC)

    # --- Fingerprint conflict detection ---
    if not device_fingerprint:
        logger.warning(
            "Device registration without fingerprint",
            user_id=str(user_id),
            device_token=device_token[:8] + "...",
        )
    if device_fingerprint:
        result = await db.execute(
            select(DeviceRegistration).where(
                and_(
                    DeviceRegistration.device_fingerprint == device_fingerprint,
                    DeviceRegistration.user_id != user_id,
                )
            )
        )
        if result.scalar_one_or_none() is not None:
            raise ValueError("Device fingerprint is already registered to another user")

    # --- Per-user device limit ---
    # Exclude the device being re-registered (same token) so updates don't
    # count against the limit.
    # Always use the release limit -- build_type is client-asserted and
    # cannot be trusted for security decisions.
    limit = settings.max_devices_per_user
    count_query = (
        select(func.count())
        .select_from(DeviceRegistration)
        .where(
            DeviceRegistration.user_id == user_id,
            DeviceRegistration.device_token != device_token,
        )
    )
    count_result = await db.execute(count_query)
    if count_result.scalar_one() >= limit:
        raise ValueError(f"Maximum of {limit} devices per user reached")

    # Try insert inside a savepoint so IntegrityError only rolls back the
    # nested transaction -- the caller's pending work (audit logs etc.) is
    # preserved.
    device = DeviceRegistration(
        user_id=user_id,
        device_token=device_token,
        device_name=device_name,
        platform=platform,
        device_fingerprint=device_fingerprint,
        app_version=app_version,
        build_type=build_type,
        last_seen_at=now,
        created_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(device)
            await db.flush()
    except IntegrityError:
        # Token already exists -- only allow update if it belongs to the
        # SAME user.  Reassigning another user's token would let an
        # attacker hijack their push notifications.
        result = await db.execute(
            select(DeviceRegistration).where(
                DeviceRegistration.device_token == device_token
            )
        )
        existing = result.scalar_one()
        if existing.user_id != user_id:
            raise ValueError("Device token is already registered to another user")
        existing.device_name = device_name
        existing.platform = platform
        if device_fingerprint is not None:
            existing.device_fingerprint = device_fingerprint
        if app_version is not None:
            existing.app_version = app_version
        if build_type is not None:
            existing.build_type = build_type
        existing.last_seen_at = now
        await db.flush()
        logger.info(
            "Device registration updated",
            user_id=str(user_id),
            device_token=device_token[:8] + "...",
        )
        return existing

    logger.info(
        "Device registered",
        user_id=str(user_id),
        device_token=device_token[:8] + "...",
    )
    return device


async def unregister_device(
    db: AsyncSession,
    device_token: str,
    user_id: uuid.UUID | None = None,
) -> bool:
    """Remove a device registration.

    Args:
        db: Database session.
        device_token: Unique device identifier.
        user_id: If provided, only delete if the device belongs to this user.

    Returns:
        True if a device was removed, False if not found.
    """
    from sqlalchemy import and_

    conditions = [DeviceRegistration.device_token == device_token]
    if user_id is not None:
        conditions.append(DeviceRegistration.user_id == user_id)

    result = await db.execute(delete(DeviceRegistration).where(and_(*conditions)))
    await db.commit()
    removed = result.rowcount > 0
    if removed:
        logger.info(
            "Device unregistered",
            device_token=device_token[:8] + "...",
        )
    return removed


async def get_devices_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[DeviceRegistration]:
    """List active devices for a user.

    Args:
        db: Database session.
        user_id: User's UUID.

    Returns:
        List of registered devices.
    """
    result = await db.execute(
        select(DeviceRegistration)
        .where(DeviceRegistration.user_id == user_id)
        .order_by(DeviceRegistration.last_seen_at.desc())
    )
    return list(result.scalars().all())


async def cleanup_stale_devices(
    db: AsyncSession,
    max_age_days: int = 30,
) -> int:
    """Remove devices not seen in the given number of days.

    Args:
        db: Database session.
        max_age_days: Maximum age in days before cleanup.

    Returns:
        Number of devices removed.
    """
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    result = await db.execute(
        delete(DeviceRegistration).where(DeviceRegistration.last_seen_at < cutoff)
    )
    await db.commit()
    count = result.rowcount
    if count > 0:
        logger.info("Cleaned up stale devices", count=count, max_age_days=max_age_days)
    return count
