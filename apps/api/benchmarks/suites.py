"""Run a directory of scenarios through the runner, the deterministic scorers,
the verdict aggregator, and the report builder.
"""

from __future__ import annotations

from pathlib import Path
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


async def run_suite(scenario_dir: Path, client: BaseAIClient) -> dict[str, Any]:
    scenarios = load_scenarios(scenario_dir)
    runs = []
    verdicts = []
    model_name = "unknown"
    for scenario in scenarios:
        run = await run_scenario(scenario, client)
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
        verdicts.append(aggregate_verdict(scenario.id, checks))
    return build_report(model_name, runs, verdicts)
