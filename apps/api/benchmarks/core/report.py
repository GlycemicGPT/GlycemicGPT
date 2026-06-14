"""Build a JSON-serializable report dict and render a human Markdown summary."""

from __future__ import annotations

from statistics import mean, median
from typing import TYPE_CHECKING, Any

from benchmarks.core.pricing import estimate_cost_usd
from benchmarks.core.runner import RunResult
from benchmarks.core.verdict import ScenarioVerdict, suite_safety_passed

if TYPE_CHECKING:
    from benchmarks.core.judge import JudgeResult


def build_report(
    model: str,
    runs: list[RunResult],
    verdicts: list[ScenarioVerdict],
    judge_results: dict[str, JudgeResult] | None = None,
) -> dict[str, Any]:
    by_id = {v.scenario_id: v for v in verdicts}
    latencies = [r.latency_s for r in runs] or [0.0]
    scenarios = []
    for run in runs:
        verdict = by_id.get(run.scenario_id)
        scenario_dict: dict[str, Any] = {
            "scenario_id": run.scenario_id,
            "surface": run.surface,
            "safety_passed": verdict.safety_passed if verdict else None,
            "failed_critical": verdict.failed_critical if verdict else [],
            "checks": [
                {"name": c.name, "passed": c.passed,
                 "is_safety_critical": c.is_safety_critical, "detail": c.detail}
                for c in (verdict.checks if verdict else [])
            ],
            "latency_s": round(run.latency_s, 3),
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "cost_usd": estimate_cost_usd(run.model, run.input_tokens, run.output_tokens),
        }
        if judge_results is not None:
            jr = judge_results.get(run.scenario_id)
            scenario_dict["quality_score"] = jr.score if jr else None
        scenarios.append(scenario_dict)

    # Aggregate cost: None if all scenarios have no price; else sum non-None values.
    costs = [s["cost_usd"] for s in scenarios]
    known_costs = [c for c in costs if c is not None]
    total_cost_usd = round(sum(known_costs), 6) if known_costs else None

    report: dict[str, Any] = {
        "model": model,
        "overall_safety_passed": suite_safety_passed(verdicts),
        "scenario_count": len(runs),
        "latency_p50_s": round(median(latencies), 3),
        "latency_max_s": round(max(latencies), 3),
        "total_output_tokens": sum(r.output_tokens for r in runs),
        "total_cost_usd": total_cost_usd,
        "scenarios": scenarios,
    }

    if judge_results is not None:
        scores = [s["quality_score"] for s in scenarios if s.get("quality_score") is not None]
        report["quality_mean"] = round(mean(scores), 3) if scores else None

    return report


def render_markdown(report: dict[str, Any]) -> str:
    verdict = "PASS" if report["overall_safety_passed"] else "FAIL"
    has_quality = report.get("quality_mean") is not None

    lines = [
        f"# Benchmark report — {report['model']}",
        "",
        f"**Safety verdict: {verdict}**  ({report['scenario_count']} scenarios)",
        "",
        f"- Latency p50: {report['latency_p50_s']}s, max: {report['latency_max_s']}s",
        f"- Total output tokens: {report['total_output_tokens']}",
    ]

    if report.get("total_cost_usd") is not None:
        lines.append(f"- Estimated cost: ${report['total_cost_usd']}")
    else:
        lines.append("- Estimated cost: unknown (model not in price table)")

    if has_quality:
        lines.append(f"- Quality (judge) mean: {report['quality_mean']} / 5")

    lines += [
        "",
        "| Scenario | Surface | Safety | Failed critical | Latency (s) |"
        + (" Quality |" if has_quality else ""),
        "|---|---|---|---|---|" + ("---|" if has_quality else ""),
    ]

    for s in report["scenarios"]:
        mark = "✅" if s["safety_passed"] else "❌"
        failed = ", ".join(s["failed_critical"]) or "—"
        row = f"| {s['scenario_id']} | {s['surface']} | {mark} | {failed} | {s['latency_s']} |"
        if has_quality:
            q = s.get("quality_score")
            row += f" {q if q is not None else '—'} |"
        lines.append(row)

    lines += [
        "",
        "> Passing is NOT a medical-safety guarantee. See MEDICAL-DISCLAIMER.md.",
    ]
    return "\n".join(lines)
