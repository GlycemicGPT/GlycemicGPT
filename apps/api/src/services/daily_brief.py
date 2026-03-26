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
from src.schemas.daily_brief import DailyBriefMetrics, InsulinBreakdown
from src.services.ai_client import get_ai_client
from src.services.brief_notifier import notify_user_of_brief
from src.services.diabetes_context import (
    format_iob_for_prompt,
    format_pump_profile_for_prompt,
    get_pump_profile_summary,
)
from src.services.safety_validation import log_safety_validation, validate_ai_suggestion

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
- When pump profile data is provided, reference the user's actual basal rates, \
correction factors, and carb ratios when discussing patterns
- When IoB data is provided, factor current insulin on board into your analysis
- Use encouraging, non-judgmental language
- Do NOT recommend specific insulin dose changes (that is for their endocrinologist)
- Focus on actionable observations the user can discuss with their care team
- Reference specific numbers from the data provided\
"""


def _build_analysis_prompt(
    metrics: DailyBriefMetrics,
    hours: int,
    profile_context: str | None = None,
    iob_context: str | None = None,
) -> str:
    """Build the user prompt with glucose and pump metrics.

    Args:
        metrics: Calculated metrics for the period.
        hours: Number of hours analyzed.
        profile_context: Optional pump profile text block.
        iob_context: Optional IoB text block.

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

    if metrics.insulin_breakdown:
        bd = metrics.insulin_breakdown
        lines.append(f"- Total insulin delivered: {bd.total_units:.1f} units")
        lines.append(f"  - Manual boluses: {bd.bolus_count} ({bd.bolus_units:.1f}u)")
        lines.append(
            f"  - Manual corrections: {bd.correction_count} ({bd.correction_units:.1f}u)"
        )
        lines.append(
            f"  - Auto-corrections (Control-IQ): {bd.auto_correction_count} ({bd.auto_correction_units:.1f}u)"
        )
        lines.append(f"  - Basal delivery (estimated): {bd.basal_units:.1f}u")
    elif metrics.total_insulin is not None:
        lines.append(f"- Total insulin delivered: {metrics.total_insulin:.1f} units")

    if profile_context:
        lines.append("")
        lines.append(profile_context)

    if iob_context:
        lines.append("")
        lines.append(iob_context)

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

    # ── Insulin breakdown ──
    # Bolus + correction events have discrete delivery amounts in units.
    # Basal events store the *rate* (u/hr) not doses, so we integrate
    # rate x time between consecutive events to estimate basal delivery.

    # Manual boluses
    bolus_result = await db.execute(
        select(func.count(), func.coalesce(func.sum(PumpEvent.units), 0.0)).where(
            PumpEvent.user_id == user_id,
            PumpEvent.event_timestamp >= period_start,
            PumpEvent.event_timestamp < period_end,
            PumpEvent.event_type == PumpEventType.BOLUS,
            PumpEvent.units.is_not(None),
        )
    )
    bolus_row = bolus_result.one()
    bolus_count = bolus_row[0] or 0
    bolus_units = float(bolus_row[1] or 0)

    # Manual corrections (user-initiated, not automated)
    manual_corr_result = await db.execute(
        select(func.count(), func.coalesce(func.sum(PumpEvent.units), 0.0)).where(
            PumpEvent.user_id == user_id,
            PumpEvent.event_timestamp >= period_start,
            PumpEvent.event_timestamp < period_end,
            PumpEvent.event_type == PumpEventType.CORRECTION,
            PumpEvent.is_automated.is_(False),
            PumpEvent.units.is_not(None),
        )
    )
    manual_corr_row = manual_corr_result.one()
    manual_corr_count = manual_corr_row[0] or 0
    manual_corr_units = float(manual_corr_row[1] or 0)

    # Auto-corrections (Control-IQ)
    auto_corr_result = await db.execute(
        select(func.count(), func.coalesce(func.sum(PumpEvent.units), 0.0)).where(
            PumpEvent.user_id == user_id,
            PumpEvent.event_timestamp >= period_start,
            PumpEvent.event_timestamp < period_end,
            PumpEvent.event_type == PumpEventType.CORRECTION,
            PumpEvent.is_automated.is_(True),
            PumpEvent.units.is_not(None),
        )
    )
    auto_corr_row = auto_corr_result.one()
    auto_corr_count = auto_corr_row[0] or 0
    auto_corr_units = float(auto_corr_row[1] or 0)

    # Basal delivery: integrate rate (u/hr) x time across the window.
    # Fetch the last basal event BEFORE the window to seed the active rate,
    # then all in-window events. Each segment runs until the next event or
    # period_end, clamped to the window boundaries.
    seed_result = await db.execute(
        select(PumpEvent.event_timestamp, PumpEvent.units)
        .where(
            PumpEvent.user_id == user_id,
            PumpEvent.event_timestamp < period_start,
            PumpEvent.event_type == PumpEventType.BASAL,
            PumpEvent.units.is_not(None),
        )
        .order_by(PumpEvent.event_timestamp.desc())
        .limit(1)
    )
    basal_result = await db.execute(
        select(PumpEvent.event_timestamp, PumpEvent.units)
        .where(
            PumpEvent.user_id == user_id,
            PumpEvent.event_timestamp >= period_start,
            PumpEvent.event_timestamp < period_end,
            PumpEvent.event_type == PumpEventType.BASAL,
            PumpEvent.units.is_not(None),
        )
        .order_by(PumpEvent.event_timestamp)
    )
    basal_events = list(basal_result.all())
    seed = seed_result.first()
    if seed:
        basal_events.insert(0, seed)

    basal_units = 0.0
    for i, (event_ts, rate) in enumerate(basal_events):
        t_start = max(event_ts, period_start)
        next_ts = basal_events[i + 1][0] if i + 1 < len(basal_events) else period_end
        t_end = min(next_ts, period_end)
        if t_end <= t_start:
            continue
        duration_hours = (t_end - t_start).total_seconds() / 3600
        # Cap individual segment to 1 hour to handle gaps in data
        duration_hours = min(duration_hours, 1.0)
        basal_units += rate * duration_hours

    total_bolus_corr = bolus_units + manual_corr_units + auto_corr_units
    total_insulin = total_bolus_corr + basal_units

    breakdown = InsulinBreakdown(
        bolus_units=round(bolus_units, 1),
        bolus_count=bolus_count,
        correction_units=round(manual_corr_units, 1),
        correction_count=manual_corr_count,
        auto_correction_units=round(auto_corr_units, 1),
        auto_correction_count=auto_corr_count,
        basal_units=round(basal_units, 1),
        total_units=round(total_insulin, 1),
    )

    return DailyBriefMetrics(
        time_in_range_pct=round(time_in_range_pct, 1),
        average_glucose=round(average_glucose, 1),
        low_count=low_count,
        high_count=high_count,
        readings_count=readings_count,
        correction_count=correction_count,
        total_insulin=round(total_insulin, 1) if total_insulin > 0 else None,
        insulin_breakdown=breakdown,
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

    # Fetch pump profile and IoB context (graceful -- missing data is fine)
    profile_context = None
    iob_context = None
    try:
        profile_summary = await get_pump_profile_summary(db, user.id)
        if profile_summary:
            profile_context = format_pump_profile_for_prompt(profile_summary)
    except Exception:
        logger.warning(
            "Failed to fetch pump profile for daily brief",
            user_id=str(user.id),
            exc_info=True,
        )

    try:
        iob_context = await format_iob_for_prompt(db, user.id)
    except Exception:
        logger.warning(
            "Failed to fetch IoB for daily brief",
            user_id=str(user.id),
            exc_info=True,
        )

    # Build prompt and generate
    user_prompt = _build_analysis_prompt(metrics, hours, profile_context, iob_context)

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

    # Safety validation (Story 5.6)
    safety_result = validate_ai_suggestion(ai_response.content, "daily_brief")

    # Store the brief with sanitized text
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
        ai_summary=safety_result.sanitized_text,
        ai_model=ai_response.model,
        ai_provider=ai_response.provider.value,
        input_tokens=ai_response.usage.input_tokens,
        output_tokens=ai_response.usage.output_tokens,
    )

    db.add(brief)
    await db.flush()

    # Log safety validation for audit
    await log_safety_validation(user.id, "daily_brief", brief.id, safety_result, db)

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
