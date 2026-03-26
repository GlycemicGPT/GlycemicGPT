"""Story 9.4: Data purge service.

Provides the ability to permanently delete all user data
while preserving account settings and configuration.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.alert import Alert
from src.models.chat_message import ChatMessage
from src.models.correction_analysis import CorrectionAnalysis
from src.models.daily_brief import DailyBrief
from src.models.escalation_event import EscalationEvent
from src.models.glucose import GlucoseReading
from src.models.meal_analysis import MealAnalysis
from src.models.pump_data import PumpEvent
from src.models.safety_log import SafetyLog
from src.models.suggestion_response import SuggestionResponse

logger = get_logger(__name__)


async def purge_all_user_data(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> dict[str, int]:
    """Permanently delete all user data except account and settings.

    Deletes glucose readings, pump events, AI analysis results,
    and audit records. Preserves the user account, configuration
    preferences (thresholds, ranges, delivery config, retention config,
    escalation config, AI provider config), integrations, emergency
    contacts, caregiver links, and Telegram links.

    All deletions are performed in a single transaction. If any
    deletion fails, the entire transaction is rolled back.

    Args:
        user_id: User's UUID.
        db: Database session.

    Returns:
        Dict with count of deleted records per category.

    Raises:
        Exception: Re-raises after rollback if any deletion fails.
    """
    # Create a durable audit log entry BEFORE deleting any data.
    # This SafetyLog record will itself be deleted as part of the purge,
    # but the structured log output (logger.warning below) provides
    # a durable external record that the purge occurred.
    logger.warning(
        "User data purge initiated",
        user_id=str(user_id),
        timestamp=datetime.now(UTC).isoformat(),
    )

    deleted = {}

    try:
        # ── Glucose data ──
        result = await db.execute(
            delete(GlucoseReading).where(GlucoseReading.user_id == user_id)
        )
        deleted["glucose_readings"] = result.rowcount

        result = await db.execute(delete(PumpEvent).where(PumpEvent.user_id == user_id))
        deleted["pump_events"] = result.rowcount

        # ── Analysis data ──
        # SuggestionResponse before analyses for forward-compatibility
        result = await db.execute(
            delete(SuggestionResponse).where(SuggestionResponse.user_id == user_id)
        )
        deleted["suggestion_responses"] = result.rowcount

        result = await db.execute(
            delete(DailyBrief).where(DailyBrief.user_id == user_id)
        )
        deleted["daily_briefs"] = result.rowcount

        result = await db.execute(
            delete(MealAnalysis).where(MealAnalysis.user_id == user_id)
        )
        deleted["meal_analyses"] = result.rowcount

        result = await db.execute(
            delete(CorrectionAnalysis).where(CorrectionAnalysis.user_id == user_id)
        )
        deleted["correction_analyses"] = result.rowcount

        # ── Audit data ──
        # SafetyLog first (no FK dependencies)
        result = await db.execute(delete(SafetyLog).where(SafetyLog.user_id == user_id))
        deleted["safety_logs"] = result.rowcount

        # EscalationEvent must be deleted before Alert
        # (escalation_events.alert_id -> alerts.id ON DELETE CASCADE)
        result = await db.execute(
            delete(EscalationEvent).where(EscalationEvent.user_id == user_id)
        )
        deleted["escalation_events"] = result.rowcount

        result = await db.execute(delete(Alert).where(Alert.user_id == user_id))
        deleted["alerts"] = result.rowcount

        # ── Chat data (Story 35.3) ──
        result = await db.execute(
            delete(ChatMessage).where(ChatMessage.user_id == user_id)
        )
        deleted["chat_messages"] = result.rowcount

        await db.commit()
    except Exception:
        await db.rollback()
        logger.error(
            "User data purge failed, transaction rolled back",
            user_id=str(user_id),
        )
        raise

    total = sum(deleted.values())
    logger.warning(
        "User data purge completed",
        user_id=str(user_id),
        deleted=deleted,
        total_deleted=total,
    )

    return deleted
