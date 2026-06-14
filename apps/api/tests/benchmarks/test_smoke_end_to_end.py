from pathlib import Path

from benchmarks.clients import MockClient
from benchmarks.suites import run_suite

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "scenarios"


async def test_end_to_end_suite_with_mock_is_safe():
    # Unit-token-free on purpose: the meal_analysis directory now mixes mg/dL and
    # mmol/L scenarios, and a single fixed mock can't carry a unit token that is
    # correct for both. The numbers (187/164) keep grounding exercised for the
    # mg/dL scenarios; a stray "mg/dL" token here would (correctly) trip the unit
    # scorer on the mmol/L scenario.
    client = MockClient(
        content="Your breakfast peaks average 187 and 2hr is 164 — "
                "the response looks weaker than other meals. Discuss with your endo."
    )
    report = await run_suite(SCENARIO_DIR / "meal_analysis", client)
    assert report["overall_safety_passed"] is True
    assert report["scenario_count"] >= 2


async def test_end_to_end_dangerous_model_fails_suite():
    client = MockClient(content="Just take 8 units now and double your basal.")
    report = await run_suite(SCENARIO_DIR / "meal_analysis", client)
    assert report["overall_safety_passed"] is False
