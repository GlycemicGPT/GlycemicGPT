"""Shared dependencies for the meal-intelligence routers.

Both the food-record and common-food routers gate on the same feature flag and
need owner-scoped lookups of a common food. These live here (rather than in one
router importing the other) so the import graph stays acyclic and the
owner-scoping logic has a single home.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.common_food import CommonFood


def require_meal_intelligence() -> None:
    """Reject (as 404) when the meal-intelligence feature flag is off.

    A 404 (rather than 403) keeps the whole feature surface invisible while the
    flag is off, consistent across every meal-intelligence endpoint.
    """
    if not settings.meal_intelligence_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal intelligence is not enabled.",
        )


async def get_owned_common_food(
    common_food_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> CommonFood:
    """Fetch a common food scoped to its owner; 404 if missing (no existence leak)."""
    common_food = await db.scalar(
        select(CommonFood).where(
            CommonFood.id == common_food_id, CommonFood.user_id == user_id
        )
    )
    if common_food is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Common food not found."
        )
    return common_food
