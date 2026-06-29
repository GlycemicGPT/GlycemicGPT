"""Insulin configuration schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Allowed insulin type values. Bolus/rapid insulins only -- this list drives the
# DIA picker that feeds the IOB curve, so long-acting/basal insulins are
# deliberately excluded (they are recognized separately on ingestion via
# BASAL_INJECTION). Keep this allow-list closed: insulin_type is rendered into
# the AI prompt, so it must never become free text. "custom" lets a user
# hand-set DIA/onset and is the only valid type without a preset.
VALID_INSULIN_TYPES = {
    # Rapid-acting analogs
    "humalog",
    "novolog",
    "fiasp",
    "lyumjev",
    "apidra",
    "novorapid",
    "liprolog",
    "admelog",
    "trurapi",
    "kirsty",
    # Regular (short-acting) human insulin
    "humulin_r",
    "novolin_r",
    "insuman_rapid",
    "custom",
}

# Preset DIA (hours) and onset (minutes) per insulin type. A brand that shares a
# molecule with a shipped entry (aspart/lispro/glulisine) reuses that molecule's
# PK verbatim, so its IOB curve is already correct. Regular human insulin uses a
# longer DIA and later onset.
INSULIN_PRESETS: dict[str, dict[str, float]] = {
    # Rapid-acting analogs
    "humalog": {"dia_hours": 4.0, "onset_minutes": 15.0},
    "novolog": {"dia_hours": 4.0, "onset_minutes": 15.0},
    "fiasp": {"dia_hours": 3.5, "onset_minutes": 5.0},
    "lyumjev": {"dia_hours": 3.5, "onset_minutes": 5.0},
    "apidra": {"dia_hours": 4.0, "onset_minutes": 15.0},
    "novorapid": {"dia_hours": 4.0, "onset_minutes": 15.0},
    "liprolog": {"dia_hours": 4.0, "onset_minutes": 15.0},
    "admelog": {"dia_hours": 4.0, "onset_minutes": 15.0},
    "trurapi": {"dia_hours": 4.0, "onset_minutes": 15.0},
    "kirsty": {"dia_hours": 4.0, "onset_minutes": 15.0},
    # Regular (short-acting) human insulin. DIA 6.0h reflects the realistic
    # total duration of action: the FDA Humulin R / Novolin R U-100 labels
    # terminate ~8h (peak ~3h) and clinical references give 5-8h. The IOB curve
    # zeroes at DIA, so a shorter value would truncate a still-active tail and
    # under-count late IOB (the stacking direction). Duration is dose-dependent
    # and large doses can act longer than this fixed model assumes.
    "humulin_r": {"dia_hours": 6.0, "onset_minutes": 30.0},
    "novolin_r": {"dia_hours": 6.0, "onset_minutes": 30.0},
    "insuman_rapid": {"dia_hours": 6.0, "onset_minutes": 30.0},
}


class InsulinConfigResponse(BaseModel):
    """Response schema for insulin configuration."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    insulin_type: str
    dia_hours: float
    onset_minutes: float
    updated_at: datetime


class InsulinConfigUpdate(BaseModel):
    """Request schema for updating insulin configuration.

    All fields are optional -- only provided fields are updated.
    """

    model_config = {"extra": "forbid"}

    insulin_type: str | None = Field(
        default=None,
        max_length=50,
        description=(
            "Bolus insulin type. Must be one of the supported values, "
            "or 'custom' to hand-set DIA/onset."
        ),
    )
    dia_hours: float | None = Field(
        default=None,
        ge=2.0,
        le=8.0,
        description="Duration of insulin action in hours. Range: 2-8.",
    )
    onset_minutes: float | None = Field(
        default=None,
        ge=1.0,
        le=60.0,
        description="Insulin onset time in minutes. Range: 1-60.",
    )

    @field_validator("insulin_type")
    @classmethod
    def validate_insulin_type(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_INSULIN_TYPES:
            raise ValueError(
                f"Invalid insulin type '{v}'. "
                f"Must be one of: {', '.join(sorted(VALID_INSULIN_TYPES))}"
            )
        return v


class InsulinConfigDefaults(BaseModel):
    """Default insulin configuration values for reference."""

    insulin_type: str = "humalog"
    dia_hours: float = 4.0
    onset_minutes: float = 15.0
    presets: dict[str, dict[str, float]] = INSULIN_PRESETS
