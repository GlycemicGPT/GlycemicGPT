"""Round-trip + safety-bound property tests for mmol/L threshold input.

The web converts a user's mmol/L threshold entry to integer mg/dL and clamps it
to the canonical bound before it leaves the browser; the API stays canonical
mg/dL and rejects out-of-range values via the Pydantic schema bounds. These
tests guard that safety contract on the BACKEND side too -- the conversion
factor (18.0156) and rounding are shared with the web, and Telegram/escalation
are fire-and-forget (no runtime signal), so the round-trip and factor/anchor
assertions below are the guard against a mis-converted threshold silently
suppressing a life-safety alert.
"""

import math

import pytest
from pydantic import ValidationError

from src.core.units import MGDL_PER_MMOL, mgdl_to_mmol, mmol_to_mgdl
from src.schemas.alert_threshold import AlertThresholdUpdate
from src.schemas.safety_limits import SafetyLimitsUpdate
from src.schemas.target_glucose_range import TargetGlucoseRangeUpdate

# Canonical platform-wide glucose safety invariant.
SAFETY_MIN_MGDL = 20
SAFETY_MAX_MGDL = 500


def _store_from_mmol(
    mmol: float, lo: int = SAFETY_MIN_MGDL, hi: int = SAFETY_MAX_MGDL
) -> int:
    """Mirror the web save path: mmol/L entry -> integer mg/dL -> clamp to bound.

    ``mmol_to_mgdl`` already rounds to an int (matching the web ``toStoredMgdl``);
    the clamp matches the web ``clampMgdl`` so a 1-decimal boundary overshoot
    (e.g. 27.8 mmol -> 501) never crosses the canonical ceiling.
    """
    return min(hi, max(lo, mmol_to_mgdl(mmol)))


def _mmol_domain() -> list[float]:
    """A 0.1-step sweep across (and beyond) the displayable mmol/L range."""
    return [round(0.1 * n, 1) for n in range(5, 351)]  # 0.5 .. 35.0 mmol/L


class TestMmolStorePathStaysInBounds:
    """No mmol entry can write a sub-20 or super-500 mg/dL value."""

    def test_clamped_store_is_always_within_the_safety_invariant(self):
        for mmol in _mmol_domain():
            stored = _store_from_mmol(mmol)
            assert SAFETY_MIN_MGDL <= stored <= SAFETY_MAX_MGDL, (
                f"{mmol} mmol stored as {stored} mg/dL escapes 20-500"
            )

    def test_hypo_floor_is_not_evaded_by_the_mmol_path(self):
        # The classic hazard: storing 3.9 *as if mg/dL* instead of converting it.
        # 3.9 mmol/L must persist as ~70 mg/dL (the hypo threshold), never 3.9.
        assert mmol_to_mgdl(3.9) == 70
        assert _store_from_mmol(3.9) == 70
        # A direction error (dividing instead of multiplying) would yield ~0.2;
        # the real conversion never produces a sub-floor value for a real reading.
        assert _store_from_mmol(3.9) >= SAFETY_MIN_MGDL


class TestMmolRoundTrip:
    """A mmol entry round-trips to the same displayed mmol value."""

    def test_round_trip_pins_the_canonical_conversion_factor(self):
        # The round-trip below is self-consistent under any factor; these
        # assertions pin the single canonical 18.0156 so a wrong factor (18.02 /
        # 18.0182) fails here directly, not only in the core-units anchor tests.
        assert MGDL_PER_MMOL == 18.0156
        # Hard-coded expected mg/dL for known mmol entries (round(mmol*18.0156)).
        assert mmol_to_mgdl(3.9) == 70
        assert mmol_to_mgdl(5.6) == 101
        assert mmol_to_mgdl(10.0) == 180

    def test_clinical_anchors_round_trip_exactly(self):
        # 70/180/120 mg/dL display as 3.9/10.0/6.7 mmol; entering those mmol
        # values stores an integer mg/dL that displays as the same mmol again.
        for mmol in (3.9, 10.0, 6.7):
            assert mgdl_to_mmol(mmol_to_mgdl(mmol)) == mmol

    def test_displayable_domain_round_trips_within_one_display_step(self):
        # INT mg/dL storage means the mmol value may "snap" by at most one
        # 0.1-mmol display step; it never drifts further (the rounding policy).
        for mmol in [round(0.1 * n, 1) for n in range(11, 278)]:  # 1.1 .. 27.7
            back = mgdl_to_mmol(mmol_to_mgdl(mmol))
            assert math.isclose(back, mmol, abs_tol=0.1 + 1e-9), (
                f"{mmol} mmol -> {mmol_to_mgdl(mmol)} mg/dL -> {back} mmol drifts"
            )

    def test_int_column_rounding_is_what_the_user_sees(self):
        # SafetyLimits min/max are INT columns. 5.5 mmol persists as 99
        # mg/dL and re-displays as 5.5 -- the persisted value the UI surfaces.
        stored = mmol_to_mgdl(5.5)
        assert stored == 99
        assert mgdl_to_mmol(stored) == 5.5


class TestSchemaBoundsRejectOutOfRangeMmolEntries:
    """The Pydantic mg/dL bounds reject a mmol entry that converts out of range,
    so the mmol input path cannot evade the canonical limits."""

    def test_alert_threshold_rejects_dangerously_low_urgent_low(self):
        # 1.0 mmol -> 18 mg/dL, below urgent_low's 30 mg/dL floor.
        with pytest.raises(ValidationError):
            AlertThresholdUpdate(urgent_low=float(mmol_to_mgdl(1.0)))

    def test_alert_threshold_accepts_in_range_converted_value(self):
        # 3.1 mmol -> 56 mg/dL, within urgent_low's 30-80 mg/dL range.
        model = AlertThresholdUpdate(urgent_low=float(mmol_to_mgdl(3.1)))
        assert model.urgent_low == 56

    def test_target_range_rejects_super_ceiling_urgent_high(self):
        # 30 mmol -> 540 mg/dL, above urgent_high's 500 mg/dL ceiling.
        with pytest.raises(ValidationError):
            TargetGlucoseRangeUpdate(urgent_high=float(mmol_to_mgdl(30.0)))

    def test_safety_limits_rejects_sub_floor_min_glucose(self):
        # 0.5 mmol -> 9 mg/dL, below the 20 mg/dL floor.
        with pytest.raises(ValidationError):
            SafetyLimitsUpdate(min_glucose_mgdl=mmol_to_mgdl(0.5))

    def test_safety_limits_accepts_in_range_converted_min_glucose(self):
        # 3.9 mmol -> 70 mg/dL, within min_glucose's 20-499 range.
        model = SafetyLimitsUpdate(min_glucose_mgdl=mmol_to_mgdl(3.9))
        assert model.min_glucose_mgdl == 70
