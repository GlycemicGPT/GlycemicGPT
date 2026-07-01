"""Story 5.5: Correction factor analysis service.

Evaluates correction bolus outcomes and generates AI-powered
insulin sensitivity factor (ISF) adjustment suggestions.
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.units import (
    GlucoseUnit,
    format_correction_factor_value,
    format_glucose,
    format_glucose_rate,
    glucose_unit_label,
    glucose_unit_prompt_instruction,
)
from src.logging_config import get_logger
from src.models.correction_analysis import CorrectionAnalysis
from src.models.glucose import GlucoseReading
from src.models.pump_data import PumpEvent, PumpEventType
from src.models.user import User
from src.schemas.ai_response import AIMessage
from src.schemas.correction_analysis import TimePeriodData
from src.services.ai_client import get_ai_client
from src.services.cgm_source import glucose_readings_query
from src.services.diabetes_context import (
    PumpProfileSummary,
    build_allowed_glucose,
    format_pump_profile_for_prompt,
    get_pump_profile_summary,
)
from src.services.safety_validation import log_safety_validation, validate_ai_suggestion

logger = get_logger(__name__)

# Glucose target range for evaluating correction outcomes
TARGET_GLUCOSE = 120  # mg/dL — target after correction
LOW_THRESHOLD = 70  # mg/dL — below this = over-correction

# Post-correction evaluation window (hours)
POST_CORRECTION_WINDOW_HOURS = 3

# Minimum BG at event to consider it a correction (not a meal bolus)
CORRECTION_BG_THRESHOLD = 150  # mg/dL

# Minimum corrections needed for meaningful analysis
MIN_CORRECTIONS = 5

# Time-of-day period definitions (hour ranges, inclusive start, exclusive end)
TIME_PERIODS = {
    "overnight": (22, 6),  # Wraps around midnight
    "morning": (6, 12),
    "afternoon": (12, 17),
    "evening": (17, 22),
}


def _build_system_prompt(unit: GlucoseUnit = GlucoseUnit.MGDL) -> str:
    """Build the correction-analysis system prompt in the user's glucose unit.

    Glucose anchors (the over-correction floor) and the ISF rate units render
    in ``unit``; a closing instruction pins the model's output unit.
    The ``1:X`` ISF example renders on the user's scale (a US 1:50 -> 1:2.8 for
    mmol/L), matching how the observed ISF and the pump's configured correction
    factor are converted, so the comparison the prompt asks for stays same-unit.
    """
    over_floor = format_glucose(LOW_THRESHOLD, unit)
    unit_label = glucose_unit_label(unit)
    cf_example = format_correction_factor_value(50, unit)
    return f"""\
You are a diabetes management assistant analyzing correction bolus outcomes \
for a person with Type 1 diabetes using a Tandem insulin pump with Control-IQ \
and a Dexcom G7 CGM.

You are reviewing correction factor (insulin sensitivity factor / ISF) data \
organized by time of day. For each time period, you have the number of \
corrections analyzed, how many under-corrected (glucose stayed above target) \
vs over-corrected (glucose dropped below {over_floor}), the average observed ISF \
({unit_label} drop per unit of insulin), and the average glucose drop.

When the user's pump profile is provided, compare the observed ISF against \
the user's currently configured correction factors for each time period. \
Reference the current configured values when explaining the pattern, but keep \
recommendations directional only (e.g., "your morning ISF is currently 1:{cf_example} \
but observed corrections suggest it may be weaker than needed for this period").

Guidelines:
- Identify which time periods show consistent under- or over-correction
- For problematic periods, suggest whether the factor may need to be stronger \
or weaker, using the current ISF only as context
- Explain reasoning: "Your morning corrections average only X {unit_label} drop per \
unit, suggesting your ISF may be too weak for this period"
- Use encouraging, non-judgmental language
- Clearly state that these are observations to discuss with their endocrinologist
- Do NOT provide specific dosing instructions; suggest directional changes only
- If data shows effective corrections for a period, acknowledge it
- If insufficient data for a period, note that more data is needed
- Account for the fact that Control-IQ may have also delivered automated \
corrections that affect the observed glucose response
- {glucose_unit_prompt_instruction(unit)}\
"""


def _classify_time_period(hour: int) -> str:
    """Classify an hour of day into a time-of-day period.

    Args:
        hour: Hour of day (0-23).

    Returns:
        Time period name.
    """
    for period, hours_range in TIME_PERIODS.items():
        start, end = hours_range
        if start <= end:
            # Normal range (e.g., morning: 6-12)
            if start <= hour < end:
                return period
        else:
            # Wraps around midnight (e.g., overnight: 22-6)
            if hour >= start or hour < end:
                return period
    return "overnight"


def build_correction_prompt(
    time_periods: list[TimePeriodData],
    total_corrections: int,
    days: int,
    profile_summary: PumpProfileSummary | None = None,
    unit: GlucoseUnit = GlucoseUnit.MGDL,
) -> str:
    """Build the analysis prompt with time period data.

    Args:
        time_periods: Per-period metrics.
        total_corrections: Total corrections analyzed.
        days: Number of days in the analysis window.
        profile_summary: Optional pump profile for ISF context.
        unit: The user's glucose display unit. The over/under anchors, the
            observed ISF rate, and the average glucose drop render in it; the
            ±20% safety math downstream is unit-relative and unchanged.

    Returns:
        Formatted prompt string.
    """
    target = format_glucose(TARGET_GLUCOSE, unit)
    low = format_glucose(LOW_THRESHOLD, unit)
    lines = [
        f"Analyze the following {days}-day correction bolus outcome data:",
        f"Total correction boluses analyzed: {total_corrections}",
        "",
    ]

    for tp in time_periods:
        lines.append(
            f"**{tp.period.capitalize()}** ({tp.correction_count} corrections):"
        )
        lines.append(
            f"  - Under-corrections (glucose stayed >{target}): {tp.under_count}"
        )
        lines.append(f"  - Over-corrections (glucose dropped <{low}): {tp.over_count}")
        lines.append(
            f"  - Average observed ISF: {format_glucose_rate(tp.avg_observed_isf, unit)}"
        )
        lines.append(
            f"  - Average glucose drop: {format_glucose(tp.avg_glucose_drop, unit)}"
        )
        if tp.correction_count > 0:
            effective = tp.correction_count - tp.under_count - tp.over_count
            eff_pct = (effective / tp.correction_count) * 100
            lines.append(f"  - Effective correction rate: {eff_pct:.0f}%")
        lines.append("")

    if profile_summary:
        lines.append(format_pump_profile_for_prompt(profile_summary, unit))
        lines.append("")

    lines.append(
        "Identify time periods with consistent under- or over-correction "
        "and suggest correction factor adjustment directions. "
        "Acknowledge periods with effective corrections."
    )

    return "\n".join(lines)


_build_correction_prompt = build_correction_prompt


async def analyze_correction_outcomes(
    user_id: "str | object",
    db: AsyncSession,
    period_start: datetime,
    period_end: datetime,
) -> list[TimePeriodData]:
    """Analyze correction bolus outcomes grouped by time-of-day period.

    For each manual correction bolus, examines glucose readings in the
    3-hour window after the bolus to evaluate whether the correction
    was effective, under-corrected, or over-corrected.

    Args:
        user_id: User's UUID.
        db: Database session.
        period_start: Start of analysis period.
        period_end: End of analysis period.

    Returns:
        List of TimePeriodData with per-period metrics.
    """
    # Get all manual boluses with BG context (correction boluses have high BG)
    bolus_result = await db.execute(
        select(PumpEvent).where(
            PumpEvent.user_id == user_id,
            PumpEvent.event_type == PumpEventType.BOLUS,
            PumpEvent.is_automated.is_(False),
            PumpEvent.bg_at_event >= CORRECTION_BG_THRESHOLD,
            PumpEvent.units > 0,
            PumpEvent.event_timestamp >= period_start,
            PumpEvent.event_timestamp < period_end,
        )
    )
    corrections = list(bolus_result.scalars().all())

    # Fetch all glucose readings for the full period plus correction window.
    # Primary CGM source only (GLY-123) so observed-ISF isn't computed against a
    # non-primary source reposting the same sensor.
    extended_end = period_end + timedelta(hours=POST_CORRECTION_WINDOW_HOURS)
    readings_stmt = (
        (
            await glucose_readings_query(
                db,
                user_id,
                entities=(GlucoseReading.reading_timestamp, GlucoseReading.value),
            )
        )
        .where(
            GlucoseReading.reading_timestamp >= period_start,
            GlucoseReading.reading_timestamp <= extended_end,
        )
        .order_by(GlucoseReading.reading_timestamp)
    )
    all_readings_result = await db.execute(readings_stmt)
    all_readings = [(row[0], row[1]) for row in all_readings_result.all()]

    # Group corrections by time period and analyze outcomes
    period_data: dict[str, dict] = {}
    for period_name in ["overnight", "morning", "afternoon", "evening"]:
        period_data[period_name] = {
            "drops": [],
            "isf_values": [],
            "under_count": 0,
            "over_count": 0,
            "correction_count": 0,
        }

    for correction in corrections:
        period = _classify_time_period(correction.event_timestamp.hour)
        window_start = correction.event_timestamp
        window_end = window_start + timedelta(hours=POST_CORRECTION_WINDOW_HOURS)

        # Filter readings after the correction (strict lower bound excludes
        # the reading at correction time itself)
        readings = [
            value for ts, value in all_readings if window_start < ts <= window_end
        ]

        if not readings or correction.units is None or correction.units <= 0:
            continue

        starting_bg = correction.bg_at_event
        # Use the last reading as the approximate post-correction value
        final_glucose = readings[-1]
        glucose_drop = starting_bg - final_glucose

        # Skip corrections where glucose rose (likely concurrent meal)
        if glucose_drop <= 0:
            continue

        observed_isf = glucose_drop / correction.units

        period_data[period]["drops"].append(glucose_drop)
        period_data[period]["isf_values"].append(observed_isf)
        period_data[period]["correction_count"] += 1

        # Evaluate outcome
        if final_glucose > TARGET_GLUCOSE:
            period_data[period]["under_count"] += 1
        elif final_glucose < LOW_THRESHOLD:
            period_data[period]["over_count"] += 1

    # Build TimePeriodData for each period
    result = []
    for period_name in ["overnight", "morning", "afternoon", "evening"]:
        data = period_data[period_name]
        correction_count = data["correction_count"]

        if correction_count == 0:
            result.append(
                TimePeriodData(
                    period=period_name,
                    correction_count=0,
                    under_count=0,
                    over_count=0,
                    avg_observed_isf=0.0,
                    avg_glucose_drop=0.0,
                )
            )
            continue

        avg_isf = sum(data["isf_values"]) / len(data["isf_values"])
        avg_drop = sum(data["drops"]) / len(data["drops"])

        result.append(
            TimePeriodData(
                period=period_name,
                correction_count=correction_count,
                under_count=data["under_count"],
                over_count=data["over_count"],
                avg_observed_isf=round(avg_isf, 1),
                avg_glucose_drop=round(avg_drop, 1),
            )
        )

    return result


async def generate_correction_analysis(
    user: User,
    db: AsyncSession,
    days: int = 7,
) -> CorrectionAnalysis:
    """Generate a correction factor analysis with ISF suggestions.

    Args:
        user: The authenticated user.
        db: Database session.
        days: Number of days to analyze.

    Returns:
        The created CorrectionAnalysis record.

    Raises:
        HTTPException: 400 if insufficient data, 404 if no AI provider.
    """
    period_end = datetime.now(UTC)
    period_start = period_end - timedelta(days=days)

    # The prompt, persisted analysis text, and ISF rate units render in the
    # user's unit; the observed-ISF math stays canonical mg/dL.
    unit = user.glucose_unit

    # Analyze correction outcomes
    time_periods = await analyze_correction_outcomes(
        user.id, db, period_start, period_end
    )

    total_corrections = sum(tp.correction_count for tp in time_periods)

    if total_corrections < MIN_CORRECTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Insufficient correction data: {total_corrections} corrections "
                f"found, minimum {MIN_CORRECTIONS} required for analysis."
            ),
        )

    total_under = sum(tp.under_count for tp in time_periods)
    total_over = sum(tp.over_count for tp in time_periods)

    # Weighted average of observed ISF across all time periods
    weighted_sum = sum(
        tp.avg_observed_isf * tp.correction_count
        for tp in time_periods
        if tp.correction_count > 0
    )
    avg_observed_isf = (
        round(weighted_sum / total_corrections, 1) if total_corrections > 0 else 0.0
    )

    # Get AI client
    ai_client = await get_ai_client(user, db)

    # Fetch pump profile for ISF context (graceful -- missing is fine)
    profile_summary = None
    try:
        profile_summary = await get_pump_profile_summary(db, user.id)
    except Exception:
        logger.warning(
            "Failed to fetch pump profile for correction analysis",
            user_id=str(user.id),
            exc_info=True,
        )

    # Build prompt and generate
    user_prompt = build_correction_prompt(
        time_periods, total_corrections, days, profile_summary, unit
    )

    logger.info(
        "Generating correction factor analysis",
        user_id=str(user.id),
        corrections=total_corrections,
        under=total_under,
        over=total_over,
        days=days,
    )

    ai_response = await ai_client.generate(
        messages=[AIMessage(role="user", content=user_prompt)],
        system_prompt=_build_system_prompt(unit),
    )

    # Safety validation (Story 5.6). Unit-agnostic: the regexes accept either
    # suffix and the ±20% check is unit-relative once a suffix matches. Any
    # glucose figure the model spoke is also flagged if it doesn't trace to the
    # period's readings; a failed allow-set fails open (no glucose flag) rather
    # than break the analysis, matching the pump-profile fetch above. ``extra``
    # admits the derived figures this prompt renders -- the post-correction
    # target, the over-correction threshold, and each period's average glucose
    # drop -- so restating them is not mis-flagged as an unverifiable reading.
    allowed_glucose: list[int] = []
    try:
        allow = await build_allowed_glucose(
            db,
            user.id,
            window_start=period_start,
            window_end=period_end,
            extra=[
                TARGET_GLUCOSE,
                LOW_THRESHOLD,
                *(tp.avg_glucose_drop for tp in time_periods),
            ],
        )
        allowed_glucose = allow.match
    except Exception:
        logger.warning(
            "Failed to build glucose allow-set for correction analysis",
            user_id=str(user.id),
            exc_info=True,
        )
    safety_result = validate_ai_suggestion(
        ai_response.content,
        "correction_analysis",
        records=allowed_glucose,
        unit=unit,
    )

    # Store the analysis with sanitized text
    analysis = CorrectionAnalysis(
        user_id=user.id,
        period_start=period_start,
        period_end=period_end,
        total_corrections=total_corrections,
        under_corrections=total_under,
        over_corrections=total_over,
        avg_observed_isf=avg_observed_isf,
        time_periods_data=[tp.model_dump() for tp in time_periods],
        ai_analysis=safety_result.sanitized_text,
        ai_model=ai_response.model,
        ai_provider=ai_response.provider.value,
        input_tokens=ai_response.usage.input_tokens,
        output_tokens=ai_response.usage.output_tokens,
    )

    db.add(analysis)
    await db.flush()

    # Log safety validation for audit
    await log_safety_validation(
        user.id, "correction_analysis", analysis.id, safety_result, db
    )

    await db.commit()
    await db.refresh(analysis)

    logger.info(
        "Correction factor analysis generated",
        user_id=str(user.id),
        analysis_id=str(analysis.id),
        under=total_under,
        over=total_over,
        safety_status=safety_result.status.value,
    )

    return analysis


async def list_correction_analyses(
    user_id: "str | object",
    db: AsyncSession,
    limit: int = 10,
    offset: int = 0,
) -> tuple[list[CorrectionAnalysis], int]:
    """List correction analyses for a user.

    Args:
        user_id: User's UUID.
        db: Database session.
        limit: Maximum number of analyses to return.
        offset: Number of analyses to skip.

    Returns:
        Tuple of (analyses list, total count).
    """
    count_result = await db.execute(
        select(func.count()).where(CorrectionAnalysis.user_id == user_id)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(CorrectionAnalysis)
        .where(CorrectionAnalysis.user_id == user_id)
        .order_by(CorrectionAnalysis.period_end.desc())
        .limit(limit)
        .offset(offset)
    )
    analyses = list(result.scalars().all())

    return analyses, total


async def get_correction_analysis_by_id(
    analysis_id: "str | object",
    user_id: "str | object",
    db: AsyncSession,
) -> CorrectionAnalysis:
    """Get a specific correction analysis by ID.

    Args:
        analysis_id: Analysis UUID.
        user_id: User's UUID (for ownership check).
        db: Database session.

    Returns:
        The requested CorrectionAnalysis.

    Raises:
        HTTPException: 404 if not found.
    """
    result = await db.execute(
        select(CorrectionAnalysis).where(
            CorrectionAnalysis.id == analysis_id,
            CorrectionAnalysis.user_id == user_id,
        )
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Correction analysis not found",
        )

    return analysis
