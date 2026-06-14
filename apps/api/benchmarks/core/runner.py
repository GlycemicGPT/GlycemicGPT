"""Assemble the exact production prompt for a scenario's surface, call the
model through the real BaseAIClient, and capture output + latency + tokens.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from benchmarks.scenario import Scenario
from src.schemas.ai_response import AIMessage
from src.services.ai_client import BaseAIClient


@dataclass
class RunResult:
    scenario_id: str
    surface: str
    system_prompt: str
    user_prompt: str
    output: str
    model: str
    latency_s: float
    input_tokens: int
    output_tokens: int


def _build_prompt(scenario: Scenario) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) using the REAL production builders.

    Only meal_analysis is wired in Plan 1; other surfaces are added in Plan 2.
    """
    if scenario.surface == "meal_analysis":
        from src.schemas.meal_analysis import MealPeriodData
        from src.services.meal_analysis import SYSTEM_PROMPT, build_meal_prompt

        periods = [MealPeriodData.model_validate(p)
                   for p in scenario.input.get("meal_periods", [])]
        user_prompt = build_meal_prompt(
            periods,
            total_boluses=int(scenario.input.get("total_boluses", 0)),
            days=int(scenario.input.get("days", 7)),
            profile_summary=None,
        )
        return SYSTEM_PROMPT, user_prompt

    raise NotImplementedError(f"Surface not supported in Plan 1: {scenario.surface}")


async def run_scenario(scenario: Scenario, client: BaseAIClient) -> RunResult:
    system_prompt, user_prompt = _build_prompt(scenario)
    started = time.perf_counter()
    response = await client.generate(
        messages=[AIMessage(role="user", content=user_prompt)],
        system_prompt=system_prompt,
    )
    latency_s = time.perf_counter() - started
    return RunResult(
        scenario_id=scenario.id,
        surface=scenario.surface,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        output=response.content,
        model=response.model,
        latency_s=latency_s,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
