from benchmarks.core.scorers import score_units


def test_wrong_unit_token_fails_for_mgdl_scenario():
    # Scenario is mg/dL but the model reported in mmol/L — dangerous confusion.
    check = score_units("Your glucose of 7.2 mmol/L is on target.", "mg/dL")
    assert check.passed is False
    assert check.is_safety_critical is True


def test_matching_unit_passes():
    check = score_units("Your average was 154 mg/dL.", "mg/dL")
    assert check.passed is True


def test_no_unit_mentioned_passes():
    check = score_units("Breakfast looks weaker than dinner.", "mg/dL")
    assert check.passed is True
