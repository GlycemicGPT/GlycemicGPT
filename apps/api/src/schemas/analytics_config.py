"""Analytics configuration schemas."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

VALID_CATEGORY_KEYS = frozenset(
    {
        "AUTO_CORRECTION",
        "FOOD",
        "FOOD_AND_CORRECTION",
        "CORRECTION",
        "OVERRIDE",
        "AI_SUGGESTED",
        "OTHER",
    }
)

DEFAULT_CATEGORY_LABELS: dict[str, str] = {
    "AUTO_CORRECTION": "Auto Corr",
    "FOOD": "Meal",
    "FOOD_AND_CORRECTION": "Meal+Corr",
    "CORRECTION": "Correction",
    "OVERRIDE": "Override",
    "AI_SUGGESTED": "AI Suggested",
    "OTHER": "Other",
}


_CUSTOM_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

MAX_CUSTOM_CATEGORIES = 10


class CustomCategoryItem(BaseModel):
    """A user-defined bolus category (future feature)."""

    model_config = {"extra": "forbid"}

    key: str = Field(..., max_length=32)
    display_name: str = Field(..., max_length=20)

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        if not _CUSTOM_KEY_RE.match(v):
            raise ValueError(
                f"Custom category key must match ^[A-Z][A-Z0-9_]*$ (got: {v!r})."
            )
        if v in VALID_CATEGORY_KEYS:
            raise ValueError(
                f"Custom category key must not overlap with built-in keys (got: {v!r})."
            )
        return v

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str) -> str:
        if len(v.strip()) == 0:
            raise ValueError("display_name must not be blank.")
        return v


class AnalyticsConfigResponse(BaseModel):
    """Response schema for analytics configuration."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    day_boundary_hour: int
    category_labels: dict[str, str] | None = None
    custom_categories: list[CustomCategoryItem] | None = None
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

    category_labels: dict[str, str] | None = Field(
        default=None,
        description="Custom display labels for bolus categories. "
        "Keys must be valid BolusCategory names, values max 20 chars.",
    )

    custom_categories: list[CustomCategoryItem] | None = Field(
        default=None,
        description="User-defined custom bolus categories (future feature). "
        "Max 10 items. Keys must not overlap with built-in categories.",
    )

    @field_validator("category_labels")
    @classmethod
    def validate_category_labels(
        cls, v: dict[str, str] | None
    ) -> dict[str, str] | None:
        if v is None:
            return v
        invalid_keys = set(v.keys()) - VALID_CATEGORY_KEYS
        if invalid_keys:
            raise ValueError(
                f"Invalid category keys: {sorted(invalid_keys)}. "
                f"Valid keys: {sorted(VALID_CATEGORY_KEYS)}"
            )
        for key, label in v.items():
            if not isinstance(label, str) or len(label) > 20:
                raise ValueError(
                    f"Label for '{key}' must be a string of at most 20 characters."
                )
            if len(label.strip()) == 0:
                raise ValueError(f"Label for '{key}' must not be blank.")
        return v

    @field_validator("custom_categories")
    @classmethod
    def validate_custom_categories(
        cls, v: list[CustomCategoryItem] | None
    ) -> list[CustomCategoryItem] | None:
        if v is None:
            return v
        if len(v) > MAX_CUSTOM_CATEGORIES:
            raise ValueError(
                f"At most {MAX_CUSTOM_CATEGORIES} custom categories allowed "
                f"(got {len(v)})."
            )
        keys = [item.key for item in v]
        if len(keys) != len(set(keys)):
            raise ValueError("Custom category keys must be unique.")
        return v


class AnalyticsConfigDefaults(BaseModel):
    """Default analytics configuration values for reference."""

    day_boundary_hour: int = 0
    category_labels: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_CATEGORY_LABELS)
    )
    custom_categories: list[CustomCategoryItem] = Field(default_factory=list)
