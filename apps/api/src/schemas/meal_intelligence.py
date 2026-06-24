"""Schemas for the per-user meal-intelligence preference."""

from pydantic import BaseModel, Field


class MealIntelligenceResponse(BaseModel):
    """Current user's meal-intelligence feature preference."""

    enabled: bool = Field(
        ...,
        description="Whether the meal-intelligence feature is enabled for this user",
    )


class MealIntelligenceUpdate(BaseModel):
    """Request to update the current user's meal-intelligence preference."""

    enabled: bool = Field(
        ...,
        description="Whether the meal-intelligence feature is enabled for this user",
    )
