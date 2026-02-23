"""Safety limits service.

Manages user safety limits configuration with get-or-create pattern.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.safety_limits import SafetyLimits
from src.schemas.safety_limits import SafetyLimitsUpdate

logger = get_logger(__name__)


async def get_or_create_safety_limits(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> SafetyLimits:
    """Get the user's safety limits, creating defaults if none exist.

    Args:
        user_id: User's UUID.
        db: Database session.

    Returns:
        The user's SafetyLimits record.
    """
    result = await db.execute(
        select(SafetyLimits).where(SafetyLimits.user_id == user_id)
    )
    safety_limits = result.scalar_one_or_none()

    if safety_limits is None:
        safety_limits = SafetyLimits(user_id=user_id)
        db.add(safety_limits)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            result = await db.execute(
                select(SafetyLimits).where(SafetyLimits.user_id == user_id)
            )
            safety_limits = result.scalar_one()
            return safety_limits
        await db.refresh(safety_limits)

        logger.info(
            "Created default safety limits",
            user_id=str(user_id),
        )

    return safety_limits


async def update_safety_limits(
    user_id: uuid.UUID,
    updates: SafetyLimitsUpdate,
    db: AsyncSession,
) -> SafetyLimits:
    """Update the user's safety limits.

    Only fields provided in the request are updated. Validates
    ordering: min_glucose < max_glucose after merge with existing values.

    Args:
        user_id: User's UUID.
        updates: Partial update with new safety limit values.
        db: Database session.

    Returns:
        The updated SafetyLimits record.

    Raises:
        ValueError: If glucose ordering is invalid after merge.
    """
    # Ensure the row exists, then re-fetch with FOR UPDATE to prevent
    # concurrent PATCH requests from interleaving reads and writes.
    await get_or_create_safety_limits(user_id, db)

    result = await db.execute(
        select(SafetyLimits).where(SafetyLimits.user_id == user_id).with_for_update()
    )
    safety_limits = result.scalar_one()

    new_min = (
        updates.min_glucose_mgdl
        if updates.min_glucose_mgdl is not None
        else safety_limits.min_glucose_mgdl
    )
    new_max = (
        updates.max_glucose_mgdl
        if updates.max_glucose_mgdl is not None
        else safety_limits.max_glucose_mgdl
    )

    if new_min >= new_max:
        msg = (
            f"min_glucose_mgdl ({new_min}) must be less than "
            f"max_glucose_mgdl ({new_max})"
        )
        logger.warning(
            "Safety limits validation failed",
            user_id=str(user_id),
            min_glucose_mgdl=new_min,
            max_glucose_mgdl=new_max,
        )
        raise ValueError(msg)

    update_data = updates.model_dump(exclude_none=True)

    # Capture before-values for audit trail
    old_values = {field: getattr(safety_limits, field) for field in update_data}

    for field, value in update_data.items():
        setattr(safety_limits, field, value)

    await db.commit()
    await db.refresh(safety_limits)

    # Log old -> new values for audit trail (safety-critical changes)
    new_values = {field: getattr(safety_limits, field) for field in update_data}
    logger.info(
        "Updated safety limits",
        user_id=str(user_id),
        fields=list(update_data.keys()),
        old_values=old_values,
        new_values=new_values,
    )

    return safety_limits
