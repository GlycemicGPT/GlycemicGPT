"""Schemas for the bolus validation endpoint."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field

from src.core.treatment_safety.enums import BolusSource, SafetyCheckType


class BolusValidationRequest(BaseModel):
    """POST body for /api/treatment/validate-bolus."""

    requested_dose_milliunits: int = Field(
        ge=0,
        le=25_000,
        description="Requested dose in milliunits (0-25000).",
    )
    glucose_at_request_mgdl: int = Field(
        ge=20,
        le=500,
        description="Current glucose reading in mg/dL.",
    )
    timestamp: AwareDatetime = Field(
        description="Time of the request (client clock, timezone-aware).",
    )
    source: BolusSource = Field(
        description="Origin of the bolus request.",
    )
    user_confirmed: bool = Field(
        default=False,
        description=(
            "Whether the user explicitly confirmed. Required for "
            "ai_suggested and automated sources."
        ),
    )


class SafetyCheckResponse(BaseModel):
    """Single safety check result in the response."""

    check_type: SafetyCheckType
    passed: bool
    message: str
    details: dict[str, Any] | None = None


class BolusValidationResponse(BaseModel):
    """Response from /api/treatment/validate-bolus."""

    approved: bool
    rejection_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str | None = Field(
        default=None,
        description=(
            "Safety disclaimer text that MUST be shown to the user "
            "before any delivery action. Present for ai_suggested sources."
        ),
    )
    validated_dose_milliunits: int = Field(
        ge=0,
        le=25_000,
        description="Approved dose (0 if rejected).",
    )
    safety_checks: list[SafetyCheckResponse] = Field(default_factory=list)
    validation_id: uuid.UUID = Field(
        description="ID of the audit log entry for this validation.",
    )
    validated_at: datetime = Field(
        description="Server timestamp of the validation.",
    )
