"""Build a JSON-serializable report dict and render a human Markdown summary."""

from __future__ import annotations

from statistics import median
from typing import Any

from benchmarks.core.runner import RunResult
from benchmarks.core.verdict import ScenarioVerdict, suite_safety_passed


def build_report(
    model: str,
    runs: list[RunResult],
    verdicts: list[ScenarioVerdict],
) -> dict[str, Any]:
    by_id = {v.scenario_id: v for v in verdicts}
    latencies = [r.latency_s for r in runs] or [0.0]
    scenarios = []
    for run in runs:
        verdict = by_id.get(run.scenario_id)
        scenarios.append({
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
        })
    return {
        "model": model,
        "overall_safety_passed": suite_safety_passed(verdicts),
        "scenario_count": len(runs),
        "latency_p50_s": round(median(latencies), 3),
        "latency_max_s": round(max(latencies), 3),
        "total_output_tokens": sum(r.output_tokens for r in runs),
        "scenarios": scenarios,
    }


def render_markdown(report: dict[str, Any]) -> str:
    verdict = "PASS" if report["overall_safety_passed"] else "FAIL"
    lines = [
        f"# Benchmark report — {report['model']}",
        "",
        f"**Safety verdict: {verdict}**  ({report['scenario_count']} scenarios)",
        "",
        f"- Latency p50: {report['latency_p50_s']}s, max: {report['latency_max_s']}s",
        f"- Total output tokens: {report['total_output_tokens']}",
        "",
        "| Scenario | Surface | Safety | Failed critical | Latency (s) |",
        "|---|---|---|---|---|",
    ]
    for s in report["scenarios"]:
        mark = "✅" if s["safety_passed"] else "❌"
        failed = ", ".join(s["failed_critical"]) or "—"
        lines.append(
            f"| {s['scenario_id']} | {s['surface']} | {mark} | {failed} | {s['latency_s']} |"
        )
    lines += [
        "",
        "> Passing is NOT a medical-safety guarantee. See MEDICAL-DISCLAIMER.md.",
    ]
    return "\n".join(lines)
