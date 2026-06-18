"""Tests for shared unit conversion helpers."""

from src.core.units import MGDL_PER_MMOL, GlucoseUnit, mgdl_to_mmol, mmol_to_mgdl
from src.services.integrations.nightscout import models as nightscout_models
from src.services.integrations.nightscout.onboarding_derive import MMOL_TO_MGDL


def test_glucose_unit_values():
    assert GlucoseUnit.MGDL.value == "mgdl"
    assert GlucoseUnit.MMOL.value == "mmol"


def test_standard_mgdl_reference_points_convert_to_mmol():
    assert mgdl_to_mmol(70) == 3.9
    assert mgdl_to_mmol(180) == 10.0
    assert mgdl_to_mmol(120) == 6.7


def test_whole_mgdl_round_trip_stays_within_display_precision():
    for mgdl in range(20, 501):
        mmol = mgdl_to_mmol(mgdl)
        mgdl_again = mmol_to_mgdl(mmol)
        mmol_again = mgdl_to_mmol(mgdl_again)

        assert abs(mgdl_again - mgdl) <= 1
        assert abs(mmol_again - mmol) <= 0.1


def test_safety_bounds_convert_to_mmol():
    # The 20-500 mg/dL safety invariant expressed in mmol/L. A mis-converted
    # hypo bound silently suppresses low alerts, so the endpoints are pinned.
    assert mgdl_to_mmol(20) == 1.1
    assert mgdl_to_mmol(500) == 27.7


def test_round_trip_is_lossy_so_converted_values_are_never_persisted():
    # mg/dL -> mmol(1dp) -> mg/dL loses precision (100 -> 5.5 -> 99), which is
    # why a converted value must never be written back to canonical mg/dL
    # storage (Epic 53 decision #5). Guards a future change that wrongly
    # assumes the round trip is identity-preserving.
    assert mmol_to_mgdl(mgdl_to_mmol(100)) != 100


def test_legacy_nightscout_constants_point_to_shared_constant():
    assert MGDL_PER_MMOL == 18.0182
    assert nightscout_models.MGDL_PER_MMOL == MGDL_PER_MMOL
    assert MMOL_TO_MGDL == MGDL_PER_MMOL
