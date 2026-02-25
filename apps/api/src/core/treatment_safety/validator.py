"""Treatment safety validator.

Validates bolus requests against per-user safety limits, CGM freshness,
rate limits, daily totals, glucose range, and user confirmation.

IMPORTANT: This validator is a software safety layer -- it does NOT
replace clinical judgment. See MEDICAL-DISCLAIMER.md and CONTRIBUTING.md
for regulatory context.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.treatment_safety.constants import (
    CGM_FRESHNESS_MAX_MINUTES,
    LOW_GLUCOSE_THRESHOLD_MGDL,
    MIN_BOLUS_INTERVAL_MINUTES,
)
from src.core.treatment_safety.enums import BolusSource, SafetyCheckType
from src.core.treatment_safety.models import (
    BolusRequest,
    BolusValidationResult,
    SafetyCheckResult,
)
from src.models.glucose import GlucoseReading
from src.models.pump_data import PumpEvent, PumpEventType
from src.models.safety_limits import SafetyLimits


class TreatmentSafetyValidator:
    """Validates treatment requests against safety limits.

    All check methods are async and require a database session.
    Every check runs regardless of earlier failures (no short-circuit).
    This class is stateless and safe to use as a singleton.
    """

    async def validate_bolus_request(
        self,
        request: BolusRequest,
        db: AsyncSession,
        *,
        safety_limits: SafetyLimits,
    ) -> BolusValidationResult:
        """Run all safety checks against a bolus request.

        Calls every _check_* method and aggregates results. All checks
        are evaluated (no short-circuit on first failure); a single
        failing check fails the overall result.

        This method never triggers or schedules a dosing action.
        Callers are responsible for any subsequent delivery step and
        must surface a human-readable disclaimer to the end user.

        Args:
            request: The bolus request to validate.
            db: Async database session for querying limits/history.
            safety_limits: Pre-fetched SafetyLimits for the user.

        Returns:
            BolusValidationResult with all check results.
        """

        # Use server time for all safety calculations, not the
        # client-supplied timestamp.  This prevents manipulation of
        # rate-limit and CGM-freshness windows.
        server_now = datetime.now(UTC)

        checks: list[SafetyCheckResult] = [
            await self._check_max_single_bolus(request, safety_limits),
            await self._check_max_daily_total(request, safety_limits, db, server_now),
            await self._check_cgm_freshness(request, db, server_now),
            await self._check_rate_limit(request, db, server_now),
            await self._check_glucose_range(request, safety_limits),
            self._check_user_confirmation(request),
        ]

        rejection_reasons = [c.message for c in checks if not c.passed]
        approved = len(rejection_reasons) == 0
        validated_dose = request.requested_dose_milliunits if approved else 0

        warnings: list[str] = []
        if request.source == BolusSource.ai_suggested:
            warnings.append(
                "This dose was AI-suggested. Verify with your healthcare "
                "provider before acting. Auto-execution is prohibited."
            )

        return BolusValidationResult(
            approved=approved,
            rejection_reasons=rejection_reasons,
            warnings=warnings,
            validated_dose_milliunits=validated_dose,
            safety_check_results=checks,
        )

    async def _check_max_single_bolus(
        self,
        request: BolusRequest,
        safety_limits: SafetyLimits,
    ) -> SafetyCheckResult:
        """Check that the requested dose does not exceed the max single bolus limit."""
        max_dose = safety_limits.max_bolus_dose_milliunits
        passed = request.requested_dose_milliunits <= max_dose
        return SafetyCheckResult(
            check_type=SafetyCheckType.max_single_bolus,
            passed=passed,
            message=(
                f"Dose {request.requested_dose_milliunits} mU within "
                f"single-bolus limit of {max_dose} mU"
                if passed
                else f"Dose {request.requested_dose_milliunits} mU exceeds "
                f"max single bolus of {max_dose} mU"
            ),
            details={
                "requested_milliunits": request.requested_dose_milliunits,
                "max_single_bolus_milliunits": max_dose,
            },
        )

    async def _check_max_daily_total(
        self,
        request: BolusRequest,
        safety_limits: SafetyLimits,
        db: AsyncSession,
        now: datetime,
    ) -> SafetyCheckResult:
        """Check that this dose would not push the 24h total over the limit."""
        max_daily = safety_limits.max_daily_bolus_milliunits

        # Sum bolus+correction events in the last 24 hours.
        # PumpEvent.units is in units (float), request is in milliunits (int).
        cutoff = now - timedelta(hours=24)
        result = await db.execute(
            select(func.coalesce(func.sum(PumpEvent.units), 0.0)).where(
                PumpEvent.user_id == request.user_id,
                PumpEvent.event_type.in_(
                    [
                        PumpEventType.BOLUS,
                        PumpEventType.CORRECTION,
                    ]
                ),
                PumpEvent.event_timestamp >= cutoff,
            )
        )
        daily_units = float(result.scalar_one())
        daily_milliunits = round(daily_units * 1000)

        projected_total = daily_milliunits + request.requested_dose_milliunits
        passed = projected_total <= max_daily

        return SafetyCheckResult(
            check_type=SafetyCheckType.max_daily_total,
            passed=passed,
            message=(
                f"Projected daily total {projected_total} mU within "
                f"limit of {max_daily} mU"
                if passed
                else f"Projected daily total {projected_total} mU exceeds "
                f"daily limit of {max_daily} mU"
            ),
            details={
                "daily_delivered_milliunits": daily_milliunits,
                "requested_milliunits": request.requested_dose_milliunits,
                "projected_total_milliunits": projected_total,
                "max_daily_milliunits": max_daily,
            },
        )

    async def _check_cgm_freshness(
        self,
        request: BolusRequest,
        db: AsyncSession,
        now: datetime,
    ) -> SafetyCheckResult:
        """Check that the latest CGM reading is recent enough."""
        result = await db.execute(
            select(GlucoseReading)
            .where(GlucoseReading.user_id == request.user_id)
            .order_by(GlucoseReading.reading_timestamp.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()

        if latest is None:
            return SafetyCheckResult(
                check_type=SafetyCheckType.cgm_freshness,
                passed=False,
                message="No CGM readings available",
                details={"latest_reading": None},
            )

        reading_time = latest.reading_timestamp
        if reading_time.tzinfo is None:
            reading_time = reading_time.replace(tzinfo=UTC)

        age_minutes = (now - reading_time).total_seconds() / 60
        passed = age_minutes <= CGM_FRESHNESS_MAX_MINUTES

        return SafetyCheckResult(
            check_type=SafetyCheckType.cgm_freshness,
            passed=passed,
            message=(
                f"CGM reading is {age_minutes:.0f} min old "
                f"(limit: {CGM_FRESHNESS_MAX_MINUTES} min)"
                if passed
                else f"CGM reading is {age_minutes:.0f} min old, "
                f"exceeds freshness limit of {CGM_FRESHNESS_MAX_MINUTES} min"
            ),
            details={
                "reading_age_minutes": round(age_minutes, 1),
                "max_age_minutes": CGM_FRESHNESS_MAX_MINUTES,
                "reading_timestamp": reading_time.isoformat(),
                "reading_value_mgdl": latest.value,
            },
        )

    async def _check_rate_limit(
        self,
        request: BolusRequest,
        db: AsyncSession,
        now: datetime,
    ) -> SafetyCheckResult:
        """Check minimum interval between bolus deliveries."""
        cutoff = now - timedelta(minutes=MIN_BOLUS_INTERVAL_MINUTES)
        result = await db.execute(
            select(PumpEvent)
            .where(
                PumpEvent.user_id == request.user_id,
                PumpEvent.event_type.in_(
                    [
                        PumpEventType.BOLUS,
                        PumpEventType.CORRECTION,
                    ]
                ),
                PumpEvent.event_timestamp >= cutoff,
            )
            .order_by(PumpEvent.event_timestamp.desc())
            .limit(1)
        )
        recent_bolus = result.scalar_one_or_none()

        if recent_bolus is None:
            return SafetyCheckResult(
                check_type=SafetyCheckType.rate_limit,
                passed=True,
                message="No recent bolus within rate limit window",
                details={
                    "min_interval_minutes": MIN_BOLUS_INTERVAL_MINUTES,
                    "last_bolus_at": None,
                },
            )

        last_time = recent_bolus.event_timestamp
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=UTC)

        minutes_since = (now - last_time).total_seconds() / 60
        passed = minutes_since >= MIN_BOLUS_INTERVAL_MINUTES

        return SafetyCheckResult(
            check_type=SafetyCheckType.rate_limit,
            passed=passed,
            message=(
                f"Last bolus was {minutes_since:.0f} min ago "
                f"(minimum interval: {MIN_BOLUS_INTERVAL_MINUTES} min)"
                if passed
                else f"Last bolus was only {minutes_since:.0f} min ago, "
                f"minimum interval is {MIN_BOLUS_INTERVAL_MINUTES} min"
            ),
            details={
                "minutes_since_last_bolus": round(minutes_since, 1),
                "min_interval_minutes": MIN_BOLUS_INTERVAL_MINUTES,
                "last_bolus_at": last_time.isoformat(),
            },
        )

    async def _check_glucose_range(
        self,
        request: BolusRequest,
        safety_limits: SafetyLimits,
    ) -> SafetyCheckResult:
        """Check glucose is within safe range for treatment.

        Two layers:
        1. Hard floor at ADA hypoglycemia threshold (70 mg/dL).
        2. User-configured validity range from safety_limits.
        """
        glucose = request.glucose_at_request_mgdl

        if glucose < LOW_GLUCOSE_THRESHOLD_MGDL:
            return SafetyCheckResult(
                check_type=SafetyCheckType.glucose_range_check,
                passed=False,
                message=(
                    f"Glucose {glucose} mg/dL is below hypoglycemia "
                    f"threshold of {LOW_GLUCOSE_THRESHOLD_MGDL} mg/dL"
                ),
                details={
                    "glucose_mgdl": glucose,
                    "low_threshold_mgdl": LOW_GLUCOSE_THRESHOLD_MGDL,
                    "user_min_mgdl": safety_limits.min_glucose_mgdl,
                    "user_max_mgdl": safety_limits.max_glucose_mgdl,
                },
            )

        within_range = (
            safety_limits.min_glucose_mgdl <= glucose <= safety_limits.max_glucose_mgdl
        )

        return SafetyCheckResult(
            check_type=SafetyCheckType.glucose_range_check,
            passed=within_range,
            message=(
                f"Glucose {glucose} mg/dL is within valid range "
                f"({safety_limits.min_glucose_mgdl}-"
                f"{safety_limits.max_glucose_mgdl})"
                if within_range
                else f"Glucose {glucose} mg/dL is outside valid range "
                f"({safety_limits.min_glucose_mgdl}-"
                f"{safety_limits.max_glucose_mgdl})"
            ),
            details={
                "glucose_mgdl": glucose,
                "min_mgdl": safety_limits.min_glucose_mgdl,
                "max_mgdl": safety_limits.max_glucose_mgdl,
                "low_threshold_mgdl": LOW_GLUCOSE_THRESHOLD_MGDL,
            },
        )

    def _check_user_confirmation(
        self,
        request: BolusRequest,
    ) -> SafetyCheckResult:
        """Require user_confirmed=True for non-manual bolus sources.

        Manual boluses pass automatically (the user explicitly chose to
        bolus). AI-suggested and automated boluses MUST carry the
        user_confirmed flag.
        """
        if request.source == BolusSource.manual:
            return SafetyCheckResult(
                check_type=SafetyCheckType.user_confirmation_required,
                passed=True,
                message="Manual bolus -- user confirmation implicit",
                details={"source": request.source.value},
            )

        return SafetyCheckResult(
            check_type=SafetyCheckType.user_confirmation_required,
            passed=request.user_confirmed,
            message=(
                f"User confirmation received for {request.source.value} bolus"
                if request.user_confirmed
                else f"User confirmation required for {request.source.value} bolus"
            ),
            details={
                "source": request.source.value,
                "user_confirmed": request.user_confirmed,
            },
        )
