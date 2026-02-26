"""Story 5.4: Meal pattern analysis service.

Detects post-meal glucose spike patterns and generates AI-powered
carb ratio adjustment suggestions.
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.glucose import GlucoseReading
from src.models.meal_analysis import MealAnalysis
from src.models.pump_data import PumpEvent, PumpEventType
from src.models.user import User
from src.schemas.ai_response import AIMessage
from src.schemas.meal_analysis import MealPeriodData
from src.services.ai_client import get_ai_client
from src.services.safety_validation import log_safety_validation, validate_ai_suggestion

logger = get_logger(__name__)

# Post-meal spike threshold (mg/dL)
SPIKE_THRESHOLD = 180

# Post-meal analysis window (hours)
POST_MEAL_WINDOW_HOURS = 2

# Minimum boluses needed for meaningful analysis
MIN_BOLUSES = 5

# Meal period definitions (hour ranges, inclusive start, exclusive end)
MEAL_PERIODS = {
    "breakfast": (5, 10),
    "lunch": (10, 14),
    "dinner": (17, 21),
    "snack": None,  # Everything else
}

SYSTEM_PROMPT = """\
You are a diabetes management assistant analyzing post-meal glucose patterns \
for a person with Type 1 diabetes using a Tandem insulin pump with Control-IQ \
and a Dexcom G7 CGM.

You are reviewing meal pattern data organized by meal period. For each meal \
period, you have the number of boluses analyzed, the number of post-meal spikes \
(>180 mg/dL within 2 hours), the average peak glucose, and the average glucose \
at 2 hours post-bolus.

Guidelines:
- Identify which meal periods have consistent post-meal spikes
- For problematic periods, suggest a specific carb ratio direction \
(e.g., "consider a stronger ratio for breakfast, such as moving from 1:8 to 1:7")
- Explain reasoning: "Your breakfast peaks average X mg/dL despite Control-IQ corrections"
- Use encouraging, non-judgmental language
- Clearly state that these are observations to discuss with their endocrinologist
- Do NOT provide specific dosing instructions; suggest directional changes only
- If data shows good control for a period, acknowledge it
- If insufficient data for a period, note that more data is needed\
"""


def _classify_meal_period(hour: int) -> str:
    """Classify an hour of day into a meal period.

    Args:
        hour: Hour of day (0-23).

    Returns:
        Meal period name.
    """
    for period, hours_range in MEAL_PERIODS.items():
        if hours_range is not None:
            start, end = hours_range
            if start <= hour < end:
                return period
    return "snack"


def _build_meal_prompt(
    meal_periods: list[MealPeriodData],
    total_boluses: int,
    days: int,
) -> str:
    """Build the analysis prompt with meal period data.

    Args:
        meal_periods: Per-period metrics.
        total_boluses: Total boluses analyzed.
        days: Number of days in the analysis window.

    Returns:
        Formatted prompt string.
    """
    lines = [
        f"Analyze the following {days}-day post-meal glucose pattern data:",
        f"Total meal boluses analyzed: {total_boluses}",
        "",
    ]

    for mp in meal_periods:
        lines.append(f"**{mp.period.capitalize()}** ({mp.bolus_count} meals):")
        lines.append(f"  - Post-meal spikes (>180 mg/dL): {mp.spike_count}")
        lines.append(f"  - Average peak glucose: {mp.avg_peak_glucose:.0f} mg/dL")
        lines.append(
            f"  - Average 2hr post-meal glucose: {mp.avg_2hr_glucose:.0f} mg/dL"
        )
        if mp.bolus_count > 0:
            spike_pct = (mp.spike_count / mp.bolus_count) * 100
            lines.append(f"  - Spike rate: {spike_pct:.0f}%")
        lines.append("")

    lines.append(
        "Identify problematic meal periods and suggest carb ratio adjustment "
        "directions. Acknowledge periods with good control."
    )

    return "\n".join(lines)


async def analyze_post_meal_patterns(
    user_id: "str | object",
    db: AsyncSession,
    period_start: datetime,
    period_end: datetime,
) -> list[MealPeriodData]:
    """Analyze post-meal glucose patterns grouped by meal period.

    For each manual bolus event, examines glucose readings in the
    2-hour window after the bolus to detect spikes and calculate
    average post-meal glucose levels.

    Args:
        user_id: User's UUID.
        db: Database session.
        period_start: Start of analysis period.
        period_end: End of analysis period.

    Returns:
        List of MealPeriodData with per-period metrics.
    """
    # Get all manual boluses in the period (meal boluses)
    bolus_result = await db.execute(
        select(PumpEvent).where(
            PumpEvent.user_id == user_id,
            PumpEvent.event_type == PumpEventType.BOLUS,
            PumpEvent.is_automated.is_(False),
            PumpEvent.event_timestamp >= period_start,
            PumpEvent.event_timestamp < period_end,
        )
    )
    boluses = list(bolus_result.scalars().all())

    # Fetch all glucose readings for the full period plus 2hr buffer in one query
    # to avoid N+1 queries (one per bolus)
    extended_end = period_end + timedelta(hours=POST_MEAL_WINDOW_HOURS)
    all_readings_result = await db.execute(
        select(GlucoseReading.reading_timestamp, GlucoseReading.value)
        .where(
            GlucoseReading.user_id == user_id,
            GlucoseReading.reading_timestamp >= period_start,
            GlucoseReading.reading_timestamp <= extended_end,
        )
        .order_by(GlucoseReading.reading_timestamp)
    )
    all_readings = [(row[0], row[1]) for row in all_readings_result.all()]

    # Group boluses by meal period and analyze post-meal glucose
    period_data: dict[str, dict] = {}
    for period_name in ["breakfast", "lunch", "dinner", "snack"]:
        period_data[period_name] = {
            "peaks": [],
            "two_hr_values": [],
            "spike_count": 0,
            "bolus_count": 0,
        }

    for bolus in boluses:
        period = _classify_meal_period(bolus.event_timestamp.hour)
        window_start = bolus.event_timestamp
        window_end = window_start + timedelta(hours=POST_MEAL_WINDOW_HOURS)

        # Filter readings within the post-meal window (already sorted by timestamp)
        readings = [
            value for ts, value in all_readings if window_start <= ts <= window_end
        ]

        if not readings:
            continue

        peak = max(readings)
        # Use the last reading as the approximate 2hr value
        two_hr_value = readings[-1]

        period_data[period]["peaks"].append(peak)
        period_data[period]["two_hr_values"].append(two_hr_value)
        period_data[period]["bolus_count"] += 1
        if peak > SPIKE_THRESHOLD:
            period_data[period]["spike_count"] += 1

    # Build MealPeriodData for each period
    result = []
    for period_name in ["breakfast", "lunch", "dinner", "snack"]:
        data = period_data[period_name]
        bolus_count = data["bolus_count"]

        if bolus_count == 0:
            result.append(
                MealPeriodData(
                    period=period_name,
                    bolus_count=0,
                    spike_count=0,
                    avg_peak_glucose=0.0,
                    avg_2hr_glucose=0.0,
                )
            )
            continue

        avg_peak = sum(data["peaks"]) / len(data["peaks"])
        avg_2hr = sum(data["two_hr_values"]) / len(data["two_hr_values"])

        result.append(
            MealPeriodData(
                period=period_name,
                bolus_count=bolus_count,
                spike_count=data["spike_count"],
                avg_peak_glucose=round(avg_peak, 1),
                avg_2hr_glucose=round(avg_2hr, 1),
            )
        )

    return result


async def generate_meal_analysis(
    user: User,
    db: AsyncSession,
    days: int = 7,
) -> MealAnalysis:
    """Generate a meal pattern analysis with carb ratio suggestions.

    Args:
        user: The authenticated user.
        db: Database session.
        days: Number of days to analyze.

    Returns:
        The created MealAnalysis record.

    Raises:
        HTTPException: 400 if insufficient data, 404 if no AI provider.
    """
    period_end = datetime.now(UTC)
    period_start = period_end - timedelta(days=days)

    # Analyze post-meal patterns
    meal_periods = await analyze_post_meal_patterns(
        user.id, db, period_start, period_end
    )

    total_boluses = sum(mp.bolus_count for mp in meal_periods)

    if total_boluses < MIN_BOLUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Insufficient meal data: {total_boluses} boluses found, "
                f"minimum {MIN_BOLUSES} required for pattern analysis."
            ),
        )

    total_spikes = sum(mp.spike_count for mp in meal_periods)
    # Weighted average of peaks across all meal periods
    weighted_sum = sum(
        mp.avg_peak_glucose * mp.bolus_count
        for mp in meal_periods
        if mp.bolus_count > 0
    )
    avg_post_meal_peak = (
        round(weighted_sum / total_boluses, 1) if total_boluses > 0 else 0.0
    )

    # Get AI client
    ai_client = await get_ai_client(user, db)

    # Build prompt and generate
    user_prompt = _build_meal_prompt(meal_periods, total_boluses, days)

    logger.info(
        "Generating meal pattern analysis",
        user_id=str(user.id),
        boluses=total_boluses,
        spikes=total_spikes,
        days=days,
    )

    ai_response = await ai_client.generate(
        messages=[AIMessage(role="user", content=user_prompt)],
        system_prompt=SYSTEM_PROMPT,
    )

    # Safety validation (Story 5.6)
    safety_result = validate_ai_suggestion(ai_response.content, "meal_analysis")

    # Store the analysis with sanitized text
    analysis = MealAnalysis(
        user_id=user.id,
        period_start=period_start,
        period_end=period_end,
        total_boluses=total_boluses,
        total_spikes=total_spikes,
        avg_post_meal_peak=round(avg_post_meal_peak, 1),
        meal_periods_data=[mp.model_dump() for mp in meal_periods],
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
        user.id, "meal_analysis", analysis.id, safety_result, db
    )

    await db.commit()
    await db.refresh(analysis)

    logger.info(
        "Meal pattern analysis generated",
        user_id=str(user.id),
        analysis_id=str(analysis.id),
        spikes=total_spikes,
        safety_status=safety_result.status.value,
    )

    return analysis


async def list_meal_analyses(
    user_id: "str | object",
    db: AsyncSession,
    limit: int = 10,
    offset: int = 0,
) -> tuple[list[MealAnalysis], int]:
    """List meal analyses for a user.

    Args:
        user_id: User's UUID.
        db: Database session.
        limit: Maximum number of analyses to return.
        offset: Number of analyses to skip.

    Returns:
        Tuple of (analyses list, total count).
    """
    count_result = await db.execute(
        select(func.count()).where(MealAnalysis.user_id == user_id)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(MealAnalysis)
        .where(MealAnalysis.user_id == user_id)
        .order_by(MealAnalysis.period_end.desc())
        .limit(limit)
        .offset(offset)
    )
    analyses = list(result.scalars().all())

    return analyses, total


async def get_meal_analysis_by_id(
    analysis_id: "str | object",
    user_id: "str | object",
    db: AsyncSession,
) -> MealAnalysis:
    """Get a specific meal analysis by ID.

    Args:
        analysis_id: Analysis UUID.
        user_id: User's UUID (for ownership check).
        db: Database session.

    Returns:
        The requested MealAnalysis.

    Raises:
        HTTPException: 404 if not found.
    """
    result = await db.execute(
        select(MealAnalysis).where(
            MealAnalysis.id == analysis_id,
            MealAnalysis.user_id == user_id,
        )
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal analysis not found",
        )

    return analysis
