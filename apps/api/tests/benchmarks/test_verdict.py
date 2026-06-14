from benchmarks.core.scorers import CheckResult
from benchmarks.core.verdict import (
    ScenarioVerdict,
    aggregate_verdict,
    suite_safety_passed,
)


def _ok(name, critical=False):
    return CheckResult(name=name, passed=True, is_safety_critical=False, detail="ok")


def _fail_critical(name):
    return CheckResult(name=name, passed=False, is_safety_critical=True, detail="bad")


def test_all_pass_is_safe():
    v = aggregate_verdict("meal-001", [_ok("safety"), _ok("dose_numbers"), _ok("units")])
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
