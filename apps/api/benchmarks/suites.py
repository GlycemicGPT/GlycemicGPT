"""Run a directory of scenarios through the runner, the deterministic scorers,
the verdict aggregator, and the report builder.
"""

from __future__ import annotations

from pathlib import Path
from statistics import mean, median
from typing import Any

from benchmarks.core.report import build_report
from benchmarks.core.runner import run_scenario
from benchmarks.core.scorers import (
    score_boundary,
    score_dose_numbers,
    score_grounding,
    score_safety,
    score_units,
)
from benchmarks.core.verdict import aggregate_verdict
from benchmarks.scenario import load_scenarios
from src.services.ai_client import BaseAIClient


async def run_suite(
    scenario_dir: Path,
    client: BaseAIClient,
    judge_client: BaseAIClient | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    scenarios = load_scenarios(scenario_dir)
    runs = []
    verdicts = []
    judge_results: dict[str, Any] | None = {} if judge_client is not None else None
    model_name = "unknown"
    for scenario in scenarios:
        run = await run_scenario(scenario, client, max_tokens=max_tokens)
        model_name = run.model
        checks = [
            score_safety(run.output, scenario.ground_truth),
            score_dose_numbers(run.output),
            score_units(run.output, scenario.units),
            score_grounding(run.output, scenario.ground_truth.cited_numbers_must_match),
        ]
        if scenario.surface == "adversarial":
            checks.append(score_boundary(run.output, scenario.expected_behavior))
        runs.append(run)
        # Safety verdict is purely deterministic — judge plays NO role here.
        verdicts.append(aggregate_verdict(scenario.id, checks))

        if judge_client is not None and judge_results is not None:
            from benchmarks.core.judge import judge_output
            judge_results[scenario.id] = await judge_output(scenario, run.output, judge_client)

    return build_report(model_name, runs, verdicts, judge_results=judge_results)


async def run_suite_repeated(
    scenario_dir: Path,
    client: BaseAIClient,
    judge_client: BaseAIClient | None = None,
    max_tokens: int | None = None,
    repeat: int = 5,
) -> dict[str, Any]:
    """Run the suite `repeat` times and aggregate. A scenario is safe only if it
    was safe on EVERY run (a model that produces unsafe output even once is unsafe).
    The judge (if any) runs on the FIRST pass only, to bound cost."""
    passes: list[dict[str, Any]] = []
    for i in range(repeat):
        report = await run_suite(
            scenario_dir, client,
            judge_client=judge_client if i == 0 else None,
            max_tokens=max_tokens,
        )
        passes.append(report)
    return aggregate_repeated(passes, repeat)


def aggregate_repeated(passes: list[dict[str, Any]], repeat: int) -> dict[str, Any]:
    """Combine N single-pass report dicts into one aggregated report."""
    first = passes[0]
    model = first["model"]
    # Preserve scenario order from the first pass.
    scenario_ids = [s["scenario_id"] for s in first["scenarios"]]
    by_id_per_pass = [{s["scenario_id"]: s for s in p["scenarios"]} for p in passes]

    scenarios: list[dict[str, Any]] = []
    all_latencies: list[float] = []
    total_output_tokens = 0
    total_latency = 0.0
    for sid in scenario_ids:
        per_pass = [bp[sid] for bp in by_id_per_pass if sid in bp]
        n = len(per_pass)
        safe_runs = sum(1 for sp in per_pass if sp["safety_passed"])
        failed_critical = sorted({fc for sp in per_pass for fc in sp["failed_critical"]})
        out_toks = sum(sp["output_tokens"] for sp in per_pass)
        lat_sum = sum(sp["latency_s"] for sp in per_pass)
        all_latencies.extend(sp["latency_s"] for sp in per_pass)
        total_output_tokens += out_toks
        total_latency += lat_sum
        run_details = [
            {
                "run_index": i,
                "safe": sp["safety_passed"],
                "failed_critical": sp["failed_critical"],
                "output": sp.get("output", ""),
                "latency_s": sp["latency_s"],
                "output_tokens": sp["output_tokens"],
            }
            for i, sp in enumerate(per_pass)
        ]
        sd: dict[str, Any] = {
            "scenario_id": sid,
            "surface": per_pass[0]["surface"],
            "runs": n,
            "safe_runs": safe_runs,
            "pass_rate": round(safe_runs / n, 3) if n else None,
            "safety_passed": safe_runs == n,
            "failed_critical": failed_critical,
            "mean_latency_s": round(lat_sum / n, 3) if n else None,
            "tokens_per_second": round(out_toks / lat_sum, 1) if lat_sum > 0 else None,
            "output_tokens": out_toks,
            "cost_usd": per_pass[0].get("cost_usd"),
            "run_details": run_details,
        }
        # Quality, if the first pass had a judge:
        q = first["scenarios"][scenario_ids.index(sid)].get("quality_score")
        if q is not None:
            sd["quality_score"] = q
        scenarios.append(sd)

    overall = all(s["safety_passed"] for s in scenarios)
    known_costs = [s["cost_usd"] for s in scenarios if s["cost_usd"] is not None]
    quality_scores = [s["quality_score"] for s in scenarios if s.get("quality_score") is not None]
    report: dict[str, Any] = {
        "model": model,
        "overall_safety_passed": overall,
        "scenario_count": len(scenarios),
        "repeat": repeat,
        "latency_p50_s": round(median(all_latencies), 3) if all_latencies else 0.0,
        "latency_max_s": round(max(all_latencies), 3) if all_latencies else 0.0,
        "total_output_tokens": total_output_tokens,
        "tokens_per_second": round(total_output_tokens / total_latency, 1) if total_latency > 0 else None,
        "total_cost_usd": round(sum(known_costs), 6) if known_costs else None,
        "scenarios": scenarios,
    }
    if quality_scores:
        report["quality_mean"] = round(mean(quality_scores), 3)
    return report
