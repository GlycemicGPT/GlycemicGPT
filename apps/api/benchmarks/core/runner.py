"""Assemble the exact production prompt for a scenario's surface, call the
model through the real BaseAIClient, and capture output + latency + tokens.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from benchmarks.scenario import Scenario
from src.core.units import GlucoseUnit
from src.schemas.ai_response import AIMessage
from src.services.ai_client import BaseAIClient


def _scenario_unit(scenario: Scenario) -> GlucoseUnit:
    """Map a scenario's display unit to the production GlucoseUnit enum.

    Scenario glucose inputs are canonical mg/dL; ``units`` selects the DISPLAY
    unit the production prompt builders render in, so the harness exercises the
    exact prompt a user of that unit would see (an mmol/L scenario must not be
    silently rendered in mg/dL)."""
    return GlucoseUnit.MMOL if scenario.units == "mmol/L" else GlucoseUnit.MGDL


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


def _chat_system_prompt(context: str) -> str:
    """Build the chat-surface system prompt from the REAL web chat prefix."""
    from src.services.telegram_chat import _WEB_SYSTEM_PROMPT_PREFIX

    return (
        _WEB_SYSTEM_PROMPT_PREFIX + context
        if context
        else _WEB_SYSTEM_PROMPT_PREFIX.rstrip()
    )


def _build_prompt(scenario: Scenario) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) using the REAL production builders.

    Only meal_analysis is wired in Plan 1; other surfaces are added in Plan 2.
    """
    unit = _scenario_unit(scenario)

    if scenario.surface == "meal_analysis":
        from src.schemas.meal_analysis import MealPeriodData
        from src.services.meal_analysis import _build_system_prompt, build_meal_prompt

        periods = [
            MealPeriodData.model_validate(p)
            for p in scenario.input.get("meal_periods", [])
        ]
        user_prompt = build_meal_prompt(
            periods,
            total_boluses=int(scenario.input.get("total_boluses", 0)),
            days=int(scenario.input.get("days", 7)),
            profile_summary=None,
            unit=unit,
        )
        return _build_system_prompt(unit), user_prompt

    if scenario.surface == "adversarial":
        system_prompt = _chat_system_prompt(scenario.input.get("context", ""))
        user_prompt = str(scenario.input.get("message", ""))
        return system_prompt, user_prompt

    if scenario.surface == "daily_brief":
        from src.schemas.daily_brief import DailyBriefMetrics
        from src.services.daily_brief import _build_system_prompt, build_analysis_prompt

        metrics = DailyBriefMetrics.model_validate(scenario.input["metrics"])
        user_prompt = build_analysis_prompt(
            metrics, hours=int(scenario.input.get("hours", 24)), unit=unit
        )
        return _build_system_prompt(unit), user_prompt

    if scenario.surface == "correction":
        from src.schemas.correction_analysis import TimePeriodData
        from src.services.correction_analysis import (
            _build_system_prompt,
            build_correction_prompt,
        )

        time_periods = [
            TimePeriodData.model_validate(p)
            for p in scenario.input.get("time_periods", [])
        ]
        user_prompt = build_correction_prompt(
            time_periods,
            total_corrections=int(scenario.input.get("total_corrections", 0)),
            days=int(scenario.input.get("days", 14)),
            unit=unit,
        )
        return _build_system_prompt(unit), user_prompt

    if scenario.surface == "chat":
        system_prompt = _chat_system_prompt(scenario.input.get("context", ""))
        user_prompt = str(scenario.input.get("message", ""))
        return system_prompt, user_prompt

    if scenario.surface == "chat_rag":
        from types import SimpleNamespace

        from src.services.knowledge_retrieval import format_knowledge_for_prompt

        chunks = [
            SimpleNamespace(
                content=k.get("content", ""),
                trust_tier=k.get("trust_tier"),
                source_name=k.get("source"),
                source_type=None,
            )
            for k in scenario.input.get("knowledge", [])
        ]
        knowledge_block = format_knowledge_for_prompt(chunks) or ""
        base = _chat_system_prompt(scenario.input.get("context", ""))
        system_prompt = f"{base}\n\n{knowledge_block}" if knowledge_block else base
        user_prompt = str(scenario.input.get("message", ""))
        return system_prompt, user_prompt

    raise NotImplementedError(f"Surface not supported: {scenario.surface}")


async def run_scenario(
    scenario: Scenario,
    client: BaseAIClient,
    max_tokens: int | None = None,
) -> RunResult:
    system_prompt, user_prompt = _build_prompt(scenario)
    # Thinking models (Qwen3, DeepSeek-R1, ...) spend output tokens on internal
    # reasoning before the visible answer; the default budget can truncate them
    # to an empty response. `max_tokens` lets a caller raise the budget, mirroring
    # the app's per-user max_response_tokens setting (issue #554). None = the
    # client's own default.
    extra = {"max_tokens": max_tokens} if max_tokens is not None else {}
    started = time.perf_counter()
    response = await client.generate(
        messages=[AIMessage(role="user", content=user_prompt)],
        system_prompt=system_prompt,
        **extra,
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
