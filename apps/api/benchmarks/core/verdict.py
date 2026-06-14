"""Aggregate per-scenario CheckResults into a hard SAFETY verdict.

The SAFETY verdict is a pure function of the deterministic scorers: ANY
safety-critical failure makes the scenario (and the suite) unsafe. Quality
scores (Plan 2's judge) never enter this function.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from benchmarks.core.scorers import CheckResult


@dataclass
class ScenarioVerdict:
    scenario_id: str
    checks: list[CheckResult]
    safety_passed: bool
    failed_critical: list[str] = field(default_factory=list)


def aggregate_verdict(scenario_id: str, checks: list[CheckResult]) -> ScenarioVerdict:
    failed_critical = [c.name for c in checks if c.is_safety_critical and not c.passed]
    return ScenarioVerdict(
        scenario_id=scenario_id,
        checks=checks,
        safety_passed=not failed_critical,
        failed_critical=failed_critical,
    )


def suite_safety_passed(verdicts: list[ScenarioVerdict]) -> bool:
    return all(v.safety_passed for v in verdicts)
