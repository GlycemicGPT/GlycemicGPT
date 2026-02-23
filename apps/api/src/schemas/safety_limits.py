"""Safety limits schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class SafetyLimitsResponse(BaseModel):
    """Response schema for safety limits."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    min_glucose_mgdl: int
    max_glucose_mgdl: int
    max_basal_rate_milliunits: int
    max_bolus_dose_milliunits: int
    updated_at: datetime


class SafetyLimitsUpdate(BaseModel):
    """Request schema for updating safety limits.

    All fields are optional -- only provided fields are updated.
    Validates that min_glucose < max_glucose and all values are
    within absolute clinical bounds.
    """

    min_glucose_mgdl: int | None = Field(
        default=None,
        ge=20,
        le=499,
        description="Minimum valid glucose reading (mg/dL). Range: 20-499.",
    )
    max_glucose_mgdl: int | None = Field(
        default=None,
        ge=21,
        le=500,
        description="Maximum valid glucose reading (mg/dL). Range: 21-500.",
    )
    max_basal_rate_milliunits: int | None = Field(
        default=None,
        ge=1,
        le=15000,
        description="Maximum basal rate in milliunits/hr. Range: 1-15000.",
    )
    max_bolus_dose_milliunits: int | None = Field(
        default=None,
        ge=1,
        le=25000,
        description="Maximum single bolus dose in milliunits. Range: 1-25000.",
    )

    @model_validator(mode="after")
    def validate_glucose_ordering(self) -> "SafetyLimitsUpdate":
        """Validate that min_glucose < max_glucose when both are provided."""
        if (
            self.min_glucose_mgdl is not None
            and self.max_glucose_mgdl is not None
            and self.min_glucose_mgdl >= self.max_glucose_mgdl
        ):
            msg = "min_glucose_mgdl must be less than max_glucose_mgdl"
            raise ValueError(msg)
        return self


class SafetyLimitsDefaults(BaseModel):
    """Default safety limits values for reference."""

    min_glucose_mgdl: int = 20
    max_glucose_mgdl: int = 500
    max_basal_rate_milliunits: int = 15000
    max_bolus_dose_milliunits: int = 25000
