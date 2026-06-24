"""Story 35.1: Shared diabetes context builders for AI prompts.

Provides reusable context-building functions that assemble diabetes data
(glucose, IoB, pump activity, Control-IQ summary, user settings, and pump
profile) into formatted text sections for any AI prompt.

Extracted from telegram_chat.py so that daily briefs, meal analysis,
correction analysis, and chat all share the same context pipeline.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.units import (
    GlucoseUnit,
    format_correction_factor_value,
    format_glucose,
    format_glucose_range,
    format_glucose_value,
)
from src.logging_config import get_logger
from src.services.alert_notifier import trend_description
from src.services.glucose_citation import verify_glucose_citations
from src.services.iob_projection import get_iob_projection, get_user_dia
from src.services.meal_citation import AllowedCarb, verify_carb_citations
from src.services.meal_intelligence import is_meal_intelligence_enabled
from src.vision.carb_contract import (
    MEAL_ESTIMATE_QUALIFIER,
    NEVER_DOSE_PROHIBITION,
    find_dosing_violations,
)

if TYPE_CHECKING:
    from src.models.food_record import FoodRecord

logger = get_logger(__name__)

# Context time windows
GLUCOSE_CONTEXT_HOURS = 6
PUMP_CONTEXT_HOURS = 6
CONTROL_IQ_SUMMARY_HOURS = 24
# Long-acting (basal) injections are typically once or twice daily, so the
# short pump-activity window misses them most of the day. Look back far enough
# to surface the active basal dose + timing for overnight-pattern analysis.
BASAL_INJECTION_CONTEXT_HOURS = 30

# Logged-meal context (meal-intelligence feature). A bounded window
# and record cap keep the prompt lean -- enough to reflect on recent eating
# without bloating context. People log a handful of meals a day, so ~48h / 10
# records covers "what have I been eating lately" for chat.
MEAL_CONTEXT_HOURS = 48
MEAL_MAX_RECORDS = 10
# Above this age, a meal line shows a wall-clock day/time instead of "Nh ago" --
# "73h ago" is harder to place than "Mon 19:30". Independent of the fetch window
# so a longer-period brief still renders old meals readably.
MEAL_RELATIVE_TIME_MAX_HOURS = 48
# Per-meal description cap for prompt rendering. Persisted descriptions are
# already bounded (food_vision._MAX_DESCRIPTION_CHARS), but the context block is
# leaner and a smaller cap keeps the prompt-injection surface small.
MEAL_DESCRIPTION_MAX_LEN = 120

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
    unit: GlucoseUnit = GlucoseUnit.MGDL,
) -> str | None:
    """Build glucose summary section from recent CGM readings.

    Glucose numbers render in ``unit``; the time-in-range membership test stays
    in canonical mg/dL and only the displayed range bounds convert.
    """
    from src.models.glucose import GlucoseReading
    from src.models.target_glucose_range import TargetGlucoseRange
    from src.services.cgm_source import (
        get_excluded_cgm_sources,
        glucose_source_exclusion_clause,
    )

    cutoff = datetime.now(UTC) - timedelta(hours=GLUCOSE_CONTEXT_HOURS)

    # Primary CGM source only (Story 43.10) so the AI's glucose summary
    # isn't doubled when two sources report the same sensor.
    excluded = await get_excluded_cgm_sources(db, user_id)
    result = await db.execute(
        select(GlucoseReading)
        .where(
            GlucoseReading.user_id == user_id,
            GlucoseReading.reading_timestamp >= cutoff,
            *glucose_source_exclusion_clause(excluded),
        )
        .order_by(GlucoseReading.reading_timestamp.desc())
        .limit(GLUCOSE_MAX_READINGS)
    )
    readings = list(result.scalars().all())

    if not readings:
        return None

    # Filter out impossible CGM values before computing aggregates
    valid_readings = [r for r in readings if 20 <= r.value <= 500]
    if not valid_readings:
        return None

    latest = valid_readings[0]
    values = [r.value for r in valid_readings]
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
        f"- Current: {format_glucose(latest.value, unit)} ({trend})",
        f"- Range: {format_glucose_range(min_val, max_val, unit)}, "
        f"Avg: {format_glucose(avg_val, unit)}",
        f"- Time in range "
        f"({format_glucose_value(low, unit)}-{format_glucose_value(high, unit)}): "
        f"{tir_pct:.0f}%",
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
    from src.models.pump_data import PumpEvent, PumpEventType
    from src.services.tandem_sync import get_pump_events

    events = await get_pump_events(db, user_id, hours=PUMP_CONTEXT_HOURS, limit=500)

    # Long-acting (basal) injection lookback -- a once/twice-daily MDI dose
    # falls outside the short pump-activity window most of the time, but the AI
    # needs the active basal dose + timing for overnight-pattern analysis.
    # Fetched over a wider window, independent of the 6h activity events above.
    basal_inj_cutoff = datetime.now(UTC) - timedelta(
        hours=BASAL_INJECTION_CONTEXT_HOURS
    )
    basal_inj_result = await db.execute(
        select(PumpEvent)
        .where(
            PumpEvent.user_id == user_id,
            PumpEvent.event_type == PumpEventType.BASAL_INJECTION,
            PumpEvent.event_timestamp >= basal_inj_cutoff,
            PumpEvent.units.is_not(None),
        )
        .order_by(PumpEvent.event_timestamp.desc())
        .limit(5)
    )
    basal_injections = list(basal_inj_result.scalars().all())

    if not events and not basal_injections:
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
        elif event.event_type == PumpEventType.CORRECTION and event.is_automated:
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

    lines: list[str] = []
    if events:
        lines.extend(
            [
                f"[Pump Activity - last {PUMP_CONTEXT_HOURS}h]",
                f"- Manual boluses: {manual_bolus_count} ({manual_bolus_units:.1f}u total)",
                f"- Auto-corrections (Control-IQ): {auto_correction_count} ({auto_correction_units:.1f}u total)",
                f"- Basal adjustments: {basal_increase_count} increases, {basal_decrease_count} decreases",
            ]
        )
        if suspend_count:
            lines.append(f"- Suspends: {suspend_count}")
        if last_auto_correction:
            minutes_ago = int(
                (
                    datetime.now(UTC) - last_auto_correction.event_timestamp
                ).total_seconds()
                / 60
            )
            lines.append(
                f"- Last auto-correction: {last_auto_correction.units or 0:.1f}u ({minutes_ago}min ago)"
            )

    if basal_injections:
        now = datetime.now(UTC)
        lines.append(
            f"[Long-acting (basal) injections - last {BASAL_INJECTION_CONTEXT_HOURS}h]"
        )
        for inj in basal_injections:
            hours_ago = (now - inj.event_timestamp).total_seconds() / 3600
            # Glooko writes `medication`; Nightscout writes `insulin_type`.
            meta = inj.metadata_json or {}
            med = meta.get("medication") or meta.get("insulin_type")
            med_label = f"{med} " if med else ""
            lines.append(f"- {med_label}{inj.units or 0:.1f}u ({hours_ago:.0f}h ago)")

    return "\n".join(lines)


# ── Logged-meal context ──

# Framing that introduces logged meals to the model. The AI is a mirror and an
# interviewer here, never an advisor (the mirror-and-interviewer charter): it
# reflects the meals back and asks open questions, and it NEVER turns a meal's
# carb estimate into dosing guidance. The carb figures are rough AI guesses --
# the user must never be told it is OK to dose or bolus from them (we never use
# "verify before dosing", which implies dosing off the estimate is fine).
_MEAL_GUIDANCE = (
    "These are meals the user logged. The carb figures are rough AI photo "
    "estimates -- often wrong, are NOT dosing inputs, and the user must never "
    "use them to dose or bolus. Reflect these meals back to the user and ask "
    'open questions about them (for example, "you logged a high-carb dinner -- '
    'how did that sit with you?"). Never tell the user how much to take or what '
    "to eat, never give treatment advice about a meal, and never imply the "
    "estimate is safe to dose from."
)


def _meal_carb_range(record: "FoodRecord") -> tuple[float, float, bool]:
    """Return ``(low, high, is_corrected)`` for a food record.

    Prefers the user's corrected carb values when present -- a correction is the
    user's own truth and supersedes the original AI estimate. Returns whether the
    corrected values were used so the rendered line can label them honestly.

    Corrected values are written as a pair (the ``ck_food_records_corrected_carb_range``
    constraint enforces both-or-neither), so a correction is only honored when
    both bounds are set; a half-populated value falls back to the AI estimate.
    """
    low = record.corrected_carbs_low
    high = record.corrected_carbs_high
    if low is not None and high is not None:
        return low, high, True
    return record.carbs_low, record.carbs_high, False


# Substrings that signal a prompt-injection attempt rather than a food name --
# instruction-override phrasing, chat role markers, special-token / code-fence
# delimiters. A real food description never contains these, so their presence is
# treated as adversarial and the description is dropped to a neutral fallback.
_PROMPT_INJECTION_MARKERS = (
    "ignore previous",
    "ignore all previous",
    "ignore the above",
    "disregard previous",
    "system:",
    "assistant:",
    "developer:",
    "<|",
    "|>",
    "```",
)


def _safe_meal_description(raw: str | None) -> str:
    """Sanitize a food description for embedding in an AI prompt.

    Defense-in-depth: a description is user/AI-controlled and lands in the system
    prompt. Persisted descriptions are already scrubbed of dosing language at
    write time (``food_vision``), but we re-check here -- if any dosing phrasing
    or prompt-injection marker slips through we drop the description to a neutral
    fallback rather than let it reach the model (mirror-and-interviewer charter). Length is
    capped to keep the prompt lean and the injection surface small.
    """
    description = _sanitize_for_prompt(raw or "")
    if not description or find_dosing_violations(description):
        return "logged meal"
    lowered = description.lower()
    if any(marker in lowered for marker in _PROMPT_INJECTION_MARKERS):
        return "logged meal"
    if len(description) > MEAL_DESCRIPTION_MAX_LEN:
        description = description[:MEAL_DESCRIPTION_MAX_LEN].rstrip() + "..."
    return description


def _meal_when_token(record: "FoodRecord", now: datetime) -> str:
    """Render the relative/absolute time token for a logged meal.

    Shared by the rendered meal context and the citation allow-set so the output
    verifier's timestamp guard compares the exact
    token the model saw. ``meal_timestamp`` is tz-aware in normal operation
    (``DateTime(timezone=True)``); a naive value is normalized defensively so the
    subtraction can't raise and silently drop the meal.
    """
    meal_ts = record.meal_timestamp
    if meal_ts.tzinfo is None:
        meal_ts = meal_ts.replace(tzinfo=UTC)
    hours_ago = (now - meal_ts).total_seconds() / 3600
    if 0 <= hours_ago < MEAL_RELATIVE_TIME_MAX_HOURS:
        return f"{hours_ago:.0f}h ago"
    return meal_ts.strftime("%a %H:%M")


def _format_meal_line(record: "FoodRecord", now: datetime) -> str:
    """Render one logged meal as a descriptive, non-prescriptive context line.

    Every line carries the "never use it to dose or bolus" qualifier so the carb
    figure is read as an AI guess, never as something to dose from.
    """
    low, high, corrected = _meal_carb_range(record)
    description = _safe_meal_description(record.food_description)
    when = _meal_when_token(record, now)
    qualifier = (
        f"user-corrected estimate — {NEVER_DOSE_PROHIBITION}"
        if corrected
        else MEAL_ESTIMATE_QUALIFIER
    )
    return f"- {description}: ~{low:g}-{high:g}g carbs ({qualifier}) [{when}]"


def _format_meals_block(header: str, records: list["FoodRecord"], now: datetime) -> str:
    """Assemble a meal context block: header, charter framing, then meal lines."""
    lines = [header, _MEAL_GUIDANCE]
    lines.extend(_format_meal_line(r, now) for r in records)
    return "\n".join(lines)


async def _fetch_meal_records(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    start: datetime,
    end: datetime | None,
) -> list["FoodRecord"]:
    """Fetch a user's logged meals in ``[start, end)`` (open end if ``end`` is None).

    Single source of the meal query so the rendered context and the citation
    allow-set always read the same rows -- the verifier can
    only trust a number if the context that produced it used identical records.
    Ordered newest-first and capped at ``MEAL_MAX_RECORDS``.
    """
    from src.models.food_record import FoodRecord

    conditions = [
        FoodRecord.user_id == user_id,
        FoodRecord.meal_timestamp >= start,
    ]
    if end is not None:
        conditions.append(FoodRecord.meal_timestamp < end)
    result = await db.execute(
        select(FoodRecord)
        .where(*conditions)
        .order_by(FoodRecord.meal_timestamp.desc())
        .limit(MEAL_MAX_RECORDS)
    )
    return list(result.scalars().all())


async def build_meals_section(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> str | None:
    """Build the recent-logged-meals section for chat context.

    Pulls the user's most recent food records within a bounded window so chat can
    reference what they ate. Descriptive only: the carb range is presented as an
    estimate to verify, never as a dosing input (meal-intelligence safety posture). The
    caller only invokes this when ``meal_intelligence_enabled`` is on.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=MEAL_CONTEXT_HOURS)
    records = await _fetch_meal_records(db, user_id, start=cutoff, end=None)
    if not records:
        return None

    return _format_meals_block(
        f"[Logged meals - last {MEAL_CONTEXT_HOURS}h]",
        records,
        now,
    )


async def format_meals_for_brief(
    db: AsyncSession,
    user_id: uuid.UUID,
    period_start: datetime,
    period_end: datetime,
) -> str | None:
    """Build the logged-meals block for a daily brief's analysis period.

    Mirrors ``build_meals_section`` but scopes to the brief's window so the brief
    references the meals logged in the period it summarizes. Same descriptive,
    never-dose-or-bolus framing; never a dosing input. The caller only invokes
    this when ``meal_intelligence_enabled`` is on.
    """
    records = await _fetch_meal_records(db, user_id, start=period_start, end=period_end)
    if not records:
        return None

    # Anchor relative timestamps to the period's end (the brief's "as of"), not
    # the moment of generation -- a brief produced hours after the window closes
    # would otherwise render in-period meals as misleadingly old.
    return _format_meals_block("[Logged meals this period]", records, period_end)


async def build_allowed_carbs(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    window_start: datetime,
    window_end: datetime | None,
    now: datetime,
) -> list[AllowedCarb]:
    """Build the set of carb figures the model was allowed to cite.

    Reads the same rows the context rendered (``_fetch_meal_records``) and the
    same per-record carb range (``_meal_carb_range`` -- corrected values
    preferred), so the output verifier's truth and the context the model saw
    can't diverge (AC3). The allowed numbers come only from the carb columns,
    never from ``food_description``, so a prompt-injected figure in a description
    can never mint an allowed value.
    """
    records = await _fetch_meal_records(db, user_id, start=window_start, end=window_end)
    allowed: list[AllowedCarb] = []
    for record in records:
        low, high, _ = _meal_carb_range(record)
        allowed.append(
            AllowedCarb(low=low, high=high, when=_meal_when_token(record, now))
        )
    return allowed


async def verify_meal_citations(
    db: AsyncSession,
    user_id: uuid.UUID,
    content: str,
    *,
    surface: str,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    now: datetime | None = None,
) -> str:
    """Verify carb figures in a model response against the user's logged meals.

    The single output-side choke-point for chat and the daily
    brief. Inert when ``meal_intelligence_enabled`` is off. ``window_start``
    defaults to the chat meal window (``now - MEAL_CONTEXT_HOURS``); the brief
    passes its period bounds and anchors ``now`` to ``period_end`` so the time
    tokens match what it rendered.

    Fail-closed on the allow-set: if the records can't be read, the allow-set is
    empty and every carb figure is scrubbed -- we never emit a number we couldn't
    verify. A verifier exception (should be impossible on ``str`` input) returns
    the content unchanged rather than break the reply; the model's *input* was
    already scrubbed by the context layer. Logs PHI-free counts only (AC6).
    """
    if not content or not await is_meal_intelligence_enabled(db, user_id):
        return content

    now = now or datetime.now(UTC)
    if window_start is None:
        window_start = now - timedelta(hours=MEAL_CONTEXT_HOURS)

    try:
        allowed = await build_allowed_carbs(
            db,
            user_id,
            window_start=window_start,
            window_end=window_end,
            now=now,
        )
    except Exception:
        logger.warning(
            "Meal citation allow-set build failed; scrubbing unverifiable figures",
            surface=surface,
            user_id=str(user_id),
            exc_info=True,
        )
        allowed = []  # fail closed -> every carb figure is scrubbed

    try:
        outcome = verify_carb_citations(content, allowed)
    except Exception:
        logger.warning(
            "Meal citation verification raised; returning content unchanged",
            surface=surface,
            user_id=str(user_id),
            exc_info=True,
        )
        return content

    if outcome.changed:
        logger.info(
            "Meal citation rewrite",
            surface=surface,
            seen=outcome.citations_seen,
            matched=outcome.citations_matched,
            corrected=outcome.citations_corrected,
            scrubbed=outcome.citations_scrubbed,
            timestamp_mismatches=outcome.timestamp_mismatches,
        )
    return outcome.text


@dataclass(frozen=True)
class GlucoseAllowSet:
    """The glucose figures a model response may cite for a window.

    ``match`` is every value a cited figure may verify against: the user's
    distinct readings plus the rendered aggregates (window average, target
    bounds) and any surface-specific ``extra`` figures the prompt also showed.
    ``readings`` is the distinct real readings alone -- the referent basis for
    single-reading correction, kept separate so the padded aggregates can't mask
    a flat-line user as multi-referent.
    """

    match: list[int]
    readings: list[int]


async def build_allowed_glucose(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    window_start: datetime,
    window_end: datetime | None = None,
    limit: int | None = None,
    extra: Sequence[float] = (),
) -> GlucoseAllowSet:
    """Build the set of glucose figures the model was allowed to cite for a window.

    The allow-set is the user's real ``GlucoseReading`` values (canonical mg/dL,
    primary-CGM-only and ``20-500``-filtered, exactly as ``build_glucose_section``
    selects them) plus the rendered aggregates the model also saw: the window
    average and the configured target-range bounds. A figure the model utters that
    matches one of these within the display band traces to real data; anything
    else is an invention.

    ``limit`` selects the newest N readings (matching ``build_glucose_section``'s
    cap for chat) so the allow-set average equals the one the model was shown;
    surfaces whose prompt computes the average differently (the daily brief) or
    renders derived figures/constants (the correction and meal analyses) pass
    those exact values via ``extra`` instead. Returns distinct values so a busy
    window can't bloat the comparison set.
    """
    from src.models.glucose import GlucoseReading
    from src.models.target_glucose_range import TargetGlucoseRange
    from src.services.cgm_source import (
        get_excluded_cgm_sources,
        glucose_source_exclusion_clause,
    )

    excluded = await get_excluded_cgm_sources(db, user_id)
    conditions = [
        GlucoseReading.user_id == user_id,
        GlucoseReading.reading_timestamp >= window_start,
        *glucose_source_exclusion_clause(excluded),
    ]
    if window_end is not None:
        conditions.append(GlucoseReading.reading_timestamp < window_end)

    stmt = select(GlucoseReading.value).where(*conditions)
    if limit is not None:
        stmt = stmt.order_by(GlucoseReading.reading_timestamp.desc()).limit(limit)
    result = await db.execute(stmt)
    values = [value for (value,) in result if 20 <= value <= 500]

    readings = sorted(set(values))
    match: set[int] = set(readings)
    if values:
        # Mirrors ``build_glucose_section``'s ``sum(values) / len(values)`` so the
        # rendered average lands in the allow-set; the +/-1 band absorbs the
        # display rounding.
        match.add(round(sum(values) / len(values)))

    target = (
        await db.execute(
            select(TargetGlucoseRange).where(TargetGlucoseRange.user_id == user_id)
        )
    ).scalar_one_or_none()
    match.add(int(target.low_target if target else DEFAULT_LOW_TARGET))
    match.add(int(target.high_target if target else DEFAULT_HIGH_TARGET))

    # The model is also shown the user's configured thresholds -- pump-profile
    # segment targets and the CGM high/low alert levels (rendered into every chat
    # prompt by build_diabetes_context and into the analysis prompts) -- so a
    # reply faithfully restating one is not an invention and must not be scrubbed.
    # Fetched fail-soft: a profile read error must not empty the allow-set (which
    # would fail-closed scrub every figure in chat). Non-configured clinical
    # anchors (54, 250...) are deliberately NOT seeded -- the directive/threshold
    # exemption already passes those through, and seeding them as always-citable
    # would mask a genuine misquote that happens to equal an anchor.
    try:
        profile = await get_pump_profile_summary(db, user_id)
    except Exception:
        logger.warning(
            "Pump-profile fetch for glucose allow-set failed",
            user_id=str(user_id),
            exc_info=True,
        )
        profile = None
    if profile is not None:
        thresholds = [segment.target_bg for segment in profile.segments]
        thresholds += [profile.cgm_high_alert_mgdl, profile.cgm_low_alert_mgdl]
        for value in thresholds:
            if value is not None and 20 <= value <= 500:
                match.add(int(round(value)))

    # Surface-specific rendered figures (a brief's exact average, an analysis'
    # post-correction target / average glucose drop). Zero/empty placeholders are
    # skipped -- they are "no data", not a citable figure.
    for value in extra:
        if value and value > 0:
            match.add(int(round(value)))

    return GlucoseAllowSet(match=sorted(match), readings=readings)


async def verify_glucose_reading_citations(
    db: AsyncSession,
    user_id: uuid.UUID,
    content: str,
    *,
    surface: str,
    unit: GlucoseUnit | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    extra: Sequence[float] = (),
) -> str:
    """Verify glucose figures in a model response against the user's readings.

    The output-side choke-point for chat and the daily brief: it corrects or
    scrubs any spoken glucose number that doesn't trace to the user's data,
    mirroring the carb verifier at the same call sites so a single reply never
    handles its glucose and carb figures with two different models. ``window_start``
    defaults to the chat glucose window (``now - GLUCOSE_CONTEXT_HOURS``), and in
    that default case the allow-set is capped to ``GLUCOSE_MAX_READINGS`` to match
    what ``build_glucose_section`` rendered; callers with their own period pass it
    (and their exact aggregates via ``extra``). ``unit`` is resolved from the data
    owner when not supplied.

    Fail-closed on the allow-set (a read failure scrubs every figure -- we never
    emit a glucose number we couldn't verify), matching ``verify_meal_citations``.
    A verifier exception (should be impossible on ``str`` input) returns the
    content unchanged. Logs PHI-free counts only.
    """
    if not content:
        return content

    now = datetime.now(UTC)
    limit: int | None = None
    if window_start is None:
        window_start = now - timedelta(hours=GLUCOSE_CONTEXT_HOURS)
        limit = GLUCOSE_MAX_READINGS  # match build_glucose_section's chat cap
    if unit is None:
        from src.services.glucose_unit import resolve_glucose_unit

        unit = await resolve_glucose_unit(db, user_id)

    try:
        allow = await build_allowed_glucose(
            db,
            user_id,
            window_start=window_start,
            window_end=window_end,
            limit=limit,
            extra=extra,
        )
        records, referents = allow.match, allow.readings
    except Exception:
        logger.warning(
            "Glucose citation allow-set build failed; scrubbing unverifiable figures",
            surface=surface,
            user_id=str(user_id),
            exc_info=True,
        )
        records, referents = [], []  # fail closed -> every glucose figure is scrubbed

    try:
        outcome = verify_glucose_citations(content, records, unit, referents=referents)
    except Exception:
        logger.warning(
            "Glucose citation verification raised; returning content unchanged",
            surface=surface,
            user_id=str(user_id),
            exc_info=True,
        )
        return content

    if outcome.changed:
        logger.info(
            "Glucose citation rewrite",
            surface=surface,
            seen=outcome.citations_seen,
            matched=outcome.citations_matched,
            corrected=outcome.citations_corrected,
            scrubbed=outcome.citations_scrubbed,
        )
    return outcome.text


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
    unit: GlucoseUnit = GlucoseUnit.MGDL,
) -> str | None:
    """Build user settings section (target range, insulin config).

    The glucose target range renders in ``unit``; insulin config (DIA, onset)
    is unit-agnostic and unchanged.
    """
    from src.models.insulin_config import InsulinConfig
    from src.models.target_glucose_range import TargetGlucoseRange

    parts = []

    range_result = await db.execute(
        select(TargetGlucoseRange).where(TargetGlucoseRange.user_id == user_id)
    )
    target_range = range_result.scalar_one_or_none()
    if target_range:
        parts.append(
            "- Target range: "
            + format_glucose_range(
                target_range.low_target, target_range.high_target, unit
            )
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
    unit: GlucoseUnit = GlucoseUnit.MGDL,
) -> str | None:
    """Build pump profile section from the active Tandem pump profile.

    Delegates to get_pump_profile_summary + format_pump_profile_for_prompt
    to avoid duplicating formatting logic.
    """
    summary = await get_pump_profile_summary(db, user_id)
    if not summary:
        return None
    return format_pump_profile_for_prompt(summary, unit)


# ── Composite context builder ──


async def build_knowledge_section(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
) -> str | None:
    """Build clinical knowledge section from RAG retrieval.

    Retrieves relevant knowledge chunks based on the user's query
    and formats them with trust-tier labels for the AI prompt.

    Args:
        db: Database session.
        user_id: User's UUID.
        query: The user's question text.

    Returns:
        Formatted knowledge text, or None if no relevant chunks found.
    """
    from src.services.knowledge_retrieval import (
        format_knowledge_for_prompt,
        retrieve_knowledge,
    )

    chunks = await retrieve_knowledge(db, user_id, query)
    return format_knowledge_for_prompt(chunks)


async def build_diabetes_context(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str | None = None,
    unit: GlucoseUnit = GlucoseUnit.MGDL,
) -> str:
    """Build comprehensive diabetes context from all available data.

    Assembles independent sections: glucose, IoB, pump activity,
    Control-IQ summary, user settings, pump profile, and optionally
    clinical knowledge (when a query is provided). Each section is
    independently resilient -- if one fails, the others still populate.

    Args:
        db: Database session.
        user_id: User's UUID.
        query: Optional user question for knowledge retrieval.
        unit: The data owner's glucose display unit. Glucose-rendering sections
            convert to it; all stored values and metric math stay mg/dL.

    Returns:
        A formatted string describing all available diabetes data,
        or a fallback message if no data is available.
    """
    # Each builder is bound to its arguments here so the dispatch loop stays
    # uniform while only the glucose-rendering sections receive the user's unit
    # (IoB, pump activity, Control-IQ and meals carry no glucose values).
    builders: list[tuple[str, object]] = [
        ("glucose", partial(build_glucose_section, db, user_id, unit)),
        ("iob", partial(build_iob_section, db, user_id)),
        ("pump", partial(build_pump_section, db, user_id)),
        ("control_iq", partial(build_control_iq_section, db, user_id)),
        ("settings", partial(build_settings_section, db, user_id, unit)),
        ("pump_profile", partial(build_pump_profile_section, db, user_id, unit)),
    ]

    # Logged meals are only surfaced when the meal-intelligence feature is on
    # Gated here -- not inside the builder -- so the feature stays
    # fully invisible (no query, no section) while the flag is off.
    if await is_meal_intelligence_enabled(db, user_id):
        builders.append(("meals", partial(build_meals_section, db, user_id)))

    sections: list[str] = []
    for name, builder in builders:
        try:
            section = await builder()
            if section:
                sections.append(section)
        except Exception:
            logger.warning(
                "Failed to build context section",
                section=name,
                user_id=str(user_id),
                exc_info=True,
            )

    # Knowledge retrieval section (only when a user query is provided)
    if query:
        try:
            knowledge = await build_knowledge_section(db, user_id, query)
            if knowledge:
                sections.append(knowledge)
        except Exception:
            logger.warning(
                "Failed to build knowledge section",
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
        select(PumpProfile)
        .where(
            PumpProfile.user_id == user_id,
            PumpProfile.is_active.is_(True),
        )
        .order_by(PumpProfile.synced_at.desc())
        .limit(1)
    )
    profile = result.scalar_one_or_none()
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


def format_pump_profile_for_prompt(
    summary: PumpProfileSummary,
    unit: GlucoseUnit = GlucoseUnit.MGDL,
) -> str:
    """Format a pump profile summary as a text block for AI prompts.

    Includes all segments with basal rates, correction factors, carb ratios,
    and target BG values. Also includes insulin duration, max bolus, and
    CGM alert thresholds.

    Glucose-valued fields render in ``unit``: the segment target BG, the CGM
    high/low alert thresholds, and the correction factor (``CF 1:X`` -- a glucose
    drop per insulin unit, the same quantity as the observed ISF, so it stays on
    the same scale the analysis prompt compares it against). The carb ratio
    (``CR 1:X``) is grams per unit, not a glucose quantity, and never converts.
    """
    safe_name = _sanitize_for_prompt(summary.profile_name)
    lines = [f'[Pump Profile - "{safe_name}" (active)]']
    for seg in summary.segments:
        safe_time = _sanitize_for_prompt(seg.time)
        cf = format_correction_factor_value(seg.correction_factor, unit)
        lines.append(
            f"- {safe_time}: Basal {seg.basal_rate:.3f} u/hr, "
            f"CF 1:{cf}, CR 1:{seg.carb_ratio:g}, "
            f"Target {format_glucose(seg.target_bg, unit)}"
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
        alert_parts.append(f"High {format_glucose(summary.cgm_high_alert_mgdl, unit)}")
    if summary.cgm_low_alert_mgdl is not None:
        alert_parts.append(f"Low {format_glucose(summary.cgm_low_alert_mgdl, unit)}")
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
