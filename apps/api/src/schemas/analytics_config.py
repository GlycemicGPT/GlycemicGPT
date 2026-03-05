"""Analytics configuration schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AnalyticsConfigResponse(BaseModel):
    """Response schema for analytics configuration."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    day_boundary_hour: int
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


class AnalyticsConfigDefaults(BaseModel):
    """Default analytics configuration values for reference."""

    day_boundary_hour: int = 0
