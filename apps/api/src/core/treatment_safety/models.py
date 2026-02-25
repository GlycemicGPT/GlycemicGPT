"""Treatment safety Pydantic models.

Pure data models for treatment safety validation. No database
dependencies, no SQLAlchemy. Field validators match clinical bounds
from the existing SafetyLimitsUpdate schema.

See __init__.py for important regulatory context.
"""

import uuid
from typing import Any, Final, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from src.core.treatment_safety.enums import BolusSource, SafetyCheckType

# Absolute clinical bounds -- must match src.schemas.safety_limits.SafetyLimitsDefaults.
# Centralised here so treatment_safety models stay decoupled from the schemas package.
MAX_BOLUS_DOSE_MILLIUNITS: Final[int] = 25_000
MIN_GLUCOSE_MGDL: Final[int] = 20
MAX_GLUCOSE_MGDL: Final[int] = 500


class BolusRequest(BaseModel):
    """A request to deliver a bolus dose.

    All doses are in milliunits to avoid floating-point precision issues.
    Glucose values are in mg/dL matching the project-wide convention.
    """

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    requested_dose_milliunits: int = Field(
        ge=0,
        le=MAX_BOLUS_DOSE_MILLIUNITS,
        description=f"Requested bolus dose in milliunits. Range: 0-{MAX_BOLUS_DOSE_MILLIUNITS}.",
    )
    glucose_at_request_mgdl: int = Field(
        ge=MIN_GLUCOSE_MGDL,
        le=MAX_GLUCOSE_MGDL,
        description=f"Glucose reading at time of request (mg/dL). Range: {MIN_GLUCOSE_MGDL}-{MAX_GLUCOSE_MGDL}.",
    )
    timestamp: AwareDatetime
    source: BolusSource
    user_confirmed: bool = Field(
        default=False,
        description=(
            "Whether the user has explicitly confirmed this bolus. "
            "Required for ai_suggested and automated sources."
        ),
    )


class SafetyCheckResult(BaseModel):
    """Result of a single safety check."""

    model_config = ConfigDict(frozen=True)

    check_type: SafetyCheckType
    passed: bool
    message: str = Field(min_length=1)
    details: dict[str, Any] | None = None


class BolusValidationResult(BaseModel):
    """Aggregate result of all safety checks for a bolus request."""

    model_config = ConfigDict(frozen=True)

    approved: bool
    rejection_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validated_dose_milliunits: int = Field(
        default=0,
        ge=0,
        le=MAX_BOLUS_DOSE_MILLIUNITS,
        description=f"Validated dose in milliunits. Range: 0-{MAX_BOLUS_DOSE_MILLIUNITS}.",
    )
    safety_check_results: list[SafetyCheckResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_consistency(self) -> Self:
        """Enforce that approved/rejected states are internally consistent."""
        if not self.approved and self.validated_dose_milliunits != 0:
            msg = "validated_dose_milliunits must be 0 when the bolus is not approved"
            raise ValueError(msg)
        if self.approved and self.rejection_reasons:
            msg = "rejection_reasons must be empty when the bolus is approved"
            raise ValueError(msg)
        if self.approved and self.validated_dose_milliunits == 0:
            msg = "validated_dose_milliunits must be > 0 when the bolus is approved"
            raise ValueError(msg)
        if not self.approved and not self.rejection_reasons:
            msg = "rejection_reasons must not be empty when the bolus is rejected"
            raise ValueError(msg)
        return self
