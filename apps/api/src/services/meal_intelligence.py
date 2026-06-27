"""Per-user meal-intelligence feature gating.

The meal-intelligence feature (vision carb estimation) is a per-user preference
(``users.meal_intelligence_enabled``), replacing the former global
``MEAL_INTELLIGENCE_ENABLED`` env flag. This module is the single service-layer
home for resolving that value from a user id.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User


async def is_meal_intelligence_enabled(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Return whether the user has the meal-intelligence feature enabled.

    Owner-scoped single-column read for service-layer gates that hold a session
    and a user id but no loaded ``User`` row. A missing user reads as disabled
    (fail-closed).
    """
    enabled = await db.scalar(
        select(User.meal_intelligence_enabled).where(User.id == user_id)
    )
    return bool(enabled)
