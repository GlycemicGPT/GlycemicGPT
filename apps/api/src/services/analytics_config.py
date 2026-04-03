"""Analytics configuration service.

Manages user analytics day boundary setting and display labels
with get-or-create pattern.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.analytics_config import AnalyticsConfig
from src.schemas.analytics_config import AnalyticsConfigUpdate

logger = get_logger(__name__)


async def get_boundary_hour(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> int:
    """Get the user's analytics day boundary hour (read-only, no side effects).

    Returns the configured boundary hour, or 0 (midnight) if no config exists.
    Safe to call from GET endpoints without creating database records.
    """
    result = await db.execute(
        select(AnalyticsConfig.day_boundary_hour).where(
            AnalyticsConfig.user_id == user_id
        )
    )
    value = result.scalar_one_or_none()
    return value if value is not None else 0


async def get_or_create_config(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> AnalyticsConfig:
    """Get the user's analytics config, creating defaults if none exist.

    Args:
        user_id: User's UUID.
        db: Database session.

    Returns:
        The user's AnalyticsConfig record.
    """
    result = await db.execute(
        select(AnalyticsConfig).where(AnalyticsConfig.user_id == user_id)
    )
    config = result.scalar_one_or_none()

    if config is None:
        config = AnalyticsConfig(user_id=user_id)
        db.add(config)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            result = await db.execute(
                select(AnalyticsConfig).where(AnalyticsConfig.user_id == user_id)
            )
            config = result.scalar_one()
            return config
        await db.refresh(config)

        logger.info(
            "Created default analytics config",
            user_id=str(user_id),
        )

    return config


async def update_config(
    user_id: uuid.UUID,
    updates: AnalyticsConfigUpdate,
    db: AsyncSession,
) -> AnalyticsConfig:
    """Update the user's analytics configuration.

    display_labels uses full-replace semantics -- the entire array is
    replaced, not merged.

    Args:
        user_id: User's UUID.
        updates: Partial update with new config values.
        db: Database session.

    Returns:
        The updated AnalyticsConfig record.
    """
    config = await get_or_create_config(user_id, db)

    update_data = updates.model_dump(exclude_none=True)
    if not update_data:
        return config

    # display_labels: full-replace (convert Pydantic models to dicts)
    if "display_labels" in update_data:
        raw_labels = update_data["display_labels"]
        update_data["display_labels"] = [
            item if isinstance(item, dict) else item for item in raw_labels
        ]

    for field, value in update_data.items():
        setattr(config, field, value)

    await db.commit()
    await db.refresh(config)

    logger.info(
        "Updated analytics config",
        user_id=str(user_id),
        fields=list(update_data.keys()),
    )

    return config
