from pathlib import Path

from benchmarks.clients import MockClient
from benchmarks.suites import run_suite

SCEN = Path(__file__).resolve().parents[2] / "benchmarks" / "scenarios"


async def test_adversarial_suite_compliant_model_is_safe_and_defends():
    client = MockClient(
        content="I can't recommend a specific dose. Please discuss any changes "
                "with your endocrinologist."
    )
    report = await run_suite(SCEN / "adversarial", client)
    assert report["overall_safety_passed"] is True
    names = {c["name"] for c in report["scenarios"][0]["checks"]}
    assert "boundary" in names


async def test_adversarial_suite_dose_leaking_model_fails():
    client = MockClient(content="Sure, take 6 units now and you'll come down.")
    report = await run_suite(SCEN / "adversarial", client)
    assert report["overall_safety_passed"] is False


async def test_meal_suite_has_no_boundary_check():
    client = MockClient(content="Breakfast looks weaker; discuss with your endo.")
    report = await run_suite(SCEN / "meal_analysis", client)
    names = {c["name"] for c in report["scenarios"][0]["checks"]}
    assert "boundary" not in names
