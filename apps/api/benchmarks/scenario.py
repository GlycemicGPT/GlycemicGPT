"""Benchmark scenario schema and YAML loader.

A scenario is one labeled test case for one AI surface. Ground truth is
DERIVED data (computed from the input), so anonymized local data scores
self-consistently in later plans.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

Surface = Literal[
    "daily_brief",
    "meal_analysis",
    "correction",
    "chat",
    "chat_rag",
    "adversarial",
]

SafetyStatusName = Literal["APPROVED", "FLAGGED", "REJECTED"]


class GroundTruth(BaseModel):
    """Known/derived facts a deterministic scorer checks the output against."""

    worst_meal_period: str | None = None
    cited_numbers_must_match: list[float] = Field(default_factory=list)
    expected_safety_status: SafetyStatusName | None = None
    must_not_contain_specific_dose: bool = True


class Scenario(BaseModel):
    """One benchmark case."""

    id: str
    surface: Surface
    units: Literal["mg/dL", "mmol/L"] = "mg/dL"
    input: dict[str, Any] = Field(default_factory=dict)
    ground_truth: GroundTruth = Field(default_factory=GroundTruth)
    judge_rubric: str | None = None
    # Adversarial-only fields (unused until Plan 2's adversarial scorer)
    attack_type: str | None = None
    expected_behavior: str | None = None


def load_scenarios(directory: Path) -> list[Scenario]:
    """Load and parse every *.yaml scenario under a directory (recursive)."""
    scenarios: list[Scenario] = []
    for path in sorted(Path(directory).rglob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        scenarios.append(Scenario.model_validate(data))
    return scenarios
