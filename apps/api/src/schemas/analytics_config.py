"""Analytics configuration schemas.

DisplayLabel-based architecture: labels are first-class entities with
optional computation_role binding and optional pump_source assignment.
"""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

COMPUTATION_ROLES = frozenset(
    {
        "AUTO_CORRECTION",
        "FOOD",
        "FOOD_AND_CORRECTION",
        "CORRECTION",
        "OVERRIDE",
        "OTHER",
    }
)

DEFAULT_DISPLAY_LABELS: list[dict] = [
    {
        "id": "auto_corr",
        "label": "Auto Corr",
        "computation_role": "AUTO_CORRECTION",
        "pump_source": None,
        "sort_order": 0,
    },
    {
        "id": "meal",
        "label": "Meal",
        "computation_role": "FOOD",
        "pump_source": None,
        "sort_order": 1,
    },
    {
        "id": "meal_corr",
        "label": "Meal+Corr",
        "computation_role": "FOOD_AND_CORRECTION",
        "pump_source": None,
        "sort_order": 2,
    },
    {
        "id": "correction",
        "label": "Correction",
        "computation_role": "CORRECTION",
        "pump_source": None,
        "sort_order": 3,
    },
    {
        "id": "override",
        "label": "Override",
        "computation_role": "OVERRIDE",
        "pump_source": None,
        "sort_order": 4,
    },
    {
        "id": "other",
        "label": "Other",
        "computation_role": "OTHER",
        "pump_source": None,
        "sort_order": 5,
    },
]

# Legacy compat: dict form for mobile backward compatibility
DEFAULT_CATEGORY_LABELS: dict[str, str] = {
    item["computation_role"]: item["label"]
    for item in DEFAULT_DISPLAY_LABELS
    if item["computation_role"]
}

MAX_DISPLAY_LABELS = 20

_LABEL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


class DisplayLabel(BaseModel):
    """A user-owned display label for bolus categories."""

    model_config = {"extra": "forbid"}

    id: str = Field(..., max_length=32)
    label: str = Field(..., max_length=20)
    computation_role: str | None = Field(default=None)
    pump_source: str | None = Field(default=None, max_length=32)
    sort_order: int = Field(..., ge=0)

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not _LABEL_ID_RE.match(v):
            raise ValueError(f"Label id must match ^[a-z][a-z0-9_]*$ (got: {v!r}).")
        return v

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str) -> str:
        v = v.strip()
        if len(v) == 0:
            raise ValueError("Label text must not be blank.")
        if _HTML_TAG_RE.search(v):
            raise ValueError("Label text must not contain HTML tags.")
        if any(c in v for c in "\n\r\t"):
            raise ValueError("Label text must not contain control characters.")
        return v

    @field_validator("computation_role")
    @classmethod
    def validate_computation_role(cls, v: str | None) -> str | None:
        if v is not None and v not in COMPUTATION_ROLES:
            raise ValueError(
                f"computation_role must be one of {sorted(COMPUTATION_ROLES)} or null "
                f"(got: {v!r})."
            )
        return v


class AnalyticsConfigResponse(BaseModel):
    """Response schema for analytics configuration."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    day_boundary_hour: int
    display_labels: list[DisplayLabel] | None = None
    category_labels: dict[str, str] | None = None
    updated_at: datetime


class AnalyticsConfigUpdate(BaseModel):
    """Request schema for updating analytics configuration.

    All fields are optional -- only provided fields are updated.
    """

    model_config = {"extra": "forbid"}

    day_boundary_hour: int | None = Field(
        default=None,
        ge=0,
        le=23,
        description="Hour (0-23) in local time when the analytics day resets.",
    )

    display_labels: list[DisplayLabel] | None = Field(
        default=None,
        description="Complete array of display labels (full-replace semantics).",
    )

    @field_validator("display_labels")
    @classmethod
    def validate_display_labels(
        cls, v: list[DisplayLabel] | None
    ) -> list[DisplayLabel] | None:
        if v is None:
            return v
        if len(v) < 1:
            raise ValueError("At least one display label is required.")
        if len(v) > MAX_DISPLAY_LABELS:
            raise ValueError(
                f"At most {MAX_DISPLAY_LABELS} display labels allowed (got {len(v)})."
            )
        # Unique ids
        ids = [item.id for item in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Display label ids must be unique.")

        # Unique computation_roles (non-null only)
        roles = [item.computation_role for item in v if item.computation_role]
        if len(roles) != len(set(roles)):
            raise ValueError(
                "Each computation_role can be assigned to at most one label."
            )

        return v


class AnalyticsConfigDefaults(BaseModel):
    """Default analytics configuration values for reference."""

    day_boundary_hour: int = 0
    display_labels: list[dict] = Field(
        default_factory=lambda: [dict(d) for d in DEFAULT_DISPLAY_LABELS]
    )
    category_labels: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_CATEGORY_LABELS)
    )


def display_labels_to_category_labels(
    labels: list[dict | DisplayLabel] | None,
) -> dict[str, str]:
    """Convert display_labels array to legacy {role: label} dict.

    Used for mobile backward compatibility. Labels without a
    computation_role are excluded.
    """
    if not labels:
        return dict(DEFAULT_CATEGORY_LABELS)
    result = {}
    for item in labels:
        if isinstance(item, DisplayLabel):
            role = item.computation_role
            text = item.label
        else:
            role = item.get("computation_role")
            text = item.get("label", "")
        if role:
            result[role] = text
    return result
