from benchmarks.clients import MockClient
from benchmarks.core.judge import JudgeResult, judge_output
from benchmarks.scenario import Scenario


def _scenario():
    return Scenario.model_validate(
        {
            "id": "j-001",
            "surface": "meal_analysis",
            "units": "mg/dL",
            "input": {},
            "ground_truth": {},
            "judge_rubric": "Good answer flags breakfast.",
        }
    )


async def test_judge_parses_score_and_rationale():
    client = MockClient(
        content='{"score": 4, "rationale": "Flags breakfast, stays directional."}'
    )
    result = await judge_output(
        _scenario(), "Breakfast looks weak; discuss with your endo.", client
    )
    assert isinstance(result, JudgeResult)
    assert result.score == 4.0
    assert "breakfast" in result.rationale.lower()


async def test_judge_extracts_json_from_surrounding_text():
    client = MockClient(
        content='Here is my assessment: {"score": 5, "rationale": "excellent"} done.'
    )
    result = await judge_output(_scenario(), "answer", client)
    assert result.score == 5.0


async def test_judge_unparseable_returns_none_score():
    client = MockClient(content="I think it was pretty good honestly.")
    result = await judge_output(_scenario(), "answer", client)
    assert result.score is None
    assert result.raw  # keeps the raw text


async def test_judge_clamps_out_of_range_score():
    client = MockClient(content='{"score": 9, "rationale": "x"}')
    result = await judge_output(_scenario(), "answer", client)
    assert result.score == 5.0
