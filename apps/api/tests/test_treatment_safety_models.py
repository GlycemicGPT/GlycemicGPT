"""Tests for treatment safety models and enums.

Verifies Pydantic model construction, enum values, and field validation bounds.
"""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.core.treatment_safety.enums import (
    BolusSource,
    SafetyCheckType,
    ValidationStatus,
)
from src.core.treatment_safety.models import (
    BolusRequest,
    BolusValidationResult,
    SafetyCheckResult,
)

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestSafetyCheckType:
    def test_all_values_exist(self):
        expected = {
            "max_single_bolus",
            "max_daily_total",
            "cgm_freshness",
            "rate_limit",
            "glucose_range_check",
            "user_confirmation_required",
        }
        assert {e.value for e in SafetyCheckType} == expected

    def test_string_enum(self):
        assert SafetyCheckType.max_single_bolus == "max_single_bolus"


class TestBolusSource:
    def test_all_values_exist(self):
        expected = {"manual", "ai_suggested", "automated"}
        assert {e.value for e in BolusSource} == expected


class TestValidationStatus:
    def test_all_values_exist(self):
        expected = {"approved", "rejected"}
        assert {e.value for e in ValidationStatus} == expected


# ---------------------------------------------------------------------------
# Model construction tests
# ---------------------------------------------------------------------------


_FIXED_TIMESTAMP = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)


def _make_bolus_request(**overrides) -> BolusRequest:
    defaults = {
        "user_id": uuid.uuid4(),
        "requested_dose_milliunits": 1000,
        "glucose_at_request_mgdl": 180,
        "timestamp": _FIXED_TIMESTAMP,
        "source": BolusSource.manual,
    }
    defaults.update(overrides)
    return BolusRequest(**defaults)


class TestBolusRequest:
    def test_valid_construction(self):
        req = _make_bolus_request()
        assert req.requested_dose_milliunits == 1000
        assert req.glucose_at_request_mgdl == 180
        assert req.source == BolusSource.manual

    def test_zero_dose_allowed(self):
        req = _make_bolus_request(requested_dose_milliunits=0)
        assert req.requested_dose_milliunits == 0

    def test_max_dose_allowed(self):
        req = _make_bolus_request(requested_dose_milliunits=25000)
        assert req.requested_dose_milliunits == 25000

    def test_dose_too_high(self):
        with pytest.raises(ValidationError):
            _make_bolus_request(requested_dose_milliunits=25001)

    def test_negative_dose_rejected(self):
        with pytest.raises(ValidationError):
            _make_bolus_request(requested_dose_milliunits=-1)

    def test_glucose_lower_bound(self):
        req = _make_bolus_request(glucose_at_request_mgdl=20)
        assert req.glucose_at_request_mgdl == 20

    def test_glucose_upper_bound(self):
        req = _make_bolus_request(glucose_at_request_mgdl=500)
        assert req.glucose_at_request_mgdl == 500

    def test_glucose_below_range(self):
        with pytest.raises(ValidationError):
            _make_bolus_request(glucose_at_request_mgdl=19)

    def test_glucose_above_range(self):
        with pytest.raises(ValidationError):
            _make_bolus_request(glucose_at_request_mgdl=501)

    @pytest.mark.parametrize("source", list(BolusSource))
    def test_all_bolus_sources_accepted(self, source):
        req = _make_bolus_request(source=source)
        assert req.source == source

    def test_naive_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            _make_bolus_request(timestamp=datetime(2025, 1, 15, 12, 0, 0))


class TestSafetyCheckResult:
    def test_valid_construction(self):
        result = SafetyCheckResult(
            check_type=SafetyCheckType.max_single_bolus,
            passed=True,
            message="Within limits",
        )
        assert result.passed is True
        assert result.details is None

    def test_with_details(self):
        result = SafetyCheckResult(
            check_type=SafetyCheckType.cgm_freshness,
            passed=False,
            message="CGM reading too old",
            details={"age_minutes": 15, "max_age_minutes": 5},
        )
        assert result.details["age_minutes"] == 15

    def test_empty_message_rejected(self):
        with pytest.raises(ValidationError):
            SafetyCheckResult(
                check_type=SafetyCheckType.max_single_bolus,
                passed=True,
                message="",
            )


class TestBolusValidationResult:
    def test_approved_construction(self):
        result = BolusValidationResult(
            approved=True,
            validated_dose_milliunits=1000,
        )
        assert result.approved is True
        assert result.rejection_reasons == []
        assert result.warnings == []
        assert result.safety_check_results == []

    def test_rejected_construction(self):
        result = BolusValidationResult(
            approved=False,
            rejection_reasons=["Exceeds max single bolus"],
        )
        assert result.approved is False
        assert len(result.rejection_reasons) == 1
        assert result.validated_dose_milliunits == 0

    @pytest.mark.parametrize("invalid_dose", [-1, 25001])
    def test_validated_dose_out_of_bounds_rejected(self, invalid_dose):
        with pytest.raises(ValidationError):
            BolusValidationResult(
                approved=True,
                validated_dose_milliunits=invalid_dose,
            )

    def test_rejected_with_nonzero_dose_invalid(self):
        with pytest.raises(ValidationError):
            BolusValidationResult(
                approved=False,
                rejection_reasons=["Exceeds limit"],
                validated_dose_milliunits=500,
            )

    def test_approved_with_rejection_reasons_invalid(self):
        with pytest.raises(ValidationError):
            BolusValidationResult(
                approved=True,
                rejection_reasons=["Should not be here"],
                validated_dose_milliunits=1000,
            )

    def test_approved_with_zero_dose_invalid(self):
        with pytest.raises(ValidationError):
            BolusValidationResult(
                approved=True,
                validated_dose_milliunits=0,
            )

    def test_rejected_without_reasons_invalid(self):
        with pytest.raises(ValidationError):
            BolusValidationResult(
                approved=False,
                rejection_reasons=[],
            )


# ---------------------------------------------------------------------------
# user_confirmed field tests
# ---------------------------------------------------------------------------


class TestBolusRequestUserConfirmed:
    def test_defaults_to_false(self):
        req = _make_bolus_request()
        assert req.user_confirmed is False

    def test_explicit_true(self):
        req = _make_bolus_request(user_confirmed=True)
        assert req.user_confirmed is True

    def test_explicit_false(self):
        req = _make_bolus_request(user_confirmed=False)
        assert req.user_confirmed is False
