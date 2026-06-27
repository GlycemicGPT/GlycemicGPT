"""Benchmark scenario schema and YAML loader.

A scenario is one labeled test case for one AI surface. Ground truth is
DERIVED data (computed from the input), so anonymized local data scores
self-consistently in later plans.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from src.core.treatment_safety.models import MAX_GLUCOSE_MGDL, MIN_GLUCOSE_MGDL

# Structured input fields that carry an ABSOLUTE glucose READING (not a delta or
# a rate). These must be canonical mg/dL inside the platform-wide 20-500 bound,
# so a fixture cannot silently encode mmol/L (e.g. avg_peak_glucose: 7.2) or an
# out-of-range value and benchmark the model against invalid medical data.
# Deltas/rates (avg_glucose_drop, avg_observed_isf) are deliberately excluded —
# a small glucose drop is valid and the 20-500 reading bound does not apply.
_GLUCOSE_READING_FIELDS = frozenset(
    {"avg_peak_glucose", "avg_2hr_glucose", "average_glucose"}
)

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


def _validate_glucose_inputs(input_data: Any) -> None:
    """Reject any absolute glucose-reading input outside the 20-500 mg/dL bound.

    Walks the (nested) structured input so a bad value at any depth — inside
    ``meal_periods``, ``metrics``, ``time_periods`` — is caught at load. The
    caller wraps a raise with the offending file path."""

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    key in _GLUCOSE_READING_FIELDS
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and not MIN_GLUCOSE_MGDL <= value <= MAX_GLUCOSE_MGDL
                ):
                    raise ValueError(
                        f"glucose input {key}={value} is outside the canonical "
                        f"{MIN_GLUCOSE_MGDL}-{MAX_GLUCOSE_MGDL} mg/dL range "
                        "(scenario glucose inputs must be canonical mg/dL; "
                        "mmol/L is a display unit only)"
                    )
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(input_data)


def load_scenarios(directory: Path) -> list[Scenario]:
    """Load and parse every *.yaml scenario under a directory (recursive).

    A malformed YAML file, a schema-invalid scenario, an out-of-range glucose
    input, or a DUPLICATE scenario id aborts the load with the offending file
    path, so a broken fixture is immediately actionable instead of failing
    anonymously. Duplicate ids are rejected because verdicts are keyed by id
    downstream — a collision would otherwise let one scenario's result silently
    overwrite another's and mask an unsafe scenario (a fail-open)."""
    scenarios: list[Scenario] = []
    seen_ids: dict[str, Path] = {}
    for path in sorted(Path(directory).rglob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
            scenario = Scenario.model_validate(data)
            _validate_glucose_inputs(scenario.input)
            if scenario.id in seen_ids:
                raise ValueError(
                    f"duplicate scenario id {scenario.id!r} "
                    f"(already used by {seen_ids[scenario.id]})"
                )
        except (yaml.YAMLError, ValidationError, ValueError) as exc:
            raise ValueError(f"failed to load scenario {path}: {exc}") from exc
        seen_ids[scenario.id] = path
        scenarios.append(scenario)
    return scenarios
