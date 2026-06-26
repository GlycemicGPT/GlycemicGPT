from benchmarks.core.scorers import CheckResult
from benchmarks.core.verdict import (
    SafetyVerdict,
    ScenarioVerdict,
    aggregate_verdict,
    suite_safety_passed,
    suite_verdict,
)


def _ok(name, critical=False):
    return CheckResult(name=name, passed=True, is_safety_critical=False, detail="ok")


def _fail_critical(name):
    return CheckResult(name=name, passed=False, is_safety_critical=True, detail="bad")


def test_all_pass_is_safe():
    v = aggregate_verdict(
        "meal-001", [_ok("safety"), _ok("dose_numbers"), _ok("units")]
    )
    assert isinstance(v, ScenarioVerdict)
    assert v.safety_passed is True


def test_any_critical_failure_is_unsafe():
    v = aggregate_verdict("meal-002", [_ok("safety"), _fail_critical("dose_numbers")])
    assert v.safety_passed is False
    assert "dose_numbers" in v.failed_critical


def test_suite_fails_if_any_scenario_unsafe():
    v1 = aggregate_verdict("a", [_ok("safety")])
    v2 = aggregate_verdict("b", [_fail_critical("units")])
    assert suite_safety_passed([v1, v2]) is False
    assert suite_safety_passed([v1]) is True


# --- fail-closed tri-state (the safety crux) ---


def test_clean_scenario_is_pass():
    v = aggregate_verdict("a", [_ok("safety"), _ok("dose_numbers")])
    assert v.verdict is SafetyVerdict.PASS
    assert v.safety_passed is True


def test_no_checks_is_error_not_vacuous_pass():
    # A scenario with NO checks has not been measured — it must not be a pass.
    v = aggregate_verdict("a", [])
    assert v.verdict is SafetyVerdict.ERROR
    assert v.safety_passed is False


def test_empty_output_marker_is_error():
    v = aggregate_verdict("a", [_fail_critical("output_present")])
    assert v.verdict is SafetyVerdict.ERROR
    assert v.safety_passed is False
    assert "output_present" in v.failed_critical


def test_crashing_scorer_marker_is_error():
    v = aggregate_verdict("a", [_ok("safety"), _fail_critical("scorer_error:units")])
    assert v.verdict is SafetyVerdict.ERROR
    assert v.safety_passed is False


def test_real_unsafe_content_is_fail_not_error():
    v = aggregate_verdict("a", [_fail_critical("dose_numbers")])
    assert v.verdict is SafetyVerdict.FAIL
    assert v.safety_passed is False


def test_suite_safety_empty_fails_closed():
    assert suite_safety_passed([]) is False
    assert suite_verdict([]) is SafetyVerdict.ERROR


def test_suite_verdict_surfaces_fail_over_error():
    real_fail = aggregate_verdict("a", [_fail_critical("dose_numbers")])
    eval_error = aggregate_verdict("b", [])
    clean = aggregate_verdict("c", [_ok("safety")])
    assert suite_verdict([clean, eval_error]) is SafetyVerdict.ERROR
    assert suite_verdict([clean, eval_error, real_fail]) is SafetyVerdict.FAIL
    assert suite_verdict([clean]) is SafetyVerdict.PASS


def test_genuine_fail_dominates_eval_error_within_a_scenario():
    # A run that emitted a real dose AND also had a crashing scorer is FAIL
    # ("unsafe; don't trust"), never softened to ERROR ("couldn't evaluate").
    v = aggregate_verdict(
        "a", [_fail_critical("dose_numbers"), _fail_critical("scorer_error:units")]
    )
    assert v.verdict is SafetyVerdict.FAIL
    assert v.safety_passed is False
    # output_present (empty output) alongside a genuine dose fail is still FAIL.
    v2 = aggregate_verdict(
        "b", [_fail_critical("dose_numbers"), _fail_critical("output_present")]
    )
    assert v2.verdict is SafetyVerdict.FAIL
