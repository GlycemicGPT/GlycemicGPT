from pathlib import Path

import pytest

from benchmarks.clients import MockClient
from benchmarks.suites import aggregate_repeated, run_suite_repeated
from src.models.ai_provider import AIProviderType
from src.schemas.ai_response import AIResponse, AIUsage
from src.services.ai_client import BaseAIClient

SCEN = Path(__file__).resolve().parents[2] / "benchmarks" / "scenarios"


class _FlakyClient(BaseAIClient):
    """Unsafe (leaks a dose) on the first call, safe afterwards."""

    def __init__(self):
        super().__init__(
            api_key="x", model="flaky", provider_type=AIProviderType.OPENAI_COMPATIBLE
        )
        self.calls = 0

    async def generate(self, messages, system_prompt=None, max_tokens=1024):
        self.calls += 1
        text = (
            "Just add 4 units now."
            if self.calls == 1
            else "Breakfast looks weaker; discuss with your endo."
        )
        return AIResponse(
            content=text,
            model=self.model,
            provider=AIProviderType.OPENAI_COMPATIBLE,
            usage=AIUsage(input_tokens=10, output_tokens=8),
        )


async def test_safe_model_passes_all_runs():
    report = await run_suite_repeated(
        SCEN / "chat",
        MockClient(content="Discuss your targets with your endocrinologist."),
        repeat=5,
    )
    assert report["repeat"] == 5
    s = report["scenarios"][0]
    assert s["runs"] == 5 and s["safe_runs"] == 5 and s["safety_passed"] is True
    assert s["pass_rate"] == 1.0
    assert len(s["run_details"]) == 5
    # output captured for study:
    assert s["run_details"][0]["output"]


async def test_one_unsafe_run_fails_the_scenario():
    # chat suite has 1 scenario; flaky client is unsafe on call #1 only.
    report = await run_suite_repeated(SCEN / "chat", _FlakyClient(), repeat=5)
    s = report["scenarios"][0]
    assert s["runs"] == 5
    assert s["safe_runs"] == 4  # one unsafe run
    assert s["safety_passed"] is False  # not ALL safe -> scenario unsafe
    assert s["pass_rate"] == 0.8
    assert "dose_numbers" in s["failed_critical"]
    assert report["overall_safety_passed"] is False


def test_aggregate_repeated_unions_failures():
    # two passes of a one-scenario report: pass A safe, pass B failed on units.
    def pass_report(safe, failed):
        return {
            "model": "m",
            "scenarios": [
                {
                    "scenario_id": "x",
                    "surface": "meal_analysis",
                    "safety_passed": safe,
                    "failed_critical": failed,
                    "latency_s": 1.0,
                    "output_tokens": 10,
                    "cost_usd": None,
                    "output": "txt",
                }
            ],
        }

    agg = aggregate_repeated(
        [pass_report(True, []), pass_report(False, ["units"])], repeat=2
    )
    s = agg["scenarios"][0]
    assert s["safe_runs"] == 1 and s["runs"] == 2 and s["safety_passed"] is False
    assert s["failed_critical"] == ["units"]
    assert agg["overall_safety_passed"] is False


def test_repeated_genuine_fail_dominates_eval_error():
    # A scenario unsafe on run 1 (real dose) and unevaluable on run 2 (empty
    # output) must roll up to FAIL ("unsafe"), not ERROR ("couldn't evaluate").
    def pass_report(failed):
        return {
            "model": "m",
            "scenarios": [
                {
                    "scenario_id": "x",
                    "surface": "meal_analysis",
                    "safety_passed": not failed,
                    "failed_critical": failed,
                    "latency_s": 1.0,
                    "output_tokens": 10,
                    "cost_usd": None,
                    "output": "t",
                }
            ],
        }

    agg = aggregate_repeated(
        [pass_report(["dose_numbers"]), pass_report(["output_present"])], repeat=2
    )
    s = agg["scenarios"][0]
    assert s["safety_passed"] is False
    assert s["verdict"] == "FAIL"
    assert agg["overall_verdict"] == "FAIL"


async def test_repeat_zero_is_rejected():
    with pytest.raises(ValueError, match="repeat"):
        await run_suite_repeated(SCEN / "chat", MockClient(content="x"), repeat=0)


def test_aggregate_repeated_empty_pass_list_is_rejected():
    with pytest.raises(ValueError, match="at least one pass"):
        aggregate_repeated([], repeat=5)
