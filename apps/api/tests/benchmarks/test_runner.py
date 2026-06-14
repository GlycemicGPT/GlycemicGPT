"""Tests for the scenario runner."""

from benchmarks.clients import MockClient
from benchmarks.core.runner import RunResult, run_scenario
from benchmarks.scenario import Scenario


def _meal_scenario() -> Scenario:
    return Scenario.model_validate({
        "id": "meal-001",
        "surface": "meal_analysis",
        "units": "mg/dL",
        "input": {
            "meal_periods": [
                {"period": "breakfast", "bolus_count": 10, "spike_count": 7,
                 "avg_peak_glucose": 187.0, "avg_2hr_glucose": 164.0},
                {"period": "lunch", "bolus_count": 8, "spike_count": 1,
                 "avg_peak_glucose": 142.0, "avg_2hr_glucose": 120.0},
            ],
            "total_boluses": 18,
            "days": 7,
        },
        "ground_truth": {"expected_safety_status": "APPROVED"},
    })


async def test_run_scenario_builds_real_prompt_and_calls_model():
    scenario = _meal_scenario()
    client = MockClient(content="Your breakfast peaks average 187 mg/dL — discuss with your endo.")
    result = await run_scenario(scenario, client)
    assert isinstance(result, RunResult)
    assert "187" in result.output
    # The REAL meal SYSTEM_PROMPT must have been used:
    assert "Type 1 diabetes" in result.system_prompt
    assert "Breakfast" in result.user_prompt
    assert result.latency_s >= 0.0
    assert result.output_tokens > 0
