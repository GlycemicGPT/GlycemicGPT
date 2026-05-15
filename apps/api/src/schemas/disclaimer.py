"""Schemas for disclaimer acknowledgment API.

Story 1.3: First-Run Safety Disclaimer
"""

from datetime import datetime

from pydantic import BaseModel, Field


class DisclaimerStatusResponse(BaseModel):
    """Response for disclaimer status check."""

    acknowledged: bool = Field(
        description="Whether the disclaimer has been acknowledged"
    )
    acknowledged_at: datetime | None = Field(
        default=None,
        description="Timestamp when the disclaimer was acknowledged",
    )
    disclaimer_version: str = Field(
        default="1.0",
        description="Current disclaimer version",
    )


class DisclaimerAcknowledgeRequest(BaseModel):
    """Request to acknowledge the disclaimer."""

    session_id: str = Field(
        min_length=36,
        max_length=36,
        description="Unique session identifier (UUID)",
    )
    checkbox_experimental: bool = Field(
        description="User checked the experimental software acknowledgment",
    )
    checkbox_not_medical_advice: bool = Field(
        description="User checked the not medical advice acknowledgment",
    )
    checkbox_ai_data_flow: bool = Field(
        description="User checked the AI data-handling acknowledgment (cloud vs local provider data flow)",
    )


class DisclaimerAcknowledgeResponse(BaseModel):
    """Response after acknowledging the disclaimer."""

    success: bool = Field(description="Whether the acknowledgment was stored")
    acknowledged_at: datetime = Field(
        description="Timestamp when the disclaimer was acknowledged"
    )
    message: str = Field(description="Human-readable status message")
