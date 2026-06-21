"""Schemas for glucose unit preferences."""

from pydantic import BaseModel, Field

from src.core.units import GlucoseUnit


class GlucoseUnitPreferenceResponse(BaseModel):
    """Current user's glucose display unit preference."""

    glucose_unit: GlucoseUnit = Field(
        ..., description="Preferred glucose display unit: mgdl or mmol"
    )


class GlucoseUnitPreferenceUpdate(BaseModel):
    """Request to update the current user's glucose display unit preference."""

    glucose_unit: GlucoseUnit = Field(
        ..., description="Preferred glucose display unit: mgdl or mmol"
    )
