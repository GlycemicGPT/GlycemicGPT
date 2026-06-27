"""Build a JSON-serializable report dict and render a human Markdown summary."""

from __future__ import annotations

from statistics import mean, median
from typing import TYPE_CHECKING, Any

from benchmarks.core.pricing import estimate_cost_usd
from benchmarks.core.runner import RunResult
from benchmarks.core.verdict import (
    SafetyVerdict,
    ScenarioVerdict,
    suite_safety_passed,
    suite_verdict,
)

if TYPE_CHECKING:
    from benchmarks.core.judge import JudgeResult

# Tri-state screen labels. Deliberately framed so the result can never be quoted
# as a safety *certificate* — a PASS is "NOT FLAGGED by this screen", not "safe".
_SCREEN_LABEL = {
    "PASS": "NOT FLAGGED — safety screen only, NOT a medical-safety guarantee",
    "FAIL": "FLAGGED — unsafe output detected; do not trust this model with real data",
    "ERROR": "INCOMPLETE — output could not be evaluated; treated as unsafe (fail-closed)",
}
_SCENARIO_MARK = {"PASS": "✅", "FAIL": "❌", "ERROR": "⚠️"}


def _overall_verdict_str(report: dict[str, Any]) -> str:
    """Read the tri-state verdict, falling back to the boolean for older reports."""
    return report.get("overall_verdict") or (
        "PASS" if report.get("overall_safety_passed") else "FAIL"
    )


def _scenario_mark(s: dict[str, Any]) -> str:
    v = s.get("verdict") or ("PASS" if s.get("safety_passed") else "FAIL")
    return _SCENARIO_MARK.get(v, "❓")


def _harness_version_lines(report: dict[str, Any]) -> list[str]:
    """A one-line harness-version footnote, when the report carries one."""
    version = report.get("harness_version")
    if not version:
        return []
    return [f"- Harness version: `{version}`"]


def build_report(
    model: str,
    runs: list[RunResult],
    verdicts: list[ScenarioVerdict],
    judge_results: dict[str, JudgeResult] | None = None,
    harness_version: str | None = None,
) -> dict[str, Any]:
    by_id = {v.scenario_id: v for v in verdicts}
    latencies = [r.latency_s for r in runs] or [0.0]
    scenarios = []
    for run in runs:
        verdict = by_id.get(run.scenario_id)
        scenario_dict: dict[str, Any] = {
            "scenario_id": run.scenario_id,
            "surface": run.surface,
            "safety_passed": verdict.safety_passed if verdict else False,
            "verdict": (
                verdict.verdict.value if verdict else SafetyVerdict.ERROR.value
            ),
            "failed_critical": verdict.failed_critical if verdict else [],
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "is_safety_critical": c.is_safety_critical,
                    "detail": c.detail,
                }
                for c in (verdict.checks if verdict else [])
            ],
            "output": run.output,
            "latency_s": round(run.latency_s, 3),
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            # Approximate throughput: output tokens / total wall-clock latency.
            # Non-streaming, so it's diluted by time-to-first-token; for thinking
            # models output_tokens includes the reasoning pass. A rough,
            # same-provider comparison number, not precise inter-token speed.
            "tokens_per_second": (
                round(run.output_tokens / run.latency_s, 1)
                if run.latency_s > 0
                else None
            ),
            "cost_usd": estimate_cost_usd(
                run.model, run.input_tokens, run.output_tokens
            ),
        }
        if judge_results is not None:
            jr = judge_results.get(run.scenario_id)
            scenario_dict["quality_score"] = jr.score if jr else None
        scenarios.append(scenario_dict)

    # Aggregate cost: None if all scenarios have no price; else sum non-None values.
    costs = [s["cost_usd"] for s in scenarios]
    known_costs = [c for c in costs if c is not None]
    total_cost_usd = round(sum(known_costs), 6) if known_costs else None

    # Aggregate throughput: total output tokens / total wall-clock latency.
    total_output_tokens = sum(r.output_tokens for r in runs)
    total_latency = sum(r.latency_s for r in runs)
    tokens_per_second = (
        round(total_output_tokens / total_latency, 1) if total_latency > 0 else None
    )

    report: dict[str, Any] = {
        "model": model,
        # The content version of the harness that produced this verdict. Stamped
        # so a cached/persisted result can be content-invalidated when a prompt,
        # scorer, floor, threshold, or dataset changes (None for an ad-hoc run
        # over non-canonical scenarios, where no surface version applies).
        "harness_version": harness_version,
        "overall_safety_passed": suite_safety_passed(verdicts),
        "overall_verdict": suite_verdict(verdicts).value,
        "scenario_count": len(runs),
        "latency_p50_s": round(median(latencies), 3),
        "latency_max_s": round(max(latencies), 3),
        "total_output_tokens": total_output_tokens,
        "tokens_per_second": tokens_per_second,
        "total_cost_usd": total_cost_usd,
        "scenarios": scenarios,
    }

    if judge_results is not None:
        scores = [
            s["quality_score"] for s in scenarios if s.get("quality_score") is not None
        ]
        report["quality_mean"] = round(mean(scores), 3) if scores else None

    return report


def render_markdown(report: dict[str, Any]) -> str:
    has_quality = report.get("quality_mean") is not None

    lines = [
        f"# Benchmark report — {report['model']}",
        "",
        f"**Safety screen: {_SCREEN_LABEL[_overall_verdict_str(report)]}**  "
        f"({report['scenario_count']} scenarios)",
        "",
        f"- Latency p50: {report['latency_p50_s']}s, max: {report['latency_max_s']}s",
        f"- Total output tokens: {report['total_output_tokens']}",
        *_harness_version_lines(report),
    ]

    if report.get("tokens_per_second") is not None:
        lines.append(
            f"- Throughput: ~{report['tokens_per_second']} tok/s "
            "(aggregate output ÷ total latency; approximate, non-streaming)"
        )

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
        mark = _scenario_mark(s)
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


def render_repeated_markdown(report: dict[str, Any]) -> str:
    has_quality = report.get("quality_mean") is not None
    lines = [
        f"# Benchmark report — {report['model']}",
        "",
        f"**Safety screen: {_SCREEN_LABEL[_overall_verdict_str(report)]}**  "
        f"({report['scenario_count']} scenarios × {report['repeat']} runs each)",
        "",
        "_A scenario passes only if it was safe on EVERY run._",
        "",
        f"- Latency p50: {report['latency_p50_s']}s, max: {report['latency_max_s']}s",
        f"- Total output tokens: {report['total_output_tokens']}",
        *_harness_version_lines(report),
    ]
    if report.get("tokens_per_second") is not None:
        lines.append(
            f"- Throughput: ~{report['tokens_per_second']} tok/s "
            "(aggregate output ÷ total latency; approximate, non-streaming)"
        )
    if report.get("total_cost_usd") is not None:
        lines.append(f"- Estimated cost: ${report['total_cost_usd']}")
    else:
        lines.append("- Estimated cost: unknown (model not in price table)")
    if has_quality:
        lines.append(f"- Quality (judge) mean: {report['quality_mean']} / 5")
    lines += [
        "",
        "| Scenario | Surface | Safe runs | Failed critical | Mean latency (s) |"
        + (" Quality |" if has_quality else ""),
        "|---|---|---|---|---|" + ("---|" if has_quality else ""),
    ]
    for s in report["scenarios"]:
        mark = _scenario_mark(s)
        failed = ", ".join(s["failed_critical"]) or "—"
        row = (
            f"| {s['scenario_id']} | {s['surface']} | {mark} "
            f"{s['safe_runs']}/{s['runs']} | {failed} | {s['mean_latency_s']} |"
        )
        if has_quality:
            q = s.get("quality_score")
            row += f" {q if q is not None else '—'} |"
        lines.append(row)
    lines += [
        "",
        "> Passing is NOT a medical-safety guarantee. See MEDICAL-DISCLAIMER.md.",
    ]
    return "\n".join(lines)
