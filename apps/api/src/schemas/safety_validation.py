"""Story 5.6: Pre-validation safety layer schemas.

Schemas for AI suggestion safety validation results.
"""

import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SafetyStatus(str, enum.Enum):
    """Validation outcome for an AI suggestion."""

    APPROVED = "approved"
    FLAGGED = "flagged"  # Contains flagged items but still shown
    REJECTED = "rejected"  # Blocked from display


class SuggestionType(str, enum.Enum):
    """Types of AI suggestions that can be validated."""

    CARB_RATIO = "carb_ratio"
    CORRECTION_FACTOR = "correction_factor"
    # A glucose figure the model spoke that does not trace to a logged reading
    # (rounding-tolerant). Not a ratio/factor change: its FlaggedSuggestion's
    # ``original_value``/``suggested_value`` carry the spoken value and nearest
    # reading, both in canonical mg/dL, and ``change_pct`` is unused (0).
    GLUCOSE_CITATION = "glucose_citation"


class FlaggedSuggestion(BaseModel):
    """A single flagged suggestion extracted from AI output."""

    suggestion_type: SuggestionType
    original_value: float = Field(
        ...,
        description=(
            "For ratio/factor types, the original value; for GLUCOSE_CITATION, "
            "the spoken glucose value in canonical mg/dL"
        ),
    )
    suggested_value: float = Field(
        ...,
        description=(
            "For ratio/factor types, the suggested value; for GLUCOSE_CITATION, "
            "the nearest logged reading in canonical mg/dL"
        ),
    )
    change_pct: float = Field(
        ...,
        description="Percentage change from original (0 for GLUCOSE_CITATION)",
    )
    max_allowed_pct: float = Field(
        default=20.0, description="Maximum allowed percentage change"
    )
    reason: str = Field(..., description="Why this was flagged")


class ValidationResult(BaseModel):
    """Result of validating AI-generated suggestions."""

    status: SafetyStatus
    flagged_items: list[FlaggedSuggestion] = Field(default_factory=list)
    original_text: str = Field(..., description="Original AI output")
    sanitized_text: str = Field(
        ..., description="AI output with safety annotations added"
    )
    has_dangerous_content: bool = Field(
        default=False, description="Whether dangerous keywords were detected"
    )


class SafetyLogResponse(BaseModel):
    """Response schema for a safety validation log entry."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    analysis_type: str
    analysis_id: uuid.UUID
    status: str
    flagged_items: list[dict]
    created_at: datetime


class SafetyLogListResponse(BaseModel):
    """Response schema for listing safety logs."""

    logs: list[SafetyLogResponse]
    total: int
