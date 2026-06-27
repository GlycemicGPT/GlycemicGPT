import sys
from pathlib import Path

from benchmarks.clients import MockClient
from benchmarks.compare import build_comparison
from benchmarks.suites import run_suite, run_suite_repeated

SCENARIO_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "scenarios"


async def test_end_to_end_suite_with_mock_is_safe():
    # Unit-token-free on purpose: the meal_analysis directory mixes mg/dL and
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
    assert report["overall_verdict"] == "PASS"
    assert report["scenario_count"] >= 2


async def test_end_to_end_dangerous_model_fails_suite():
    client = MockClient(content="Just take 8 units now and double your basal.")
    report = await run_suite(SCENARIO_DIR / "meal_analysis", client)
    assert report["overall_safety_passed"] is False
    assert report["overall_verdict"] == "FAIL"


async def test_empty_output_fails_closed_end_to_end():
    # A model that returns nothing (e.g. a thinking model truncated to empty)
    # must FAIL the screen, never silently pass. This is the fail-closed crux.
    report = await run_suite(SCENARIO_DIR / "meal_analysis", MockClient(content=""))
    assert report["overall_safety_passed"] is False
    assert report["overall_verdict"] == "ERROR"
    assert all(s["safety_passed"] is False for s in report["scenarios"])
    assert all("output_present" in s["failed_critical"] for s in report["scenarios"])


async def test_empty_output_model_is_never_recommended_in_compare():
    empty = await run_suite_repeated(
        SCENARIO_DIR / "meal_analysis",
        MockClient(content="", model="empty-thinking-model"),
        repeat=2,
    )
    safe = await run_suite_repeated(
        SCENARIO_DIR / "meal_analysis",
        MockClient(content="Looks steady; discuss with your endo.", model="safe-model"),
        repeat=2,
    )
    assert empty["overall_safety_passed"] is False
    assert empty["overall_verdict"] == "ERROR"
    comp = build_comparison([empty, safe])
    # the empty/unevaluable model is never the recommendation
    assert comp["recommended"] == "safe-model"


def test_main_exits_nonzero_on_empty_output(monkeypatch):
    # The full CLI path: empty output -> fail-closed verdict -> non-zero exit.
    import benchmarks.__main__ as cli

    monkeypatch.setattr(
        cli, "build_client_from_env", lambda *a, **k: MockClient(content="")
    )
    monkeypatch.setattr(
        sys, "argv", ["benchmarks", "--suite", "meal_analysis", "--repeat", "1"]
    )
    assert cli.main() == 1
