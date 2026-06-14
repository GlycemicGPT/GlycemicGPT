from pathlib import Path

from benchmarks.clients import MockClient
from benchmarks.suites import run_suite

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "scenarios"


async def test_end_to_end_suite_with_mock_is_safe():
    client = MockClient(
        content="Your breakfast peaks average 187 mg/dL and 2hr is 164 mg/dL — "
                "the response looks weaker than other meals. Discuss with your endo."
    )
    report = await run_suite(SCENARIO_DIR / "meal_analysis", client)
    assert report["overall_safety_passed"] is True
    assert report["scenario_count"] >= 2


async def test_end_to_end_dangerous_model_fails_suite():
    client = MockClient(content="Just take 8 units now and double your basal.")
    report = await run_suite(SCENARIO_DIR / "meal_analysis", client)
    assert report["overall_safety_passed"] is False
