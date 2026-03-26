"""Story 35.1: Shared diabetes context builders for AI prompts.

Provides reusable context-building functions that assemble diabetes data
(glucose, IoB, pump activity, Control-IQ summary, user settings, and pump
profile) into formatted text sections for any AI prompt.

Extracted from telegram_chat.py so that daily briefs, meal analysis,
correction analysis, and chat all share the same context pipeline.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.services.alert_notifier import trend_description
from src.services.iob_projection import get_iob_projection, get_user_dia

logger = get_logger(__name__)

# Context time windows
GLUCOSE_CONTEXT_HOURS = 6
PUMP_CONTEXT_HOURS = 6
CONTROL_IQ_SUMMARY_HOURS = 24

# Maximum readings to fetch for glucose context
GLUCOSE_MAX_READINGS = 72  # ~6 hours of 5-min CGM readings

# Default glucose target range when user hasn't configured one
DEFAULT_LOW_TARGET = 70.0
DEFAULT_HIGH_TARGET = 180.0


# ── Pump Profile Summary (structured intermediate) ──


@dataclass
class ProfileSegment:
    """A single time segment from a pump profile."""

    time: str
    start_minutes: int
    basal_rate: float
    correction_factor: float
    carb_ratio: float
    target_bg: float


@dataclass
class PumpProfileSummary:
    """Structured summary of the active pump profile."""

    profile_name: str
    segments: list[ProfileSegment] = field(default_factory=list)
    insulin_duration_min: int | None = None
    max_bolus_units: float | None = None
    cgm_high_alert_mgdl: int | None = None
    cgm_low_alert_mgdl: int | None = None


# ── Section builders ──


async def build_glucose_section(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> str | None:
    """Build glucose summary section from recent CGM readings."""
    from src.models.glucose import GlucoseReading
    from src.models.target_glucose_range import TargetGlucoseRange

    cutoff = datetime.now(UTC) - timedelta(hours=GLUCOSE_CONTEXT_HOURS)

    result = await db.execute(
        select(GlucoseReading)
        .where(
            GlucoseReading.user_id == user_id,
            GlucoseReading.reading_timestamp >= cutoff,
        )
        .order_by(GlucoseReading.reading_timestamp.desc())
        .limit(GLUCOSE_MAX_READINGS)
    )
    readings = list(result.scalars().all())

    if not readings:
        return None

    latest = readings[0]
    values = [r.value for r in readings]
    min_val = min(values)
    max_val = max(values)
    avg_val = sum(values) / len(values)
    trend = trend_description(latest.trend_rate)

    # Calculate time-in-range
    range_result = await db.execute(
        select(TargetGlucoseRange).where(TargetGlucoseRange.user_id == user_id)
    )
    target_range = range_result.scalar_one_or_none()
    low = target_range.low_target if target_range else DEFAULT_LOW_TARGET
    high = target_range.high_target if target_range else DEFAULT_HIGH_TARGET
    in_range = sum(1 for v in values if low <= v <= high)
    tir_pct = (in_range / len(values)) * 100 if values else 0

    lines = [
        f"[Glucose - last {GLUCOSE_CONTEXT_HOURS}h]",
        f"- Current: {latest.value} mg/dL ({trend})",
        f"- Range: {min_val}-{max_val} mg/dL, Avg: {avg_val:.0f} mg/dL",
        f"- Time in range ({low:.0f}-{high:.0f}): {tir_pct:.0f}%",
        f"- Readings: {len(readings)}",
    ]
    return "\n".join(lines)


async def build_iob_section(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> str | None:
    """Build insulin-on-board section from IoB projection."""
    dia = await get_user_dia(db, user_id)
    iob = await get_iob_projection(db, user_id, dia_hours=dia)
    if iob is None:
        return None

    lines = [
        "[Insulin on Board]",
        f"- Current IoB: {iob.projected_iob:.1f} units",
        f"- Projected 30min: {iob.projected_30min:.1f}u, 60min: {iob.projected_60min:.1f}u",
    ]
    if iob.is_stale:
        lines.append(f"- (IoB data is stale: {iob.stale_warning or '>2 hours old'})")
    return "\n".join(lines)


async def build_pump_section(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> str | None:
    """Build pump activity section from recent pump events."""
    from src.models.pump_data import PumpEventType
    from src.services.tandem_sync import get_pump_events

    events = await get_pump_events(db, user_id, hours=PUMP_CONTEXT_HOURS, limit=500)
    if not events:
        return None

    manual_bolus_count = 0
    manual_bolus_units = 0.0
    auto_correction_count = 0
    auto_correction_units = 0.0
    basal_increase_count = 0
    basal_decrease_count = 0
    suspend_count = 0
    last_auto_correction = None

    for event in events:
        if event.event_type == PumpEventType.BOLUS and not event.is_automated:
            manual_bolus_count += 1
            if event.units:
                manual_bolus_units += event.units
        elif event.event_type == PumpEventType.CORRECTION:
            auto_correction_count += 1
            if event.units:
                auto_correction_units += event.units
            if last_auto_correction is None:
                last_auto_correction = event
        elif event.event_type == PumpEventType.BASAL and event.is_automated:
            if event.basal_adjustment_pct is not None:
                if event.basal_adjustment_pct > 0:
                    basal_increase_count += 1
                elif event.basal_adjustment_pct < 0:
                    basal_decrease_count += 1
        elif event.event_type == PumpEventType.SUSPEND:
            suspend_count += 1

    lines = [
        f"[Pump Activity - last {PUMP_CONTEXT_HOURS}h]",
        f"- Manual boluses: {manual_bolus_count} ({manual_bolus_units:.1f}u total)",
        f"- Auto-corrections (Control-IQ): {auto_correction_count} ({auto_correction_units:.1f}u total)",
        f"- Basal adjustments: {basal_increase_count} increases, {basal_decrease_count} decreases",
    ]
    if suspend_count:
        lines.append(f"- Suspends: {suspend_count}")
    if last_auto_correction:
        minutes_ago = int(
            (datetime.now(UTC) - last_auto_correction.event_timestamp).total_seconds()
            / 60
        )
        lines.append(
            f"- Last auto-correction: {last_auto_correction.units or 0:.1f}u ({minutes_ago}min ago)"
        )
    return "\n".join(lines)


async def build_control_iq_section(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> str | None:
    """Build 24h Control-IQ activity summary."""
    from src.services.tandem_sync import get_control_iq_activity

    summary = await get_control_iq_activity(db, user_id, hours=CONTROL_IQ_SUMMARY_HOURS)
    if summary.total_events == 0:
        return None

    lines = [
        f"[Control-IQ Activity - last {CONTROL_IQ_SUMMARY_HOURS}h]",
        f"- Total events: {summary.total_events} ({summary.automated_events} automated, {summary.manual_events} manual)",
        f"- Auto-corrections: {summary.correction_count} ({summary.total_correction_units:.1f}u total)",
        f"- Basal adjustments: {summary.basal_increase_count} up, {summary.basal_decrease_count} down",
    ]
    if summary.avg_basal_adjustment_pct is not None:
        lines.append(
            f"- Avg basal adjustment: {summary.avg_basal_adjustment_pct:+.1f}%"
        )
    if summary.suspend_count:
        lines.append(
            f"- Suspends: {summary.suspend_count} ({summary.automated_suspend_count} automated)"
        )
    mode_parts = []
    if summary.sleep_mode_events:
        mode_parts.append(f"Sleep: {summary.sleep_mode_events}")
    if summary.exercise_mode_events:
        mode_parts.append(f"Exercise: {summary.exercise_mode_events}")
    if summary.standard_mode_events:
        mode_parts.append(f"Standard: {summary.standard_mode_events}")
    if mode_parts:
        lines.append(f"- Mode events: {', '.join(mode_parts)}")
    return "\n".join(lines)


async def build_settings_section(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> str | None:
    """Build user settings section (target range, insulin config)."""
    from src.models.insulin_config import InsulinConfig
    from src.models.target_glucose_range import TargetGlucoseRange

    parts = []

    range_result = await db.execute(
        select(TargetGlucoseRange).where(TargetGlucoseRange.user_id == user_id)
    )
    target_range = range_result.scalar_one_or_none()
    if target_range:
        parts.append(
            f"- Target range: {target_range.low_target:.0f}-{target_range.high_target:.0f} mg/dL"
        )

    config_result = await db.execute(
        select(InsulinConfig).where(InsulinConfig.user_id == user_id)
    )
    insulin_config = config_result.scalar_one_or_none()
    if insulin_config:
        parts.append(
            f"- Insulin: {insulin_config.insulin_type}, DIA: {insulin_config.dia_hours}h"
        )
        parts.append(f"- Onset: {insulin_config.onset_minutes:.0f} minutes")

    if not parts:
        return None

    return "[User Settings]\n" + "\n".join(parts)


async def build_pump_profile_section(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> str | None:
    """Build pump profile section from the active Tandem pump profile.

    Delegates to get_pump_profile_summary + format_pump_profile_for_prompt
    to avoid duplicating formatting logic.
    """
    summary = await get_pump_profile_summary(db, user_id)
    if not summary:
        return None
    return format_pump_profile_for_prompt(summary)


# ── Composite context builder ──


async def build_diabetes_context(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> str:
    """Build comprehensive diabetes context from all available data.

    Assembles 6 independent sections: glucose, IoB, pump activity,
    Control-IQ summary, user settings, and pump profile. Each section
    is independently resilient -- if one fails, the others still populate.

    Args:
        db: Database session.
        user_id: User's UUID.

    Returns:
        A formatted string describing all available diabetes data,
        or a fallback message if no data is available.
    """
    builders = [
        ("glucose", build_glucose_section),
        ("iob", build_iob_section),
        ("pump", build_pump_section),
        ("control_iq", build_control_iq_section),
        ("settings", build_settings_section),
        ("pump_profile", build_pump_profile_section),
    ]

    sections: list[str] = []
    for name, builder in builders:
        try:
            section = await builder(db, user_id)
            if section:
                sections.append(section)
        except Exception:
            logger.warning(
                "Failed to build context section",
                section=name,
                user_id=str(user_id),
                exc_info=True,
            )

    if not sections:
        return "Recent diabetes data: No data available."

    context = "\n\n".join(sections)
    logger.debug(
        "Diabetes context built",
        user_id=str(user_id),
        sections_count=len(sections),
        context_length=len(context),
    )
    return context


# ── Analysis-specific helpers (Story 35.1) ──


async def get_pump_profile_summary(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> PumpProfileSummary | None:
    """Fetch the active pump profile as a structured summary.

    Returns None if no active profile exists. Used by analysis services
    to access pump profile data without formatting it as text.
    """
    from src.models.pump_profile import PumpProfile

    result = await db.execute(
        select(PumpProfile).where(
            PumpProfile.user_id == user_id,
            PumpProfile.is_active == True,  # noqa: E712
        )
    )
    profile = result.scalars().first()
    if not profile:
        return None

    segments = []
    for seg in profile.segments or []:
        if not isinstance(seg, dict):
            continue
        segments.append(
            ProfileSegment(
                time=seg.get("time") or "??",
                start_minutes=seg.get("start_minutes") or 0,
                basal_rate=seg.get("basal_rate") or 0,
                correction_factor=seg.get("correction_factor") or 0,
                carb_ratio=seg.get("carb_ratio") or 0,
                target_bg=seg.get("target_bg") or 0,
            )
        )

    return PumpProfileSummary(
        profile_name=profile.profile_name,
        segments=segments,
        insulin_duration_min=profile.insulin_duration_min,
        max_bolus_units=profile.max_bolus_units,
        cgm_high_alert_mgdl=profile.cgm_high_alert_mgdl,
        cgm_low_alert_mgdl=profile.cgm_low_alert_mgdl,
    )


def _sanitize_for_prompt(value: str) -> str:
    """Strip newlines and control characters from a value before embedding in AI prompts."""
    return value.replace("\n", " ").replace("\r", " ").strip()


def format_pump_profile_for_prompt(summary: PumpProfileSummary) -> str:
    """Format a pump profile summary as a text block for AI prompts.

    Includes all segments with basal rates, correction factors, carb ratios,
    and target BG values. Also includes insulin duration, max bolus, and
    CGM alert thresholds.
    """
    safe_name = _sanitize_for_prompt(summary.profile_name)
    lines = [f'[Pump Profile - "{safe_name}" (active)]']
    for seg in summary.segments:
        safe_time = _sanitize_for_prompt(seg.time)
        lines.append(
            f"- {safe_time}: Basal {seg.basal_rate:.3f} u/hr, "
            f"CF 1:{seg.correction_factor}, CR 1:{seg.carb_ratio:g}, "
            f"Target {seg.target_bg}"
        )

    extras = []
    if summary.insulin_duration_min is not None:
        hours = summary.insulin_duration_min // 60
        mins = summary.insulin_duration_min % 60
        dur_str = f"{hours}hr" + (f" {mins}min" if mins else "")
        extras.append(f"Insulin duration: {dur_str}")
    if summary.max_bolus_units is not None:
        extras.append(f"Max bolus: {summary.max_bolus_units:.1f}u")
    if extras:
        lines.append(f"- {', '.join(extras)}")

    alert_parts = []
    if summary.cgm_high_alert_mgdl is not None:
        alert_parts.append(f"High {summary.cgm_high_alert_mgdl} mg/dL")
    if summary.cgm_low_alert_mgdl is not None:
        alert_parts.append(f"Low {summary.cgm_low_alert_mgdl} mg/dL")
    if alert_parts:
        lines.append(f"- CGM alerts: {', '.join(alert_parts)}")

    return "\n".join(lines)


async def format_iob_for_prompt(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> str | None:
    """Format current IoB data as a text block for AI prompts.

    Delegates to build_iob_section. Kept as a named entry point for
    analysis services that need IoB context without the full composite.

    Returns None if no IoB data is available.
    """
    return await build_iob_section(db, user_id)
