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


def test_legacy_nightscout_constants_point_to_shared_constant():
    assert MGDL_PER_MMOL == 18.0182
    assert nightscout_models.MGDL_PER_MMOL == MGDL_PER_MMOL
    assert MMOL_TO_MGDL == MGDL_PER_MMOL
