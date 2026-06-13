"""Story 3.7: Insulin on Board (IoB) Projection Engine.

Provides projected IoB calculations based on pump-confirmed snapshots
combined with dose-summation for insulin the snapshot cannot account
for: doses delivered after it, and non-pump doses (smart-pen / manual
logs) the pump never knew about regardless of timing.
Uses decay curves for rapid-acting insulins (Novolog/Humalog).
"""

import enum
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.pump_data import PumpEvent, PumpEventType


async def get_user_dia(db: AsyncSession, user_id: uuid.UUID) -> float:
    """Get the user's configured DIA, or the default 4.0 hours.

    Args:
        db: Database session
        user_id: User ID to look up

    Returns:
        DIA in hours
    """
    from src.models.insulin_config import InsulinConfig

    result = await db.execute(
        select(InsulinConfig).where(InsulinConfig.user_id == user_id)
    )
    config = result.scalar_one_or_none()
    if config is not None:
        return config.dia_hours
    return INSULIN_DIA_HOURS


@dataclass
class IoBProjection:
    """Projected IoB values at different time points."""

    # Last confirmed IoB from pump
    confirmed_iob: float
    confirmed_at: datetime

    # Current projected IoB (accounting for decay since confirmation)
    projected_iob: float
    projected_at: datetime

    # Future projections
    projected_30min: float
    projected_60min: float

    # Data staleness
    minutes_since_confirmed: int
    is_stale: bool  # True if > 2 hours old
    stale_warning: str | None = None
    is_estimated: bool = False  # True when no pump confirmation exists


# Insulin activity profile constants for rapid-acting insulin (Novolog/Humalog)
# Based on exponential decay model with 4-hour duration of insulin action (DIA)
INSULIN_DIA_HOURS = 4.0  # Duration of Insulin Action
INSULIN_PEAK_HOURS = 1.0  # Time to peak activity

# The ONLY event types this engine sums as insulin doses. Pinned by test
# (`TestDoseEventTypePin`): basal-family types must never enter dose
# summation -- BASAL is already captured in the pump's IoB snapshot, and a
# future long-acting type (e.g. BASAL_INJECTION, issue #728) follows a
# multi-hour absorption profile this rapid-acting decay curve would badly
# misrepresent. Add new types here only together with a matching curve.
_DOSE_EVENT_TYPES: tuple[PumpEventType, ...] = (
    PumpEventType.BOLUS,
    PumpEventType.CORRECTION,
)

# Nightscout-sourced rows carry `source = "nightscout:<connection_id>"`.
_NIGHTSCOUT_SOURCE_PREFIX = "nightscout:"

# Closed-loop uploaders whose Nightscout BOLUS/CORRECTION treatments record
# insulin the loop's pump actually delivered. Anything else writing a bolus
# treatment (Care Portal UI, xDrip+/Spike/Tidepool manual logs, unknown) is
# a human logging insulin by hand.
_NS_LOOP_UPLOADERS = frozenset({"loop", "aaps", "trio", "oref0"})


class _AnchorVisibility(enum.Enum):
    """Whether a pump-confirmed IoB anchor can already include a dose row.

    The hybrid model cuts dose summation at the anchor timestamp on the
    assumption that the anchor already accounts for older doses. That
    assumption only holds for insulin the anchor's writer knew about:

    - PUMP: pump-delivered insulin (direct integrations, Glooko/Medtronic
      pump streams, loop-uploaded Nightscout boluses). Reflected in every
      IoB anchor for that pump -- the anchor-timestamp cut applies.
    - NEVER: Glooko ``insulins``-stream rows (smart-pen doses + manual
      Glooko logs). No anchor writer can see these: pump hardware only
      knows its own deliveries, and Nightscout loops have no Glooko link.
      They must survive the cut regardless of anchor age.
    - NIGHTSCOUT_ONLY: manually-recorded Nightscout treatments (External
      Insulin, Care Portal / non-loop-uploader boluses). Invisible to pump
      hardware anchors, but possibly visible to a Nightscout-derived anchor:
      Loop counts logged external insulin in its own IoB, and AAPS with NS
      sync imports Care Portal treatments. They survive the cut only when
      the anchor is NOT Nightscout-derived; against a Nightscout anchor we
      conservatively keep the cut, because double-counting (overstated IoB,
      withheld corrections) is the failure mode that would make this
      classification dangerous if wrong.
    """

    PUMP = "pump"
    NEVER = "never"
    NIGHTSCOUT_ONLY = "nightscout_only"


@dataclass(frozen=True)
class _Dose:
    """A single insulin dose row with its anchor-visibility classification."""

    timestamp: datetime
    units: float
    anchor_visibility: _AnchorVisibility


def _classify_anchor_visibility(
    source: str, metadata_json: dict | None
) -> _AnchorVisibility:
    """Classify a dose row by which IoB anchors could already include it.

    Conservative by construction: anything not positively identified as a
    non-pump dose is treated as pump-delivered (subject to the anchor cut),
    so an unexpected source/metadata shape degrades to the pre-fix behavior
    (possible understatement) rather than risking double-counting.
    """
    metadata = metadata_json or {}
    if metadata.get("glooko_stream") == "insulins":
        return _AnchorVisibility.NEVER
    if source.startswith(_NIGHTSCOUT_SOURCE_PREFIX):
        if metadata.get("bolus_subtype") == "external":
            return _AnchorVisibility.NIGHTSCOUT_ONLY
        if metadata.get("source_uploader") not in _NS_LOOP_UPLOADERS:
            return _AnchorVisibility.NIGHTSCOUT_ONLY
    return _AnchorVisibility.PUMP


def _survives_anchor_cut(
    dose: _Dose, anchor_at: datetime, anchor_is_nightscout: bool
) -> bool:
    """Decide whether a dose still contributes IoB given a pump anchor.

    Doses after the anchor always count (the anchor predates them). At or
    before the anchor, only doses the anchor's writer could not have known
    about count -- see `_AnchorVisibility`. Exactly-at-anchor pump doses are
    excluded (the snapshot is assumed to include them; pinned by
    `test_iob_same_timestamp_not_double_counted`).
    """
    if dose.timestamp > anchor_at:
        return True
    if dose.anchor_visibility is _AnchorVisibility.NEVER:
        return True
    return (
        dose.anchor_visibility is _AnchorVisibility.NIGHTSCOUT_ONLY
        and not anchor_is_nightscout
    )


def calculate_insulin_remaining(
    elapsed_hours: float, dia_hours: float = INSULIN_DIA_HOURS
) -> float:
    """Calculate fraction of insulin remaining after elapsed time.

    Uses a simplified exponential decay model. For rapid-acting insulin:
    - Peak activity at ~1 hour
    - Most insulin action complete by 4 hours
    - Decay follows approximate curve: remaining = 1 - (t/DIA)^2 for t < DIA

    This is a simplified model. Real insulin curves are more complex but this
    provides a reasonable approximation for projection purposes.

    Args:
        elapsed_hours: Hours since insulin was delivered
        dia_hours: Duration of insulin action (default 4 hours)

    Returns:
        Fraction of insulin activity remaining (0.0 to 1.0)
    """
    if elapsed_hours <= 0:
        return 1.0
    if elapsed_hours >= dia_hours:
        return 0.0

    # Parabolic decay model: steeper at the end
    # This approximates the bilinear model commonly used in loop systems
    t_ratio = elapsed_hours / dia_hours
    remaining = 1.0 - (t_ratio * t_ratio)

    return max(0.0, min(1.0, remaining))


def calculate_iob_activity_curve(
    elapsed_hours: float, dia_hours: float = INSULIN_DIA_HOURS
) -> float:
    """Calculate the Walsh-curve inspired insulin activity at a given time.

    This uses a more accurate bilinear decay model that accounts for:
    - Slow initial absorption
    - Peak activity around 60-75 minutes
    - Gradual tail-off

    Args:
        elapsed_hours: Hours since insulin was delivered
        dia_hours: Duration of insulin action (default 4 hours)

    Returns:
        Fraction of insulin activity remaining (0.0 to 1.0)
    """
    if elapsed_hours <= 0:
        return 1.0
    if elapsed_hours >= dia_hours:
        return 0.0

    # Bilinear model parameters
    peak_time = INSULIN_PEAK_HOURS

    if elapsed_hours < peak_time:
        # Rising phase - rapid absorption
        # Activity decreases more slowly at first
        fraction = elapsed_hours / peak_time
        iob_fraction = 1.0 - (0.2 * fraction)  # Only lose 20% in first hour
    else:
        # Falling phase - exponential-like decay
        remaining_time = dia_hours - elapsed_hours
        decay_duration = dia_hours - peak_time
        # Lose remaining 80% over the next 3 hours
        iob_fraction = 0.8 * (remaining_time / decay_duration)

    return max(0.0, min(1.0, iob_fraction))


def project_iob(
    confirmed_iob: float,
    confirmed_at: datetime,
    projection_time: datetime,
    dia_hours: float = INSULIN_DIA_HOURS,
) -> float:
    """Project IoB at a future time based on decay curve.

    Args:
        confirmed_iob: Last confirmed IoB value in units
        confirmed_at: Timestamp of the confirmed IoB
        projection_time: Time to project IoB to
        dia_hours: Duration of insulin action

    Returns:
        Projected IoB in units
    """
    # Calculate elapsed time since confirmation
    elapsed = projection_time - confirmed_at
    elapsed_hours = elapsed.total_seconds() / 3600

    if elapsed_hours <= 0:
        return confirmed_iob

    # Calculate what fraction of the confirmed IoB would remain
    # We use the simplified decay model here
    remaining_fraction = calculate_insulin_remaining(elapsed_hours, dia_hours)

    return confirmed_iob * remaining_fraction


async def get_last_iob(
    db: AsyncSession,
    user_id: uuid.UUID,
    max_hours: float | None = None,
) -> tuple[float | None, datetime | None, str | None]:
    """Get the most recent IoB value for a user.

    Args:
        db: Database session
        user_id: User ID to query
        max_hours: Maximum age of IoB reading to consider.
                   Defaults to the user's configured DIA (up to 8h).

    Returns:
        Tuple of (iob_value, timestamp, source) or (None, None, None)
        if no data. `source` is the anchor row's integration source --
        needed to decide which non-pump doses the anchor could already
        include (see `_AnchorVisibility`).
    """
    if max_hours is None:
        max_hours = await get_user_dia(db, user_id)
    cutoff = datetime.now(UTC) - timedelta(hours=max_hours)

    result = await db.execute(
        select(PumpEvent.iob_at_event, PumpEvent.event_timestamp, PumpEvent.source)
        .where(
            PumpEvent.user_id == user_id,
            PumpEvent.iob_at_event.isnot(None),
            PumpEvent.event_timestamp >= cutoff,
        )
        .order_by(desc(PumpEvent.event_timestamp))
        .limit(1)
    )

    row = result.first()
    if row:
        return row[0], row[1], row[2]
    return None, None, None


async def _fetch_insulin_doses(
    db: AsyncSession,
    user_id: uuid.UUID,
    dia_hours: float,
    reference_time: datetime,
) -> list[_Dose]:
    """Fetch all insulin-delivering events within the DIA window.

    Returns bolus and correction events, each classified by which IoB
    anchors could already include it (`_AnchorVisibility`). Basal events
    are excluded because their insulin contribution is already captured
    in the pump's IoB snapshot.
    """
    cutoff = reference_time - timedelta(hours=dia_hours)
    result = await db.execute(
        select(
            PumpEvent.event_timestamp,
            PumpEvent.units,
            PumpEvent.source,
            PumpEvent.metadata_json,
        )
        .where(
            PumpEvent.user_id == user_id,
            PumpEvent.event_type.in_(_DOSE_EVENT_TYPES),
            PumpEvent.units.isnot(None),
            PumpEvent.units > 0,
            PumpEvent.event_timestamp >= cutoff,
            PumpEvent.event_timestamp <= reference_time,
        )
        .order_by(PumpEvent.event_timestamp)
    )
    return [
        _Dose(
            timestamp=row[0],
            units=row[1],
            anchor_visibility=_classify_anchor_visibility(row[2], row[3]),
        )
        for row in result.all()
    ]


def _sum_iob_from_doses(
    doses: list[tuple[datetime, float]],
    at_time: datetime,
    dia_hours: float = INSULIN_DIA_HOURS,
) -> float:
    """Compute total IoB at a given time from a list of insulin doses.

    For each dose, applies the decay curve based on elapsed time and sums
    the remaining insulin across all doses.

    Args:
        doses: List of (event_timestamp, units) tuples.
        at_time: Time to compute IoB at.
        dia_hours: Duration of insulin action.

    Returns:
        Total remaining insulin in units.
    """
    total = 0.0
    for event_time, units in doses:
        elapsed = (at_time - event_time).total_seconds() / 3600
        if elapsed < 0:
            continue  # dose is in the future relative to at_time
        remaining = calculate_insulin_remaining(elapsed, dia_hours)
        total += units * remaining
    return total


async def get_iob_projection(
    db: AsyncSession,
    user_id: uuid.UUID,
    dia_hours: float = INSULIN_DIA_HOURS,
) -> IoBProjection | None:
    """Get projected IoB for a user using hybrid dose-summation.

    Uses pump-confirmed IoB as an anchor (captures all historical insulin
    including basal), then adds insulin from bolus/correction doses the
    anchor cannot already include: doses delivered after the confirmation,
    plus non-pump doses (smart-pen / manual logs) the anchor's writer never
    saw regardless of timing -- see `_AnchorVisibility` for the rule.

    Args:
        db: Database session
        user_id: User ID to query
        dia_hours: Duration of insulin action (default 4 hours)

    Returns:
        IoBProjection with confirmed and projected values, or None if no data
    """
    now = datetime.now(UTC)

    # Step 1: Get last pump-confirmed IoB (any age within DIA window)
    last_confirmed_iob, last_confirmed_at, anchor_source = await get_last_iob(
        db, user_id, max_hours=dia_hours
    )

    # Step 2: Fetch all bolus/correction doses within DIA window
    all_doses = await _fetch_insulin_doses(db, user_id, dia_hours, now)

    # No data at all
    if last_confirmed_iob is None and not all_doses:
        return None

    # Step 3: Keep the doses the anchor cannot already include
    # (post-anchor doses + anchor-blind non-pump doses)
    if last_confirmed_at is not None:
        anchor_is_nightscout = (anchor_source or "").startswith(
            _NIGHTSCOUT_SOURCE_PREFIX
        )
        counted_doses = [
            (d.timestamp, d.units)
            for d in all_doses
            if _survives_anchor_cut(d, last_confirmed_at, anchor_is_nightscout)
        ]
    else:
        counted_doses = [(d.timestamp, d.units) for d in all_doses]

    # Step 4: Compute IoB at now, +30min, +60min
    def _compute_at(at_time: datetime) -> float:
        pump_component = 0.0
        if last_confirmed_iob is not None and last_confirmed_at is not None:
            pump_component = project_iob(
                last_confirmed_iob, last_confirmed_at, at_time, dia_hours
            )
        dose_component = _sum_iob_from_doses(counted_doses, at_time, dia_hours)
        return max(0.0, pump_component + dose_component)

    current_iob = _compute_at(now)
    iob_30 = _compute_at(now + timedelta(minutes=30))
    iob_60 = _compute_at(now + timedelta(minutes=60))

    # Step 5: Determine if this is a fallback (no pump confirmation)
    is_estimated = last_confirmed_at is None
    if is_estimated:
        last_confirmed_iob = round(current_iob, 2)
        last_confirmed_at = now

    # Step 6: Staleness check (based on last pump confirmation)
    elapsed_since = now - last_confirmed_at
    minutes_since = int(elapsed_since.total_seconds() / 60)
    is_stale = minutes_since > 120
    stale_warning = None
    if is_stale:
        stale_warning = "IoB projection may be unreliable - data is over 2 hours old"
    elif is_estimated:
        stale_warning = (
            "IoB estimated from dose history only - no pump confirmation available"
        )

    return IoBProjection(
        confirmed_iob=round(last_confirmed_iob, 2),
        confirmed_at=last_confirmed_at,
        projected_iob=round(current_iob, 2),
        projected_at=now,
        projected_30min=round(iob_30, 2),
        projected_60min=round(iob_60, 2),
        minutes_since_confirmed=minutes_since,
        is_stale=is_stale,
        stale_warning=stale_warning,
        is_estimated=is_estimated,
    )
