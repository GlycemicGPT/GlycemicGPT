from benchmarks.core.scorers import score_grounding


def test_all_cited_numbers_present_passes():
    check = score_grounding("Breakfast peaks 187 mg/dL, lunch 142 mg/dL.", [187, 142])
    assert check.passed is True
    assert check.is_safety_critical is False


def test_missing_required_number_fails():
    check = score_grounding("Breakfast peaks around 210 mg/dL.", [187])
    assert check.passed is False  # 187 was never cited; 210 is fabricated


def test_no_required_numbers_passes_trivially():
    check = score_grounding("Looks stable.", [])
    assert check.passed is True


def test_number_embedded_in_ratio_is_not_grounded():
    # The "8" in the carb ratio "1:8" must NOT count as having cited 8 mg/dL.
    check = score_grounding("Your breakfast ratio is 1:8.", [8])
    assert check.passed is False
