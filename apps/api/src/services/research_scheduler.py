"""Story 35.12: Scheduled research pipeline runner.

Runs the AI research pipeline for all users with active research sources.
Each user is processed in isolation -- one failure doesn't block others.
"""

import asyncio

from sqlalchemy import distinct, select

from src.database import get_session_maker
from src.logging_config import get_logger
from src.models.research_source import ResearchSource
from src.services.ai_researcher import ai_research_for_user

logger = get_logger(__name__)


async def run_research_pipeline_all_users() -> None:
    """Run the research pipeline for all users with configured sources.

    This job is triggered by APScheduler on a weekly cadence.
    Each user gets their own database session for isolation.
    """
    logger.info("Starting scheduled AI research pipeline")

    async with get_session_maker()() as db:
        result = await db.execute(
            select(distinct(ResearchSource.user_id)).where(
                ResearchSource.is_active.is_(True)
            )
        )
        user_ids = [row[0] for row in result.all()]

    if not user_ids:
        logger.info("No users with active research sources")
        return

    logger.info("Research pipeline: processing users", count=len(user_ids))

    success = 0
    errors = 0

    for user_id in user_ids:
        try:
            async with get_session_maker()() as user_db:
                await ai_research_for_user(user_db, user_id)
                success += 1
        except Exception:
            logger.error(
                "Research pipeline failed for user",
                user_id=str(user_id),
                exc_info=True,
            )
            errors += 1

        # Rate limiting between users
        await asyncio.sleep(2)

    logger.info(
        "Scheduled AI research pipeline completed",
        users_processed=success,
        users_failed=errors,
    )
