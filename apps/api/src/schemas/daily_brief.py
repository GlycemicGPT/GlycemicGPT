"""Story 5.3: Daily brief schemas.

Request and response schemas for daily brief generation and retrieval.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class InsulinBreakdown(BaseModel):
    """Breakdown of insulin delivery by type."""

    bolus_units: float = Field(default=0.0, description="Manual bolus insulin (units)")
    bolus_count: int = Field(default=0, description="Number of manual boluses")
    correction_units: float = Field(
        default=0.0, description="Correction bolus insulin (units)"
    )
    correction_count: int = Field(default=0, description="Number of correction boluses")
    auto_correction_units: float = Field(
        default=0.0, description="Control-IQ auto-correction insulin (units)"
    )
    auto_correction_count: int = Field(
        default=0, description="Number of auto-corrections"
    )
    basal_units: float = Field(
        default=0.0,
        description="Estimated basal delivery (rate x time integration)",
    )
    total_units: float = Field(
        default=0.0, description="Total insulin delivered (all types)"
    )


class DailyBriefMetrics(BaseModel):
    """Calculated glucose metrics for a 24-hour period."""

    time_in_range_pct: float = Field(
        ..., description="Percentage of readings in range (70-180 mg/dL)"
    )
    average_glucose: float = Field(..., description="Average glucose in mg/dL")
    low_count: int = Field(..., description="Number of readings below 70 mg/dL")
    high_count: int = Field(..., description="Number of readings above 180 mg/dL")
    readings_count: int = Field(..., description="Total number of glucose readings")
    correction_count: int = Field(
        default=0, description="Number of Control-IQ corrections"
    )
    total_insulin: float | None = Field(
        default=None, description="Total insulin delivered in units (all types)"
    )
    insulin_breakdown: InsulinBreakdown | None = Field(
        default=None, description="Detailed insulin delivery breakdown"
    )


class DailyBriefResponse(BaseModel):
    """Response schema for a daily brief."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    period_start: datetime
    period_end: datetime
    time_in_range_pct: float
    average_glucose: float
    low_count: int
    high_count: int
    readings_count: int
    correction_count: int
    total_insulin: float | None
    ai_summary: str
    ai_model: str
    ai_provider: str
    input_tokens: int
    output_tokens: int
    created_at: datetime


class DailyBriefListResponse(BaseModel):
    """Response schema for listing daily briefs."""

    briefs: list[DailyBriefResponse]
    total: int


class GenerateBriefRequest(BaseModel):
    """Request schema for manually generating a daily brief."""

    hours: int = Field(
        default=24,
        ge=1,
        le=72,
        description="Number of hours to analyze (default 24)",
    )
