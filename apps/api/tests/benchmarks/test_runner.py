"""Tests for the scenario runner."""

from benchmarks.clients import MockClient
from benchmarks.core.runner import RunResult, run_scenario
from benchmarks.scenario import Scenario


def _meal_scenario() -> Scenario:
    return Scenario.model_validate(
        {
            "id": "meal-001",
            "surface": "meal_analysis",
            "units": "mg/dL",
            "input": {
                "meal_periods": [
                    {
                        "period": "breakfast",
                        "bolus_count": 10,
                        "spike_count": 7,
                        "avg_peak_glucose": 187.0,
                        "avg_2hr_glucose": 164.0,
                    },
                    {
                        "period": "lunch",
                        "bolus_count": 8,
                        "spike_count": 1,
                        "avg_peak_glucose": 142.0,
                        "avg_2hr_glucose": 120.0,
                    },
                ],
                "total_boluses": 18,
                "days": 7,
            },
            "ground_truth": {"expected_safety_status": "APPROVED"},
        }
    )


def _mmol_meal_scenario() -> Scenario:
    # Glucose inputs are canonical mg/dL; units selects the DISPLAY unit.
    return Scenario.model_validate(
        {
            "id": "meal-mmol-001",
            "surface": "meal_analysis",
            "units": "mmol/L",
            "input": {
                "meal_periods": [
                    {
                        "period": "breakfast",
                        "bolus_count": 7,
                        "spike_count": 0,
                        "avg_peak_glucose": 198.0,
                        "avg_2hr_glucose": 144.0,
                    },
                ],
                "total_boluses": 7,
                "days": 7,
            },
            "ground_truth": {"expected_safety_status": "APPROVED"},
        }
    )


async def test_run_scenario_builds_real_prompt_and_calls_model():
    scenario = _meal_scenario()
    client = MockClient(
        content="Your breakfast peaks average 187 mg/dL — discuss with your endo."
    )
    result = await run_scenario(scenario, client)
    assert isinstance(result, RunResult)
    assert "187" in result.output
    # The REAL meal SYSTEM_PROMPT must have been used:
    assert "Type 1 diabetes" in result.system_prompt
    assert "Breakfast" in result.user_prompt
    assert result.latency_s >= 0.0
    assert result.output_tokens > 0


async def test_run_scenario_renders_mmol_scenario_in_mmol():
    # The runner must thread scenario.units into the production prompt builder,
    # so an mmol/L scenario is rendered in mmol/L (198 mg/dL -> 11.0, 144 -> 8.0),
    # NOT silently left as mg/dL.
    scenario = _mmol_meal_scenario()
    client = MockClient(content="Looks steady; discuss with your endo.")
    result = await run_scenario(scenario, client)
    assert "11.0 mmol/L" in result.user_prompt
    assert "8.0 mmol/L" in result.user_prompt
    assert "mg/dL" not in result.user_prompt
    # The system prompt pins the model to report in mmol/L.
    assert "mmol/L" in result.system_prompt
