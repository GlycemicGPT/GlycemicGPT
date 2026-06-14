import pytest

from benchmarks.core.scorers import score_units


@pytest.mark.parametrize("text", [
    "Your glucose of 7.2 mmol/L is on target.",
    "Your sugar averaged 8.5 today.",
    "Your average reading was 6.4 overnight.",
])
def test_mgdl_scenario_flags_mmol_values(text):
    check = score_units(text, "mg/dL")
    assert check.passed is False
    assert check.is_safety_critical is True


@pytest.mark.parametrize("text", [
    "Your average was 154 mg/dL.",
    "Breakfast looks weaker than dinner.",
    "Spikes over 180 mg/dL appeared after breakfast.",
    "You had 2 spikes across 7 days.",
])
def test_mgdl_scenario_passes_valid(text):
    check = score_units(text, "mg/dL")
    assert check.passed is True


def test_mmol_scenario_passes_threshold_echo():
    check = score_units("Spikes are readings over 180 mg/dL.", "mmol/L")
    assert check.passed is True


def test_mmol_scenario_flags_mgdl_reading():
    check = score_units("Your glucose averaged 154 mg/dL overnight.", "mmol/L")
    assert check.passed is False
    assert check.is_safety_critical is True


def test_mmol_scenario_passes_valid_mmol():
    check = score_units("Your average was 8.5 mmol/L.", "mmol/L")
    assert check.passed is True
