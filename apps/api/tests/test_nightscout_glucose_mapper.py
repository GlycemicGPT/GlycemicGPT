"""Tests for the Nightscout glucose mappers.

Focus: the mmol/L -> mg/dL conversion at the treatments-route
fingerstick seam, which is the one ingestion path whose output
shifts when the shared conversion constant moved from the
translator-local 18.02 to the project-wide 18.0156 (mmol/L support
foundation).
"""

from __future__ import annotations

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
