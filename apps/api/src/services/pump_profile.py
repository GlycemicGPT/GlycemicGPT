"""Pump profile service.

Retrieves the user's active pump profile for mobile consumption.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.pump_profile import PumpProfile


async def get_active_profile(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> PumpProfile | None:
    """Get the user's most recently synced active pump profile.

    Args:
        user_id: User's UUID.
        db: Database session.

    Returns:
        The active PumpProfile, or None if no profile has been synced.
    """
    result = await db.execute(
        select(PumpProfile)
        .where(PumpProfile.user_id == user_id, PumpProfile.is_active.is_(True))
        .order_by(PumpProfile.synced_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
