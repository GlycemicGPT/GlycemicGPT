"""Story 5.3: Daily brief generation service.

Aggregates glucose and pump data, generates AI-powered analysis briefs.
"""

import asyncio
import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_session_maker
from src.logging_config import get_logger
from src.models.brief_delivery_config import BriefDeliveryConfig
from src.models.daily_brief import DailyBrief
from src.models.glucose import GlucoseReading
from src.models.pump_data import (
    MAX_BASAL_INJECTION_UNITS,
    PumpEvent,
    PumpEventType,
)
from src.models.user import User
from src.schemas.ai_response import AIMessage
from src.schemas.daily_brief import DailyBriefMetrics, InsulinBreakdown
from src.services.ai_client import get_ai_client
from src.services.brief_notifier import notify_user_of_brief
from src.services.cgm_source import (
    get_excluded_cgm_sources,
    glucose_source_exclusion_clause,
)
from src.services.diabetes_context import (
    format_iob_for_prompt,
    format_meals_for_brief,
    format_pump_profile_for_prompt,
    get_pump_profile_summary,
    verify_meal_citations,
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
- When logged meals are provided, you may reflect them back and ask how they \
went, but treat the carb figures as rough estimates to verify -- never as \
dosing inputs, and never suggest a dose for a meal
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
    meals_context: str | None = None,
) -> str:
    """Build the user prompt with glucose and pump metrics.

    Args:
        metrics: Calculated metrics for the period.
        hours: Number of hours analyzed.
        profile_context: Optional pump profile text block.
        iob_context: Optional IoB text block.
        meals_context: Optional logged-meals text block. Carries
            the reflect-and-ask, never-dose-or-bolus framing; never a dosing
            input.

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
        if bd.basal_injection_count:
            lines.append(
                f"  - Long-acting injections: {bd.basal_injection_count} "
                f"({bd.basal_injection_units:.1f}u)"
            )
    elif metrics.total_insulin is not None:
        lines.append(f"- Total insulin delivered: {metrics.total_insulin:.1f} units")

    if profile_context:
        lines.append("")
        lines.append(profile_context)

    if iob_context:
        lines.append("")
        lines.append(iob_context)

    if meals_context:
        lines.append("")
        lines.append(meals_context)

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
    *,
    excluded_sources: list[str] | None = None,
) -> DailyBriefMetrics:
    """Calculate glucose and pump metrics for a time period.

    Args:
        user_id: User's UUID.
        db: Database session.
        period_start: Start of analysis period.
        period_end: End of analysis period.
        excluded_sources: CGM ``source`` strings to exclude from the glucose
            metrics (Story 43.10 secondary/off sources). The caller resolves
            these once via ``get_excluded_cgm_sources`` so the brief's
            TIR/metrics aren't doubled when two sources report the same sensor.

    Returns:
        Calculated metrics for the period.
    """
    readings_result = await db.execute(
        select(GlucoseReading.value).where(
            GlucoseReading.user_id == user_id,
            GlucoseReading.reading_timestamp >= period_start,
            GlucoseReading.reading_timestamp < period_end,
            *glucose_source_exclusion_clause(excluded_sources),
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

    # Long-acting (basal) pen injections (MDI). Discrete injected amounts in
    # units -- NOT a rate -- so they sum directly (no time integration). Counts
    # toward basal for the therapy picture but kept as its own line. Bounded to
    # the basal-injection limit (corrupt-record guard) -- the lower bolus bound
    # would clip a legitimate large basal dose. Deduplicated by
    # (event_timestamp, units) -- matching the `/insulin/summary` query -- so the
    # same dose imported from both Glooko and Nightscout isn't double-counted in
    # the total fed to the AI brief.
    basal_inj_subq = (
        select(PumpEvent.event_timestamp, PumpEvent.units)
        .where(
            PumpEvent.user_id == user_id,
            PumpEvent.event_timestamp >= period_start,
            PumpEvent.event_timestamp < period_end,
            PumpEvent.event_type == PumpEventType.BASAL_INJECTION,
            PumpEvent.units.is_not(None),
            PumpEvent.units > 0,
            PumpEvent.units <= MAX_BASAL_INJECTION_UNITS,
        )
        .group_by(PumpEvent.event_timestamp, PumpEvent.units)
        .subquery()
    )
    basal_inj_result = await db.execute(
        select(
            func.count(basal_inj_subq.c.units),
            func.coalesce(func.sum(basal_inj_subq.c.units), 0.0),
        )
    )
    basal_inj_row = basal_inj_result.one()
    basal_injection_count = basal_inj_row[0] or 0
    basal_injection_units = float(basal_inj_row[1] or 0)

    total_bolus_corr = bolus_units + manual_corr_units + auto_corr_units
    total_insulin = total_bolus_corr + basal_units + basal_injection_units

    breakdown = InsulinBreakdown(
        bolus_units=round(bolus_units, 1),
        bolus_count=bolus_count,
        correction_units=round(manual_corr_units, 1),
        correction_count=manual_corr_count,
        auto_correction_units=round(auto_corr_units, 1),
        auto_correction_count=auto_corr_count,
        basal_units=round(basal_units, 1),
        basal_injection_units=round(basal_injection_units, 1),
        basal_injection_count=basal_injection_count,
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

    # Resolve the primary-CGM exclusion once (Story 43.10) and thread it into
    # the metrics so the brief reflects the primary source only.
    excluded = await get_excluded_cgm_sources(db, user.id)
    metrics = await calculate_metrics(
        user.id, db, period_start, period_end, excluded_sources=excluded
    )

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

    # Logged meals for the period -- gated on the meal-intelligence
    # feature so the brief stays unchanged while the flag is off.
    meals_context = None
    if settings.meal_intelligence_enabled:
        try:
            meals_context = await format_meals_for_brief(
                db, user.id, period_start, period_end
            )
        except Exception:
            logger.warning(
                "Failed to fetch logged meals for daily brief",
                user_id=str(user.id),
                exc_info=True,
            )

    # Build prompt and generate
    user_prompt = _build_analysis_prompt(
        metrics, hours, profile_context, iob_context, meals_context
    )

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

    # Verify any cited meal carb figure against the period's logged meals before
    # the dosing-safety pass and storage. Anchor ``now`` to
    # ``period_end`` so the time tokens match what the brief rendered.
    verified_text = await verify_meal_citations(
        db,
        user.id,
        ai_response.content,
        surface="daily_brief",
        window_start=period_start,
        window_end=period_end,
        now=period_end,
    )

    # Safety validation (Story 5.6)
    safety_result = validate_ai_suggestion(verified_text, "daily_brief")

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


# ── Scheduled auto-generation (issue #741) ──────────────────────────────────
# Per-user in-process lock: the local-day existence check below is the real
# idempotency guard; this just prevents a slow generation from overlapping the
# next tick for the same user. A multi-replica deployment would instead need a
# DB-level uniqueness constraint on (user, local day) -- single scheduler today.
_brief_locks: dict[uuid.UUID, asyncio.Lock] = {}


def _lock_for(user_id: uuid.UUID) -> asyncio.Lock:
    lock = _brief_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _brief_locks[user_id] = lock
    return lock


def _release_lock(user_id: uuid.UUID, lock: asyncio.Lock) -> None:
    if not getattr(lock, "_waiters", None):
        _brief_locks.pop(user_id, None)


def _local_day_start_utc(now_utc: datetime, tz_name: str) -> tuple[datetime, datetime]:
    """Return (now in the user's tz, UTC instant of the user's local midnight today)."""
    tz = ZoneInfo(tz_name)
    now_local = now_utc.astimezone(tz)
    local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return now_local, local_midnight.astimezone(UTC)


def _brief_due(
    *,
    enabled: bool,
    delivery_time: time,
    now_local: datetime,
    brief_exists_today: bool,
) -> bool:
    """Generate iff enabled, the local clock has reached delivery_time, and no
    brief exists for the local day yet. The last condition gives both idempotency
    and same-day catch-up (a restart after delivery_time still fires that day)."""
    return enabled and not brief_exists_today and now_local.time() >= delivery_time


async def _has_brief_for_local_day(
    db: AsyncSession, user_id: uuid.UUID, local_midnight_utc: datetime
) -> bool:
    """Whether a brief was already generated on the user's current local day."""
    result = await db.execute(
        select(DailyBrief.id)
        .where(
            DailyBrief.user_id == user_id,
            DailyBrief.created_at >= local_midnight_utc,
        )
        .limit(1)
    )
    return result.first() is not None


async def generate_briefs_all_users(now: datetime | None = None) -> None:
    """Scheduled tick: auto-generate a daily brief for each enabled user whose
    local delivery_time has passed and who has no brief for their local day yet.

    Per-user failures (insufficient data, no AI provider, anything else) are
    swallowed so one user never aborts the run.
    """
    now_utc = now or datetime.now(UTC)
    logger.info("Starting scheduled brief generation")

    async with get_session_maker()() as db:
        configs = (
            (
                await db.execute(
                    select(BriefDeliveryConfig).where(
                        BriefDeliveryConfig.enabled.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )

    generated = skipped = errors = 0
    for cfg in configs:
        lock = _lock_for(cfg.user_id)
        async with lock:
            try:
                try:
                    now_local, local_midnight_utc = _local_day_start_utc(
                        now_utc, cfg.timezone
                    )
                except Exception:
                    logger.warning(
                        "Bad brief timezone, skipping user",
                        user_id=str(cfg.user_id),
                        tz=cfg.timezone,
                    )
                    errors += 1
                    continue

                async with get_session_maker()() as user_db:
                    brief_exists = await _has_brief_for_local_day(
                        user_db, cfg.user_id, local_midnight_utc
                    )
                    if not _brief_due(
                        enabled=cfg.enabled,
                        delivery_time=cfg.delivery_time,
                        now_local=now_local,
                        brief_exists_today=brief_exists,
                    ):
                        skipped += 1
                        continue

                    user = (
                        await user_db.execute(
                            select(User).where(
                                User.id == cfg.user_id, User.is_active.is_(True)
                            )
                        )
                    ).scalar_one_or_none()
                    if user is None:
                        skipped += 1
                        continue

                    try:
                        await generate_daily_brief(user, user_db, hours=24)
                        generated += 1
                    except HTTPException as e:
                        # 400 insufficient data / 404 no AI provider -> graceful skip.
                        logger.info(
                            "Brief auto-generation skipped",
                            user_id=str(cfg.user_id),
                            detail=str(e.detail),
                        )
                        skipped += 1
                    except Exception:
                        logger.error(
                            "Brief auto-generation failed",
                            user_id=str(cfg.user_id),
                            exc_info=True,
                        )
                        errors += 1
            except Exception:
                # Any other per-user failure (e.g. a transient DB error on the
                # existence check or user load) must not abort the whole tick.
                logger.error(
                    "Brief generation tick error for user",
                    user_id=str(cfg.user_id),
                    exc_info=True,
                )
                errors += 1
            finally:
                _release_lock(cfg.user_id, lock)

        await asyncio.sleep(0.2)

    logger.info(
        "Scheduled brief generation completed",
        generated=generated,
        skipped=skipped,
        errors=errors,
    )
