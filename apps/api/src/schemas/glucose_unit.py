"""Schemas for glucose unit preferences."""

from pydantic import BaseModel, Field

from src.core.units import GlucoseUnit, GlucoseUnitSource


class GlucoseUnitPreferenceResponse(BaseModel):
    """Current user's glucose display unit preference."""

    glucose_unit: GlucoseUnit = Field(
        ..., description="Preferred glucose display unit: mgdl or mmol"
    )
    glucose_unit_source: GlucoseUnitSource | None = Field(
        default=None,
        description=(
            "Provenance of the preference: 'seed' (smart default, overridable),"
            " 'user' (explicit choice), or null (legacy). Drives the one-time"
            " confirmation notice."
        ),
    )


class GlucoseUnitPreferenceUpdate(BaseModel):
    """Request to update the current user's glucose display unit preference."""

    glucose_unit: GlucoseUnit = Field(
        ..., description="Preferred glucose display unit: mgdl or mmol"
    )
