"""Story 35.12: Research source schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class ResearchSourceCreate(BaseModel):
    """Request to add a research source."""

    url: str = Field(
        ..., min_length=10, max_length=2000, description="Source URL (HTTPS)"
    )
    name: str = Field(
        ..., min_length=1, max_length=200, description="Human-readable name"
    )
    category: str | None = Field(
        default=None,
        max_length=50,
        description="Category: pump, cgm, insulin, guidelines",
    )

    @model_validator(mode="after")
    def validate_https(self) -> "ResearchSourceCreate":
        if not self.url.startswith("https://"):
            raise ValueError("Research source URLs must use HTTPS")
        return self


class ResearchSourceResponse(BaseModel):
    """Response for a research source."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    url: str
    name: str
    category: str | None
    is_active: bool
    last_researched_at: datetime | None
    created_at: datetime


class ResearchSourceListResponse(BaseModel):
    """Response for listing research sources."""

    sources: list[ResearchSourceResponse]
    total: int


class SuggestedSource(BaseModel):
    """A suggested research source based on user config."""

    url: str
    name: str
    category: str


class SuggestionsResponse(BaseModel):
    """Response for source suggestions."""

    suggestions: list[SuggestedSource]
    based_on: dict = Field(
        default_factory=dict,
        description="User config that generated these suggestions",
    )


class SourceRecommendation(BaseModel):
    """A domain the AI recommends adding."""

    domain: str
    url: str
    reason: str


class ResearchRunResponse(BaseModel):
    """Response after triggering a research run."""

    sources: int
    updated: int
    new: int
    unchanged: int
    errors: int
    recommendations: list[SourceRecommendation] = Field(default_factory=list)
