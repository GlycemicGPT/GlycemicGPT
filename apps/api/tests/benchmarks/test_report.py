import json

from benchmarks.core.report import build_report, render_markdown
from benchmarks.core.runner import RunResult
from benchmarks.core.scorers import CheckResult
from benchmarks.core.verdict import aggregate_verdict


def _run(latency=1.2, out_tokens=40):
    return RunResult(
        scenario_id="meal-001", surface="meal_analysis",
        system_prompt="sys", user_prompt="usr", output="Breakfast 187 mg/dL.",
        model="mock-model", latency_s=latency, input_tokens=100, output_tokens=out_tokens,
    )


def test_build_report_marks_overall_safety():
    runs = [_run()]
    verdicts = [aggregate_verdict("meal-001", [CheckResult("safety", True, False, "ok")])]
    report = build_report("mock-model", runs, verdicts)
    assert report["overall_safety_passed"] is True
    assert report["model"] == "mock-model"
    assert report["scenarios"][0]["scenario_id"] == "meal-001"
    # must be JSON-serializable
    json.dumps(report)


def test_render_markdown_contains_verdict_and_latency():
    runs = [_run(latency=2.5)]
    verdicts = [aggregate_verdict("meal-001", [CheckResult("safety", True, False, "ok")])]
    md = render_markdown(build_report("mock-model", runs, verdicts))
    assert "PASS" in md
    assert "mock-model" in md
    assert "2.5" in md
