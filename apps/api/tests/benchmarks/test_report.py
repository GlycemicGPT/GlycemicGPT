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


def test_report_cost_when_model_priced(monkeypatch):
    from benchmarks.core import pricing
    monkeypatch.setitem(pricing.PRICE_TABLE, "mock-model", (0.001, 0.002))
    runs = [_run()]  # input_tokens=100, output_tokens=40, model="mock-model"
    verdicts = [aggregate_verdict("meal-001", [CheckResult("safety", True, False, "ok")])]
    report = build_report("mock-model", runs, verdicts)
    # 100/1000*0.001 + 40/1000*0.002 = 0.0001 + 0.00008 = 0.00018
    assert report["total_cost_usd"] == 0.00018
    assert report["scenarios"][0]["cost_usd"] == 0.00018
    assert "$" in render_markdown(report)


def test_report_cost_unknown_model_is_none():
    runs = [_run()]
    verdicts = [aggregate_verdict("meal-001", [CheckResult("safety", True, False, "ok")])]
    report = build_report("mock-model", runs, verdicts)
    assert report["total_cost_usd"] is None
    assert "unknown" in render_markdown(report).lower()


def test_report_includes_quality_when_judge_results_present():
    from benchmarks.core.judge import JudgeResult
    runs = [_run()]
    verdicts = [aggregate_verdict("meal-001", [CheckResult("safety", True, False, "ok")])]
    judge = {"meal-001": JudgeResult(score=4.0, rationale="good", raw="{}")}
    report = build_report("mock-model", runs, verdicts, judge_results=judge)
    assert report["quality_mean"] == 4.0
    assert report["scenarios"][0]["quality_score"] == 4.0
    md = render_markdown(report)
    assert "Quality" in md


def test_report_includes_tokens_per_second():
    # _run(): output_tokens=40, latency_s=1.2 -> 40/1.2 = 33.3 tok/s
    runs = [_run()]
    verdicts = [aggregate_verdict("meal-001", [CheckResult("safety", True, False, "ok")])]
    report = build_report("mock-model", runs, verdicts)
    assert report["tokens_per_second"] == 33.3
    assert report["scenarios"][0]["tokens_per_second"] == 33.3
    assert "tok/s" in render_markdown(report)


def test_tokens_per_second_handles_zero_latency():
    runs = [RunResult("s", "meal_analysis", "sys", "usr", "out", "m",
                      latency_s=0.0, input_tokens=10, output_tokens=5)]
    verdicts = [aggregate_verdict("s", [CheckResult("safety", True, False, "ok")])]
    report = build_report("m", runs, verdicts)
    assert report["tokens_per_second"] is None
    assert report["scenarios"][0]["tokens_per_second"] is None
