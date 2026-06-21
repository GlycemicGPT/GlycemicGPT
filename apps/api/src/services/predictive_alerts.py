"""Story 6.2: Predictive Alert Engine.

Calculates glucose trajectory at 20/30/45 minutes, detects threshold
crossings, and escalates urgency based on IoB. Deduplicates alerts
to avoid spamming the user.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.units import GlucoseUnit, format_glucose, format_glucose_value
from src.logging_config import get_logger
from src.models.alert import Alert, AlertSeverity, AlertType
from src.models.alert_threshold import AlertThreshold
from src.models.glucose import GlucoseReading
from src.services.alert_notifier import notify_user_of_alerts
from src.services.alert_threshold import get_or_create_thresholds
from src.services.glucose_unit import resolve_glucose_unit
from src.services.iob_projection import get_iob_projection, get_user_dia

logger = get_logger(__name__)

# Prediction time horizons in minutes
PREDICTION_HORIZONS = [20, 30, 45]

# Deduplication window: don't create same alert type within this period
DEDUP_WINDOW_MINUTES = 30

# Alert expiration: alerts expire after this period
ALERT_EXPIRY_MINUTES = 60

# IoB escalation threshold: escalate severity when IoB exceeds this
# relative to the user's configured iob_warning threshold
IOB_ESCALATION_FACTOR = 0.8

# Glucose staleness: ignore readings older than this
GLUCOSE_STALE_MINUTES = 10


@dataclass
class GlucoseTrajectory:
    """Predicted glucose values at future time points."""

    current_value: float
    trend_rate: float  # mg/dL/min
    predictions: dict[int, float]  # minutes -> predicted mg/dL


@dataclass
class AlertCandidate:
    """A potential alert before deduplication."""

    alert_type: AlertType
    severity: AlertSeverity
    current_value: float
    predicted_value: float | None
    prediction_minutes: int | None
    iob_value: float | None
    message: str
    trend_rate: float | None
    source: str  # "predictive", "current", "iob"


def calculate_trajectory(
    current_value: float,
    trend_rate: float,
    horizons: list[int] | None = None,
) -> GlucoseTrajectory:
    """Calculate linear glucose trajectory at future time points.

    Uses the current trend rate (mg/dL/min) for linear projection.
    While glucose curves are not perfectly linear, this provides
    a reasonable short-term prediction (< 1 hour).

    Args:
        current_value: Current glucose in mg/dL.
        trend_rate: Rate of change in mg/dL/min.
        horizons: Prediction horizons in minutes (default: 20, 30, 45).

    Returns:
        GlucoseTrajectory with predictions at each horizon.
    """
    if horizons is None:
        horizons = PREDICTION_HORIZONS

    predictions = {}
    for minutes in horizons:
        predicted = current_value + (trend_rate * minutes)
        # Clamp to physiological range (glucose can't go below 0)
        predictions[minutes] = max(0.0, round(predicted, 1))

    return GlucoseTrajectory(
        current_value=current_value,
        trend_rate=trend_rate,
        predictions=predictions,
    )


def determine_severity(
    alert_type: AlertType,
    iob_value: float | None,
    iob_threshold: float,
) -> AlertSeverity:
    """Determine alert severity, escalating based on IoB if applicable.

    When glucose is dropping AND IoB is high, the situation is more
    dangerous because more insulin is still active. Similarly, when
    glucose is rising with low IoB, there's less correction available.

    Args:
        alert_type: The type of alert being generated.
        iob_value: Current IoB in units (None if unavailable).
        iob_threshold: User's configured IoB warning threshold.

    Returns:
        Appropriate AlertSeverity level.
    """
    # Base severity by alert type
    base_severity = {
        AlertType.LOW_URGENT: AlertSeverity.URGENT,
        AlertType.LOW_WARNING: AlertSeverity.WARNING,
        AlertType.HIGH_WARNING: AlertSeverity.WARNING,
        AlertType.HIGH_URGENT: AlertSeverity.URGENT,
        AlertType.IOB_WARNING: AlertSeverity.WARNING,
    }

    severity = base_severity[alert_type]

    # IoB-based escalation for low glucose alerts
    if iob_value is not None and alert_type in (
        AlertType.LOW_WARNING,
        AlertType.LOW_URGENT,
    ):
        # High IoB + dropping glucose = escalate
        if iob_value >= iob_threshold * IOB_ESCALATION_FACTOR:
            if severity == AlertSeverity.WARNING:
                severity = AlertSeverity.URGENT
            elif severity == AlertSeverity.URGENT:
                severity = AlertSeverity.EMERGENCY

    return severity


def check_threshold_crossings(
    trajectory: GlucoseTrajectory,
    thresholds: AlertThreshold,
    iob_value: float | None,
    unit: GlucoseUnit = GlucoseUnit.MGDL,
) -> list[AlertCandidate]:
    """Check if glucose trajectory crosses any configured thresholds.

    Checks both current value and predicted values. For predicted
    values, reports the earliest crossing time.

    Args:
        trajectory: Calculated glucose trajectory.
        thresholds: User's configured alert thresholds.
        iob_value: Current IoB value (for severity escalation).
        unit: The patient's glucose display unit. The persisted
            ``Alert.message`` text renders in it (rendered once at persist; the
            numeric ``current_value``/``predicted_value`` stay canonical mg/dL).
            All threshold comparisons remain in mg/dL.

    Returns:
        List of AlertCandidate objects for threshold crossings found.
    """
    candidates: list[AlertCandidate] = []
    current = trajectory.current_value
    # Pre-render the message figures in the patient's unit once. ``current_labeled``
    # carries the unit label for the headline figure; ``current_value`` and the
    # ``*_disp`` threshold strings are the bare numbers shown inside the
    # parentheticals. Threshold comparisons below still use the raw mg/dL columns.
    current_labeled = format_glucose(current, unit)
    current_value = format_glucose_value(current, unit)
    urgent_low_disp = format_glucose_value(thresholds.urgent_low, unit)
    low_warning_disp = format_glucose_value(thresholds.low_warning, unit)
    urgent_high_disp = format_glucose_value(thresholds.urgent_high, unit)
    high_warning_disp = format_glucose_value(thresholds.high_warning, unit)

    # Check current value against thresholds
    if current <= thresholds.urgent_low:
        candidates.append(
            AlertCandidate(
                alert_type=AlertType.LOW_URGENT,
                severity=determine_severity(
                    AlertType.LOW_URGENT, iob_value, thresholds.iob_warning
                ),
                current_value=current,
                predicted_value=None,
                prediction_minutes=None,
                iob_value=iob_value,
                message=(
                    f"Urgent low glucose: {current_labeled} "
                    f"(threshold: {urgent_low_disp})"
                ),
                trend_rate=trajectory.trend_rate,
                source="current",
            )
        )
    elif current <= thresholds.low_warning:
        candidates.append(
            AlertCandidate(
                alert_type=AlertType.LOW_WARNING,
                severity=determine_severity(
                    AlertType.LOW_WARNING, iob_value, thresholds.iob_warning
                ),
                current_value=current,
                predicted_value=None,
                prediction_minutes=None,
                iob_value=iob_value,
                message=(
                    f"Low glucose warning: {current_labeled} "
                    f"(threshold: {low_warning_disp})"
                ),
                trend_rate=trajectory.trend_rate,
                source="current",
            )
        )

    if current >= thresholds.urgent_high:
        candidates.append(
            AlertCandidate(
                alert_type=AlertType.HIGH_URGENT,
                severity=determine_severity(
                    AlertType.HIGH_URGENT, iob_value, thresholds.iob_warning
                ),
                current_value=current,
                predicted_value=None,
                prediction_minutes=None,
                iob_value=iob_value,
                message=(
                    f"Urgent high glucose: {current_labeled} "
                    f"(threshold: {urgent_high_disp})"
                ),
                trend_rate=trajectory.trend_rate,
                source="current",
            )
        )
    elif current >= thresholds.high_warning:
        candidates.append(
            AlertCandidate(
                alert_type=AlertType.HIGH_WARNING,
                severity=determine_severity(
                    AlertType.HIGH_WARNING, iob_value, thresholds.iob_warning
                ),
                current_value=current,
                predicted_value=None,
                prediction_minutes=None,
                iob_value=iob_value,
                message=(
                    f"High glucose warning: {current_labeled} "
                    f"(threshold: {high_warning_disp})"
                ),
                trend_rate=trajectory.trend_rate,
                source="current",
            )
        )

    # Check predicted values (only if current is not already alerting for same type)
    current_alert_types = {c.alert_type for c in candidates}

    for minutes, predicted in sorted(trajectory.predictions.items()):
        # Low predictions
        if (
            predicted <= thresholds.urgent_low
            and AlertType.LOW_URGENT not in current_alert_types
        ):
            candidates.append(
                AlertCandidate(
                    alert_type=AlertType.LOW_URGENT,
                    severity=determine_severity(
                        AlertType.LOW_URGENT, iob_value, thresholds.iob_warning
                    ),
                    current_value=current,
                    predicted_value=predicted,
                    prediction_minutes=minutes,
                    iob_value=iob_value,
                    message=(
                        f"Predicted urgent low: {format_glucose(predicted, unit)} "
                        f"in {minutes} min "
                        f"(current: {current_value}, threshold: {urgent_low_disp})"
                    ),
                    trend_rate=trajectory.trend_rate,
                    source="predictive",
                )
            )
            current_alert_types.add(AlertType.LOW_URGENT)

        elif (
            predicted <= thresholds.low_warning
            and AlertType.LOW_WARNING not in current_alert_types
            and AlertType.LOW_URGENT not in current_alert_types
        ):
            candidates.append(
                AlertCandidate(
                    alert_type=AlertType.LOW_WARNING,
                    severity=determine_severity(
                        AlertType.LOW_WARNING, iob_value, thresholds.iob_warning
                    ),
                    current_value=current,
                    predicted_value=predicted,
                    prediction_minutes=minutes,
                    iob_value=iob_value,
                    message=(
                        f"Predicted low glucose: {format_glucose(predicted, unit)} "
                        f"in {minutes} min "
                        f"(current: {current_value}, threshold: {low_warning_disp})"
                    ),
                    trend_rate=trajectory.trend_rate,
                    source="predictive",
                )
            )
            current_alert_types.add(AlertType.LOW_WARNING)

        # High predictions
        if (
            predicted >= thresholds.urgent_high
            and AlertType.HIGH_URGENT not in current_alert_types
        ):
            candidates.append(
                AlertCandidate(
                    alert_type=AlertType.HIGH_URGENT,
                    severity=determine_severity(
                        AlertType.HIGH_URGENT, iob_value, thresholds.iob_warning
                    ),
                    current_value=current,
                    predicted_value=predicted,
                    prediction_minutes=minutes,
                    iob_value=iob_value,
                    message=(
                        f"Predicted urgent high: {format_glucose(predicted, unit)} "
                        f"in {minutes} min "
                        f"(current: {current_value}, threshold: {urgent_high_disp})"
                    ),
                    trend_rate=trajectory.trend_rate,
                    source="predictive",
                )
            )
            current_alert_types.add(AlertType.HIGH_URGENT)

        elif (
            predicted >= thresholds.high_warning
            and AlertType.HIGH_WARNING not in current_alert_types
            and AlertType.HIGH_URGENT not in current_alert_types
        ):
            candidates.append(
                AlertCandidate(
                    alert_type=AlertType.HIGH_WARNING,
                    severity=determine_severity(
                        AlertType.HIGH_WARNING, iob_value, thresholds.iob_warning
                    ),
                    current_value=current,
                    predicted_value=predicted,
                    prediction_minutes=minutes,
                    iob_value=iob_value,
                    message=(
                        f"Predicted high glucose: {format_glucose(predicted, unit)} "
                        f"in {minutes} min "
                        f"(current: {current_value}, threshold: {high_warning_disp})"
                    ),
                    trend_rate=trajectory.trend_rate,
                    source="predictive",
                )
            )
            current_alert_types.add(AlertType.HIGH_WARNING)

    return candidates


def check_iob_threshold(
    current_glucose: float,
    iob_value: float,
    iob_threshold: float,
    trend_rate: float | None,
) -> AlertCandidate | None:
    """Check if IoB exceeds the configured threshold.

    Args:
        current_glucose: Current glucose value.
        iob_value: Current IoB value.
        iob_threshold: User's configured IoB warning threshold.
        trend_rate: Current trend rate.

    Returns:
        AlertCandidate if IoB exceeds threshold, None otherwise.
    """
    if iob_value >= iob_threshold:
        return AlertCandidate(
            alert_type=AlertType.IOB_WARNING,
            severity=AlertSeverity.WARNING,
            current_value=current_glucose,
            predicted_value=None,
            prediction_minutes=None,
            iob_value=iob_value,
            message=(
                f"High insulin on board: {iob_value:.1f} units "
                f"(threshold: {iob_threshold:.1f})"
            ),
            trend_rate=trend_rate,
            source="iob",
        )
    return None


async def has_recent_alert(
    db: AsyncSession,
    user_id: uuid.UUID,
    alert_type: AlertType,
    window_minutes: int = DEDUP_WINDOW_MINUTES,
) -> bool:
    """Check if a recent alert of the same type exists.

    Prevents alert spam by checking if the user already has
    an unacknowledged alert of the same type within the dedup window.

    Args:
        db: Database session.
        user_id: User's UUID.
        alert_type: Type of alert to check for.
        window_minutes: Deduplication window in minutes.

    Returns:
        True if a recent alert exists.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)

    result = await db.execute(
        select(Alert.id)
        .where(
            and_(
                Alert.user_id == user_id,
                Alert.alert_type == alert_type,
                Alert.created_at >= cutoff,
                Alert.acknowledged.is_(False),
            )
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def create_alert(
    db: AsyncSession,
    user_id: uuid.UUID,
    candidate: AlertCandidate,
) -> Alert:
    """Persist an alert candidate to the database.

    Args:
        db: Database session.
        user_id: User's UUID.
        candidate: The alert candidate to persist.

    Returns:
        The created Alert record.
    """
    now = datetime.now(UTC)
    alert = Alert(
        user_id=user_id,
        alert_type=candidate.alert_type,
        severity=candidate.severity,
        current_value=candidate.current_value,
        predicted_value=candidate.predicted_value,
        prediction_minutes=candidate.prediction_minutes,
        iob_value=candidate.iob_value,
        message=candidate.message,
        trend_rate=candidate.trend_rate,
        source=candidate.source,
        created_at=now,
        expires_at=now + timedelta(minutes=ALERT_EXPIRY_MINUTES),
    )
    db.add(alert)
    return alert


async def get_active_alerts(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 50,
) -> list[Alert]:
    """Get all active (unacknowledged, non-expired) alerts for a user.

    Args:
        db: Database session.
        user_id: User's UUID.
        limit: Maximum number of alerts to return.

    Returns:
        List of active Alert records, newest first.
    """
    now = datetime.now(UTC)

    result = await db.execute(
        select(Alert)
        .where(
            and_(
                Alert.user_id == user_id,
                Alert.acknowledged.is_(False),
                Alert.expires_at > now,
            )
        )
        .order_by(desc(Alert.created_at))
        .limit(limit)
    )
    return list(result.scalars().all())


async def acknowledge_alert(
    db: AsyncSession,
    user_id: uuid.UUID,
    alert_id: uuid.UUID,
) -> Alert | None:
    """Acknowledge an alert.

    Args:
        db: Database session.
        user_id: User's UUID (for ownership check).
        alert_id: The alert to acknowledge.

    Returns:
        The updated Alert, or None if not found / not owned by user.
    """
    result = await db.execute(
        select(Alert).where(
            and_(
                Alert.id == alert_id,
                Alert.user_id == user_id,
            )
        )
    )
    alert = result.scalar_one_or_none()

    if alert is None:
        return None

    alert.acknowledged = True
    alert.acknowledged_at = datetime.now(UTC)
    return alert


async def evaluate_alerts_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[Alert]:
    """Run the full predictive alert evaluation for a user.

    This is the main entry point for the alert engine. It:
    1. Gets the latest glucose reading
    2. Calculates trajectory at 20/30/45 min
    3. Gets user's alert thresholds
    4. Gets IoB projection
    5. Checks for threshold crossings
    6. Deduplicates against recent alerts
    7. Persists new alerts

    Args:
        db: Database session.
        user_id: User's UUID.

    Returns:
        List of newly created Alert records.
    """
    # Get latest glucose reading
    result = await db.execute(
        select(GlucoseReading)
        .where(GlucoseReading.user_id == user_id)
        .order_by(desc(GlucoseReading.reading_timestamp))
        .limit(1)
    )
    latest_reading = result.scalar_one_or_none()

    if latest_reading is None:
        logger.debug("No glucose readings for user", user_id=str(user_id))
        return []

    # Check staleness
    now = datetime.now(UTC)
    reading_time = latest_reading.reading_timestamp
    if reading_time.tzinfo is None:
        reading_time = reading_time.replace(tzinfo=UTC)

    minutes_ago = (now - reading_time).total_seconds() / 60
    if minutes_ago > GLUCOSE_STALE_MINUTES:
        logger.debug(
            "Glucose reading is stale, skipping alert evaluation",
            user_id=str(user_id),
            minutes_ago=round(minutes_ago, 1),
        )
        return []

    # Get trend rate (default to 0 if unavailable)
    trend_rate = (
        latest_reading.trend_rate if latest_reading.trend_rate is not None else 0.0
    )

    # Calculate trajectory
    trajectory = calculate_trajectory(
        current_value=float(latest_reading.value),
        trend_rate=trend_rate,
    )

    # Get user's thresholds
    thresholds = await get_or_create_thresholds(user_id, db)

    # Resolve the patient's display unit once. Alert.message is rendered in it
    # at persist time (historical alerts are not backfilled on a unit change);
    # the numeric current/predicted columns stay canonical mg/dL.
    unit = await resolve_glucose_unit(db, user_id)

    # Get IoB projection
    iob_value = None
    try:
        dia = await get_user_dia(db, user_id)
        iob_projection = await get_iob_projection(db, user_id, dia_hours=dia)
        if iob_projection and not iob_projection.is_stale:
            iob_value = iob_projection.projected_iob
    except Exception as e:
        logger.warning(
            "Failed to get IoB projection for alert evaluation",
            user_id=str(user_id),
            error=str(e),
        )

    # Check threshold crossings
    candidates = check_threshold_crossings(trajectory, thresholds, iob_value, unit)

    # Check IoB threshold
    if iob_value is not None:
        iob_candidate = check_iob_threshold(
            current_glucose=float(latest_reading.value),
            iob_value=iob_value,
            iob_threshold=thresholds.iob_warning,
            trend_rate=trend_rate,
        )
        if iob_candidate:
            candidates.append(iob_candidate)

    # Deduplicate and persist
    new_alerts: list[Alert] = []
    for candidate in candidates:
        if not await has_recent_alert(db, user_id, candidate.alert_type):
            alert = await create_alert(db, user_id, candidate)
            new_alerts.append(alert)

    if new_alerts:
        await db.commit()
        for alert in new_alerts:
            await db.refresh(alert)

        logger.info(
            "Created predictive alerts",
            user_id=str(user_id),
            alert_count=len(new_alerts),
            types=[a.alert_type.value for a in new_alerts],
        )

        # Story 7.2: Immediate Telegram delivery
        try:
            await notify_user_of_alerts(db, user_id, new_alerts, unit)
        except Exception as e:
            logger.warning(
                "Telegram alert delivery failed",
                user_id=str(user_id),
                error=str(e),
            )

    return new_alerts
