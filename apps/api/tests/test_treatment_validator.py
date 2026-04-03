"""Tests for the TreatmentSafetyValidator.

Tests each check method against a real database with controlled test data.
Pure checks (max_single_bolus, glucose_range, user_confirmation) use
in-memory SafetyLimits objects. DB-backed checks (daily_total, cgm_freshness,
rate_limit) and the full validate_bolus_request integration test use a
dedicated session managed within each test to avoid teardown conflicts.
"""

import uuid
from datetime import UTC, datetime, timedelta

from src.core.treatment_safety.constants import (
    CGM_FRESHNESS_MAX_MINUTES,
    LOW_GLUCOSE_THRESHOLD_MGDL,
)
from src.core.treatment_safety.enums import BolusSource, SafetyCheckType
from src.core.treatment_safety.models import BolusRequest
from src.core.treatment_safety.validator import TreatmentSafetyValidator
from src.database import get_session_maker
from src.models.glucose import GlucoseReading, TrendDirection
from src.models.pump_data import PumpEvent, PumpEventType
from src.models.safety_limits import SafetyLimits
from src.models.user import User, UserRole

_NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)


def _make_request(**overrides) -> BolusRequest:
    defaults = {
        "user_id": uuid.uuid4(),
        "requested_dose_milliunits": 1000,
        "glucose_at_request_mgdl": 180,
        "timestamp": _NOW,
        "source": BolusSource.manual,
    }
    defaults.update(overrides)
    return BolusRequest(**defaults)


def _make_safety_limits(user_id: uuid.UUID, **overrides) -> SafetyLimits:
    """Build an in-memory SafetyLimits for pure (non-DB) checks."""
    defaults = {
        "user_id": user_id,
        "min_glucose_mgdl": 20,
        "max_glucose_mgdl": 500,
        "max_basal_rate_milliunits": 15000,
        "max_bolus_dose_milliunits": 10000,
        "max_daily_bolus_milliunits": 50000,
    }
    defaults.update(overrides)
    return SafetyLimits(**defaults)


def _make_user() -> User:
    return User(
        id=uuid.uuid4(),
        email=f"validator_test_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="$2b$12$fakehashforvalidatortests000000000000000000000000",
        role=UserRole.DIABETIC,
    )


# ---------------------------------------------------------------------------
# Pure checks -- no database needed
# ---------------------------------------------------------------------------


class TestCheckMaxSingleBolus:
    async def test_pass_within_limit(self):
        uid = uuid.uuid4()
        limits = _make_safety_limits(uid)
        validator = TreatmentSafetyValidator()
        request = _make_request(user_id=uid, requested_dose_milliunits=5000)
        result = await validator._check_max_single_bolus(request, limits)
        assert result.passed is True
        assert result.check_type == SafetyCheckType.max_single_bolus

    async def test_pass_at_limit(self):
        uid = uuid.uuid4()
        limits = _make_safety_limits(uid)
        validator = TreatmentSafetyValidator()
        request = _make_request(user_id=uid, requested_dose_milliunits=10000)
        result = await validator._check_max_single_bolus(request, limits)
        assert result.passed is True

    async def test_fail_over_limit(self):
        uid = uuid.uuid4()
        limits = _make_safety_limits(uid)
        validator = TreatmentSafetyValidator()
        request = _make_request(user_id=uid, requested_dose_milliunits=10001)
        result = await validator._check_max_single_bolus(request, limits)
        assert result.passed is False
        assert "exceeds" in result.message


class TestCheckGlucoseRange:
    async def test_pass_normal(self):
        uid = uuid.uuid4()
        limits = _make_safety_limits(uid)
        validator = TreatmentSafetyValidator()
        request = _make_request(user_id=uid, glucose_at_request_mgdl=120)
        result = await validator._check_glucose_range(request, limits)
        assert result.passed is True

    async def test_fail_hypoglycemia(self):
        uid = uuid.uuid4()
        limits = _make_safety_limits(uid)
        validator = TreatmentSafetyValidator()
        request = _make_request(user_id=uid, glucose_at_request_mgdl=60)
        result = await validator._check_glucose_range(request, limits)
        assert result.passed is False
        assert "hypoglycemia" in result.message

    async def test_pass_at_hypo_threshold(self):
        uid = uuid.uuid4()
        limits = _make_safety_limits(uid)
        validator = TreatmentSafetyValidator()
        request = _make_request(
            user_id=uid, glucose_at_request_mgdl=LOW_GLUCOSE_THRESHOLD_MGDL
        )
        result = await validator._check_glucose_range(request, limits)
        assert result.passed is True


class TestCheckUserConfirmation:
    def test_manual_passes_without_confirmation(self):
        validator = TreatmentSafetyValidator()
        request = _make_request(source=BolusSource.manual, user_confirmed=False)
        result = validator._check_user_confirmation(request)
        assert result.passed is True

    def test_ai_suggested_fails_without_confirmation(self):
        validator = TreatmentSafetyValidator()
        request = _make_request(source=BolusSource.ai_suggested, user_confirmed=False)
        result = validator._check_user_confirmation(request)
        assert result.passed is False

    def test_ai_suggested_passes_with_confirmation(self):
        validator = TreatmentSafetyValidator()
        request = _make_request(source=BolusSource.ai_suggested, user_confirmed=True)
        result = validator._check_user_confirmation(request)
        assert result.passed is True

    def test_automated_fails_without_confirmation(self):
        validator = TreatmentSafetyValidator()
        request = _make_request(source=BolusSource.automated, user_confirmed=False)
        result = validator._check_user_confirmation(request)
        assert result.passed is False

    def test_automated_passes_with_confirmation(self):
        validator = TreatmentSafetyValidator()
        request = _make_request(source=BolusSource.automated, user_confirmed=True)
        result = validator._check_user_confirmation(request)
        assert result.passed is True


# ---------------------------------------------------------------------------
# DB-backed checks -- use dedicated session per test
# ---------------------------------------------------------------------------


class TestCheckMaxDailyTotal:
    async def test_pass_no_prior_boluses(self):
        session_maker = get_session_maker()
        async with session_maker() as db:
            user = _make_user()
            db.add(user)
            await db.commit()
            await db.refresh(user)

            limits = SafetyLimits(
                user_id=user.id,
                min_glucose_mgdl=20,
                max_glucose_mgdl=500,
                max_basal_rate_milliunits=15000,
                max_bolus_dose_milliunits=10000,
                max_daily_bolus_milliunits=50000,
            )
            db.add(limits)
            await db.commit()
            await db.refresh(limits)

            validator = TreatmentSafetyValidator()
            request = _make_request(
                user_id=user.id,
                requested_dose_milliunits=5000,
            )
            result = await validator._check_max_daily_total(request, limits, db, _NOW)
            assert result.passed is True

    async def test_fail_exceeds_daily_limit(self):
        session_maker = get_session_maker()
        async with session_maker() as db:
            user = _make_user()
            db.add(user)
            await db.commit()
            await db.refresh(user)

            limits = SafetyLimits(
                user_id=user.id,
                min_glucose_mgdl=20,
                max_glucose_mgdl=500,
                max_basal_rate_milliunits=15000,
                max_bolus_dose_milliunits=10000,
                max_daily_bolus_milliunits=50000,
            )
            db.add(limits)
            db.add(
                PumpEvent(
                    user_id=user.id,
                    event_type=PumpEventType.BOLUS,
                    event_timestamp=_NOW - timedelta(hours=2),
                    units=48.0,
                    is_automated=False,
                    received_at=_NOW - timedelta(hours=2),
                )
            )
            await db.commit()
            await db.refresh(limits)

            validator = TreatmentSafetyValidator()
            request = _make_request(
                user_id=user.id,
                requested_dose_milliunits=5000,  # 48000 + 5000 = 53000 > 50000
            )
            result = await validator._check_max_daily_total(request, limits, db, _NOW)
            assert result.passed is False
            assert "exceeds" in result.message

    async def test_pass_with_prior_under_limit(self):
        session_maker = get_session_maker()
        async with session_maker() as db:
            user = _make_user()
            db.add(user)
            await db.commit()
            await db.refresh(user)

            limits = SafetyLimits(
                user_id=user.id,
                min_glucose_mgdl=20,
                max_glucose_mgdl=500,
                max_basal_rate_milliunits=15000,
                max_bolus_dose_milliunits=10000,
                max_daily_bolus_milliunits=50000,
            )
            db.add(limits)
            db.add(
                PumpEvent(
                    user_id=user.id,
                    event_type=PumpEventType.BOLUS,
                    event_timestamp=_NOW - timedelta(hours=2),
                    units=10.0,
                    is_automated=False,
                    received_at=_NOW - timedelta(hours=2),
                )
            )
            await db.commit()
            await db.refresh(limits)

            validator = TreatmentSafetyValidator()
            request = _make_request(
                user_id=user.id,
                requested_dose_milliunits=5000,  # 10000 + 5000 = 15000 < 50000
            )
            result = await validator._check_max_daily_total(request, limits, db, _NOW)
            assert result.passed is True


class TestCheckCgmFreshness:
    async def test_pass_recent_reading(self):
        session_maker = get_session_maker()
        async with session_maker() as db:
            user = _make_user()
            db.add(user)
            await db.commit()
            await db.refresh(user)

            db.add(
                GlucoseReading(
                    user_id=user.id,
                    value=180,
                    reading_timestamp=_NOW - timedelta(minutes=5),
                    trend=TrendDirection.FLAT,
                    received_at=_NOW - timedelta(minutes=5),
                )
            )
            await db.commit()

            validator = TreatmentSafetyValidator()
            request = _make_request(user_id=user.id)
            result = await validator._check_cgm_freshness(request, db, _NOW)
            assert result.passed is True

    async def test_fail_stale_reading(self):
        session_maker = get_session_maker()
        async with session_maker() as db:
            user = _make_user()
            db.add(user)
            await db.commit()
            await db.refresh(user)

            db.add(
                GlucoseReading(
                    user_id=user.id,
                    value=180,
                    reading_timestamp=_NOW - timedelta(minutes=20),
                    trend=TrendDirection.FLAT,
                    received_at=_NOW - timedelta(minutes=20),
                )
            )
            await db.commit()

            validator = TreatmentSafetyValidator()
            request = _make_request(user_id=user.id)
            result = await validator._check_cgm_freshness(request, db, _NOW)
            assert result.passed is False
            assert "exceeds" in result.message

    async def test_fail_no_readings(self):
        session_maker = get_session_maker()
        async with session_maker() as db:
            user = _make_user()
            db.add(user)
            await db.commit()
            await db.refresh(user)

            validator = TreatmentSafetyValidator()
            request = _make_request(user_id=user.id)
            result = await validator._check_cgm_freshness(request, db, _NOW)
            assert result.passed is False
            assert "No CGM readings" in result.message

    async def test_pass_at_boundary(self):
        session_maker = get_session_maker()
        async with session_maker() as db:
            user = _make_user()
            db.add(user)
            await db.commit()
            await db.refresh(user)

            db.add(
                GlucoseReading(
                    user_id=user.id,
                    value=180,
                    reading_timestamp=_NOW
                    - timedelta(minutes=CGM_FRESHNESS_MAX_MINUTES),
                    trend=TrendDirection.FLAT,
                    received_at=_NOW - timedelta(minutes=CGM_FRESHNESS_MAX_MINUTES),
                )
            )
            await db.commit()

            validator = TreatmentSafetyValidator()
            request = _make_request(user_id=user.id)
            result = await validator._check_cgm_freshness(request, db, _NOW)
            assert result.passed is True


class TestCheckRateLimit:
    async def test_pass_no_recent_bolus(self):
        session_maker = get_session_maker()
        async with session_maker() as db:
            user = _make_user()
            db.add(user)
            await db.commit()
            await db.refresh(user)

            validator = TreatmentSafetyValidator()
            request = _make_request(user_id=user.id)
            result = await validator._check_rate_limit(request, db, _NOW)
            assert result.passed is True

    async def test_fail_recent_bolus(self):
        session_maker = get_session_maker()
        async with session_maker() as db:
            user = _make_user()
            db.add(user)
            await db.commit()
            await db.refresh(user)

            db.add(
                PumpEvent(
                    user_id=user.id,
                    event_type=PumpEventType.BOLUS,
                    event_timestamp=_NOW - timedelta(minutes=5),
                    units=2.0,
                    is_automated=False,
                    received_at=_NOW - timedelta(minutes=5),
                )
            )
            await db.commit()

            validator = TreatmentSafetyValidator()
            request = _make_request(user_id=user.id)
            result = await validator._check_rate_limit(request, db, _NOW)
            assert result.passed is False
            assert "minimum interval" in result.message

    async def test_pass_old_bolus(self):
        session_maker = get_session_maker()
        async with session_maker() as db:
            user = _make_user()
            db.add(user)
            await db.commit()
            await db.refresh(user)

            db.add(
                PumpEvent(
                    user_id=user.id,
                    event_type=PumpEventType.BOLUS,
                    event_timestamp=_NOW - timedelta(minutes=20),
                    units=2.0,
                    is_automated=False,
                    received_at=_NOW - timedelta(minutes=20),
                )
            )
            await db.commit()

            validator = TreatmentSafetyValidator()
            request = _make_request(user_id=user.id)
            result = await validator._check_rate_limit(request, db, _NOW)
            assert result.passed is True


# ---------------------------------------------------------------------------
# Integration -- full validate_bolus_request
# ---------------------------------------------------------------------------


class TestValidateBolusRequest:
    """Integration tests for validate_bolus_request.

    These use server time internally (datetime.now(UTC)), so test data
    timestamps must be relative to the actual current time.
    """

    async def test_all_pass_approved(self):
        now = datetime.now(UTC)
        session_maker = get_session_maker()
        async with session_maker() as db:
            user = _make_user()
            db.add(user)
            await db.commit()
            await db.refresh(user)

            limits = SafetyLimits(
                user_id=user.id,
                min_glucose_mgdl=20,
                max_glucose_mgdl=500,
                max_basal_rate_milliunits=15000,
                max_bolus_dose_milliunits=10000,
                max_daily_bolus_milliunits=50000,
            )
            db.add(limits)
            db.add(
                GlucoseReading(
                    user_id=user.id,
                    value=180,
                    reading_timestamp=now - timedelta(minutes=2),
                    trend=TrendDirection.FLAT,
                    received_at=now - timedelta(minutes=2),
                )
            )
            await db.commit()

            validator = TreatmentSafetyValidator()
            request = _make_request(
                user_id=user.id,
                requested_dose_milliunits=5000,
                glucose_at_request_mgdl=180,
            )
            result = await validator.validate_bolus_request(
                request, db, safety_limits=limits
            )
            assert result.approved is True
            assert result.validated_dose_milliunits == 5000
            assert result.rejection_reasons == []
            assert len(result.safety_check_results) == 6

    async def test_single_failure_rejects(self):
        now = datetime.now(UTC)
        session_maker = get_session_maker()
        async with session_maker() as db:
            user = _make_user()
            db.add(user)
            await db.commit()
            await db.refresh(user)

            limits = SafetyLimits(
                user_id=user.id,
                min_glucose_mgdl=20,
                max_glucose_mgdl=500,
                max_basal_rate_milliunits=15000,
                max_bolus_dose_milliunits=10000,
                max_daily_bolus_milliunits=50000,
            )
            db.add(limits)
            db.add(
                GlucoseReading(
                    user_id=user.id,
                    value=180,
                    reading_timestamp=now - timedelta(minutes=2),
                    trend=TrendDirection.FLAT,
                    received_at=now - timedelta(minutes=2),
                )
            )
            await db.commit()

            validator = TreatmentSafetyValidator()
            request = _make_request(
                user_id=user.id,
                requested_dose_milliunits=15000,  # Over 10000 limit
                glucose_at_request_mgdl=180,
            )
            result = await validator.validate_bolus_request(
                request, db, safety_limits=limits
            )
            assert result.approved is False
            assert result.validated_dose_milliunits == 0
            assert len(result.rejection_reasons) >= 1
            assert any("exceeds" in r for r in result.rejection_reasons)

    async def test_multiple_failures_all_reported(self):
        now = datetime.now(UTC)
        session_maker = get_session_maker()
        async with session_maker() as db:
            user = _make_user()
            db.add(user)
            await db.commit()
            await db.refresh(user)

            limits = SafetyLimits(
                user_id=user.id,
                min_glucose_mgdl=20,
                max_glucose_mgdl=500,
                max_basal_rate_milliunits=15000,
                max_bolus_dose_milliunits=10000,
                max_daily_bolus_milliunits=50000,
            )
            db.add(limits)
            # Add recent bolus but NO CGM reading
            db.add(
                PumpEvent(
                    user_id=user.id,
                    event_type=PumpEventType.BOLUS,
                    event_timestamp=now - timedelta(minutes=2),
                    units=2.0,
                    is_automated=False,
                    received_at=now - timedelta(minutes=2),
                )
            )
            await db.commit()

            validator = TreatmentSafetyValidator()
            request = _make_request(
                user_id=user.id,
                requested_dose_milliunits=15000,
                glucose_at_request_mgdl=180,
            )
            result = await validator.validate_bolus_request(
                request, db, safety_limits=limits
            )
            assert result.approved is False
            # Should have at least 3 failures: single bolus, CGM freshness, rate limit
            assert len(result.rejection_reasons) >= 3
