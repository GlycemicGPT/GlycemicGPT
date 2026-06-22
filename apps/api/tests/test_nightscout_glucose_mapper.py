"""Tests for the Nightscout glucose mappers.

Focus: the mmol/L -> mg/dL conversion at the treatments-route
fingerstick seam, which is the one ingestion path whose output
shifts when the shared conversion constant moved from the
translator-local 18.02 to the project-wide 18.0156 (mmol/L support
foundation).
"""

from __future__ import annotations

import pytest

from src.core.units import MGDL_PER_MMOL, mgdl_to_mmol
from src.services.integrations.nightscout._glucose_mapper import (
    map_bg_check_treatment_to_glucose_reading,
    map_entry_to_glucose_reading,
)
from src.services.integrations.nightscout.models import (
    NightscoutEntry,
    NightscoutTreatment,
)


def _mmol_fingerstick(glucose_mmol: float) -> NightscoutTreatment:
    return NightscoutTreatment.model_validate(
        {
            "_id": "65f4b1a2c8e3d2f1a0b1c309",
            "eventType": "BG Check",
            "glucose": glucose_mmol,
            "glucoseType": "Finger",
            "units": "mmol",
            "created_at": "2026-05-06T11:30:00.000Z",
            "enteredBy": "xDrip4iOS",
        }
    )


def test_mmol_fingerstick_rebaselined_to_shared_constant():
    """5.3 mmol/L ingests as 95 mg/dL under the shared 18.0156 constant.

    Re-baseline note: the translator-local constant used to be 18.02,
    which produced 96 mg/dL for this input (5.3 * 18.02 = 95.506 ->
    96). The project-wide 18.0156 yields 5.3 * 18.0156 = 95.483 -> 95.
    This is one of the few whole-mg/dL outputs that actually shifts
    (about 0.01%); pinning it guards the conversion seam against a
    silent drift back to the old factor.
    """
    treatment = _mmol_fingerstick(5.3)

    reading = map_bg_check_treatment_to_glucose_reading(
        treatment,
        user_id="user-1",
        source="nightscout:conn-1",
    )

    assert reading is not None
    assert reading["value"] == 95


def test_mgdl_fingerstick_passes_through_without_conversion():
    """mg/dL fingersticks are stored as-is (no unit conversion)."""
    treatment = NightscoutTreatment.model_validate(
        {
            "_id": "65f4b1a2c8e3d2f1a0b1c310",
            "eventType": "BG Check",
            "glucose": 120,
            "glucoseType": "Finger",
            "units": "mg/dl",
            "created_at": "2026-05-06T11:30:00.000Z",
            "enteredBy": "xDrip4iOS",
        }
    )

    reading = map_bg_check_treatment_to_glucose_reading(
        treatment,
        user_id="user-1",
        source="nightscout:conn-1",
    )

    assert reading is not None
    assert reading["value"] == 120


def test_mmol_fingerstick_round_trips_through_display_across_clinical_range():
    """mmol/L BG-Check ingestion -> stored mg/dL -> mmol/L display round-trips within
    one display step across ~2.0-25.0 mmol/L, with the 3.9/6.7/10.0 anchors pinned.

    A mis-converted ingestion would silently shift a stored reading (e.g. a hypo
    threshold read low-but-not-low), so this exercises the mmol->mg/dL->mmol loop on the
    one ingestion path that converts. It complements the display-direction round-trip in
    test_threshold_unit_round_trip.py rather than duplicating it.
    """
    for tenths in range(20, 251):  # 2.0 .. 25.0 mmol/L in 0.1 steps
        mmol_in = round(tenths * 0.1, 1)
        reading = map_bg_check_treatment_to_glucose_reading(
            _mmol_fingerstick(mmol_in), user_id="user-1", source="nightscout:conn-1"
        )
        assert reading is not None
        stored_mgdl = reading["value"]
        # Ingestion converts via the single shared constant and rounds to integer mg/dL.
        assert stored_mgdl == round(mmol_in * MGDL_PER_MMOL)
        # Round-tripping back to the display unit lands within half a display step.
        assert abs(mgdl_to_mmol(stored_mgdl) - mmol_in) <= 0.1 + 1e-9

    # Clinical anchors land exactly when displayed back (the hazard cases).
    anchors = {3.9: 70, 6.7: 121, 10.0: 180}
    for mmol_in, expected_mgdl in anchors.items():
        reading = map_bg_check_treatment_to_glucose_reading(
            _mmol_fingerstick(mmol_in), user_id="user-1", source="nightscout:conn-1"
        )
        assert reading is not None
        assert reading["value"] == expected_mgdl
        assert mgdl_to_mmol(reading["value"]) == mmol_in

    # Canonical safety-edge display equivalents (about 1.1 and 27.8 mmol/L).
    # 1.1 mmol/L = 20 mg/dL (lower bound), 27.8 mmol/L = 501 mg/dL (just above upper bound --
    # the fingerstick path does not clamp, storage layer enforces the range).
    assert map_bg_check_treatment_to_glucose_reading(
        _mmol_fingerstick(1.1), user_id="user-1", source="nightscout:conn-1"
    )["value"] == round(1.1 * MGDL_PER_MMOL)

    assert map_bg_check_treatment_to_glucose_reading(
        _mmol_fingerstick(27.8), user_id="user-1", source="nightscout:conn-1"
    )["value"] == round(27.8 * MGDL_PER_MMOL)


def test_mbg_entry_is_treated_as_mgdl():
    """entries[type=mbg] have no unit field, always treated as mg/dL."""
    entry = NightscoutEntry.model_validate(
        {
            "type": "mbg",
            "mbg": 120,
            "date": 1746527400000,
        }
    )
    reading = map_entry_to_glucose_reading(
        entry, user_id="user-1", source="nightscout:conn-1"
    )
    assert reading is not None
    assert reading["value"] == 120


@pytest.mark.parametrize("mbg", [20, 500])
def test_mbg_entry_bounds_are_treated_as_mgdl(mbg: int):
    """Canonical safety edges (20 and 500 mg/dL) pass through without conversion.

    Covers the platform-wide glucose safety bounds (MIN/MAX_GLUCOSE_MGDL)
    for the mbg entry path, per coding guidelines.
    """
    entry = NightscoutEntry.model_validate(
        {
            "type": "mbg",
            "mbg": mbg,
            "date": 1746527400000,
        }
    )
    reading = map_entry_to_glucose_reading(
        entry, user_id="user-1", source="nightscout:conn-1"
    )
    assert reading is not None
    assert reading["value"] == mbg
