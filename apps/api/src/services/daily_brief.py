"""Story 5.3: Daily brief generation service.

Aggregates glucose and pump data, generates AI-powered analysis briefs.
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.daily_brief import DailyBrief
from src.models.glucose import GlucoseReading
from src.models.pump_data import PumpEvent, PumpEventType
from src.models.user import User
from src.schemas.ai_response import AIMessage
from src.schemas.daily_brief import DailyBriefMetrics
from src.services.ai_client import get_ai_client
from src.services.brief_notifier import notify_user_of_brief

logger = get_logger(__name__)

# Glucose range thresholds (mg/dL)
LOW_THRESHOLD = 70
HIGH_THRESHOLD = 180

# Minimum readings required to generate a meaningful brief
MIN_READINGS = 12

SYSTEM_PROMPT = """\
You are a diabetes management assistant analyzing glucose and insulin data. \
Provide a concise, supportive daily brief for a person with Type 1 diabetes \
using a Tandem insulin pump with Control-IQ and a Dexcom G7 CGM.

Guidelines:
- Be concise but informative (3-5 paragraphs)
- Highlight patterns (post-meal spikes, overnight trends, time-in-range)
- Note Control-IQ corrections and what they suggest
- Use encouraging, non-judgmental language
- Do NOT recommend specific insulin dose changes (that is for their endocrinologist)
- Focus on actionable observations the user can discuss with their care team
- Reference specific numbers from the data provided\
"""


def _build_analysis_prompt(metrics: DailyBriefMetrics, hours: int) -> str:
    """Build the user prompt with glucose and pump metrics.

    Args:
        metrics: Calculated metrics for the period.
        hours: Number of hours analyzed.

    Returns:
        Formatted prompt string for the AI provider.
    """
    lines = [
        f"Analyze the following {hours}-hour glucose and insulin summary:",
        "",
        f"- Readings: {metrics.readings_count}",
        f"- Average glucose: {metrics.average_glucose:.0f} mg/dL",
        f"- Time in range (70-180): {metrics.time_in_range_pct:.1f}%",
        f"- Low readings (<{LOW_THRESHOLD}): {metrics.low_count}",
        f"- High readings (>{HIGH_THRESHOLD}): {metrics.high_count}",
        f"- Control-IQ auto-corrections: {metrics.correction_count}",
    ]

    if metrics.total_insulin is not None:
        lines.append(f"- Total insulin delivered: {metrics.total_insulin:.1f} units")

    lines.append("")
    lines.append(
        "Provide a daily brief summarizing key patterns, "
        "notable events, and observations."
    )

    return "\n".join(lines)


async def calculate_metrics(
    user_id: "str | object",
    db: AsyncSession,
    period_start: datetime,
    period_end: datetime,
) -> DailyBriefMetrics:
    """Calculate glucose and pump metrics for a time period.

    Args:
        user_id: User's UUID.
        db: Database session.
        period_start: Start of analysis period.
        period_end: End of analysis period.

    Returns:
        Calculated metrics for the period.
    """
    # Query glucose readings for the period
    readings_result = await db.execute(
        select(GlucoseReading.value).where(
            GlucoseReading.user_id == user_id,
            GlucoseReading.reading_timestamp >= period_start,
            GlucoseReading.reading_timestamp < period_end,
        )
    )
    values = [row[0] for row in readings_result.all()]

    readings_count = len(values)
    if readings_count == 0:
        return DailyBriefMetrics(
            time_in_range_pct=0.0,
            average_glucose=0.0,
            low_count=0,
            high_count=0,
            readings_count=0,
            correction_count=0,
            total_insulin=None,
        )

    in_range = sum(1 for v in values if LOW_THRESHOLD <= v <= HIGH_THRESHOLD)
    low_count = sum(1 for v in values if v < LOW_THRESHOLD)
    high_count = sum(1 for v in values if v > HIGH_THRESHOLD)
    time_in_range_pct = (in_range / readings_count) * 100
    average_glucose = sum(values) / readings_count

    # Query pump events for Control-IQ corrections
    correction_result = await db.execute(
        select(func.count()).where(
            PumpEvent.user_id == user_id,
            PumpEvent.event_timestamp >= period_start,
            PumpEvent.event_timestamp < period_end,
            PumpEvent.event_type == PumpEventType.CORRECTION,
            PumpEvent.is_automated.is_(True),
        )
    )
    correction_count = correction_result.scalar() or 0

    # Query total insulin delivered
    insulin_result = await db.execute(
        select(func.sum(PumpEvent.units)).where(
            PumpEvent.user_id == user_id,
            PumpEvent.event_timestamp >= period_start,
            PumpEvent.event_timestamp < period_end,
            PumpEvent.units.is_not(None),
        )
    )
    total_insulin = insulin_result.scalar()

    return DailyBriefMetrics(
        time_in_range_pct=round(time_in_range_pct, 1),
        average_glucose=round(average_glucose, 1),
        low_count=low_count,
        high_count=high_count,
        readings_count=readings_count,
        correction_count=correction_count,
        total_insulin=round(total_insulin, 1) if total_insulin is not None else None,
    )


async def generate_daily_brief(
    user: User,
    db: AsyncSession,
    hours: int = 24,
) -> DailyBrief:
    """Generate a daily brief for a user.

    Aggregates glucose and pump data, calls the AI provider,
    and stores the result.

    Args:
        user: The authenticated user.
        db: Database session.
        hours: Number of hours to analyze.

    Returns:
        The created DailyBrief record.

    Raises:
        HTTPException: 400 if insufficient data, 404 if no AI provider.
    """
    period_end = datetime.now(UTC)
    period_start = period_end - timedelta(hours=hours)

    # Calculate metrics
    metrics = await calculate_metrics(user.id, db, period_start, period_end)

    if metrics.readings_count < MIN_READINGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Insufficient glucose data: {metrics.readings_count} readings "
                f"found, minimum {MIN_READINGS} required for analysis."
            ),
        )

    # Get AI client (raises 404 if not configured)
    ai_client = await get_ai_client(user, db)

    # Build prompt and generate
    user_prompt = _build_analysis_prompt(metrics, hours)

    logger.info(
        "Generating daily brief",
        user_id=str(user.id),
        readings=metrics.readings_count,
        hours=hours,
    )

    ai_response = await ai_client.generate(
        messages=[AIMessage(role="user", content=user_prompt)],
        system_prompt=SYSTEM_PROMPT,
    )

    # Store the brief
    brief = DailyBrief(
        user_id=user.id,
        period_start=period_start,
        period_end=period_end,
        time_in_range_pct=metrics.time_in_range_pct,
        average_glucose=metrics.average_glucose,
        low_count=metrics.low_count,
        high_count=metrics.high_count,
        readings_count=metrics.readings_count,
        correction_count=metrics.correction_count,
        total_insulin=metrics.total_insulin,
        ai_summary=ai_response.content,
        ai_model=ai_response.model,
        ai_provider=ai_response.provider.value,
        input_tokens=ai_response.usage.input_tokens,
        output_tokens=ai_response.usage.output_tokens,
    )

    db.add(brief)
    await db.commit()
    await db.refresh(brief)

    logger.info(
        "Daily brief generated",
        user_id=str(user.id),
        brief_id=str(brief.id),
        tir=metrics.time_in_range_pct,
    )

    # Story 7.3: Telegram delivery
    try:
        await notify_user_of_brief(db, user.id, brief)
    except Exception as e:
        logger.warning(
            "Telegram brief delivery failed",
            user_id=str(user.id),
            error=str(e),
        )

    return brief


async def list_briefs(
    user_id: "str | object",
    db: AsyncSession,
    limit: int = 10,
    offset: int = 0,
) -> tuple[list[DailyBrief], int]:
    """List daily briefs for a user.

    Args:
        user_id: User's UUID.
        db: Database session.
        limit: Maximum number of briefs to return.
        offset: Number of briefs to skip.

    Returns:
        Tuple of (briefs list, total count).
    """
    # Get total count
    count_result = await db.execute(
        select(func.count()).where(DailyBrief.user_id == user_id)
    )
    total = count_result.scalar() or 0

    # Get paginated briefs
    result = await db.execute(
        select(DailyBrief)
        .where(DailyBrief.user_id == user_id)
        .order_by(DailyBrief.period_end.desc())
        .limit(limit)
        .offset(offset)
    )
    briefs = list(result.scalars().all())

    return briefs, total


async def get_brief_by_id(
    brief_id: "str | object",
    user_id: "str | object",
    db: AsyncSession,
) -> DailyBrief:
    """Get a specific daily brief by ID.

    Args:
        brief_id: Brief UUID.
        user_id: User's UUID (for ownership check).
        db: Database session.

    Returns:
        The requested DailyBrief.

    Raises:
        HTTPException: 404 if not found.
    """
    result = await db.execute(
        select(DailyBrief).where(
            DailyBrief.id == brief_id,
            DailyBrief.user_id == user_id,
        )
    )
    brief = result.scalar_one_or_none()

    if not brief:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Daily brief not found",
        )

    return brief
