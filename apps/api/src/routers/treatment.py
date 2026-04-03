"""Treatment validation router.

Provides the bolus validation endpoint for mobile plugins.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import get_current_user, require_diabetic_or_admin
from src.core.treatment_safety.enums import BolusSource
from src.database import get_db
from src.models.user import User
from src.schemas.treatment_validation import (
    BolusValidationRequest,
    BolusValidationResponse,
    SafetyCheckResponse,
)
from src.services.treatment_validation import validate_bolus

_AI_DISCLAIMER = (
    "This dose was suggested by an AI model and may be incorrect. "
    "Verify with your healthcare provider before acting. "
    "Auto-execution of AI-suggested doses is prohibited."
)

router = APIRouter(
    prefix="/api/treatment",
    tags=["treatment"],
    dependencies=[Depends(require_diabetic_or_admin)],
)


@router.post(
    "/validate-bolus",
    response_model=BolusValidationResponse,
    responses={
        200: {"description": "Validation result (may be approved or rejected)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Permission denied"},
        422: {"description": "Invalid request body"},
    },
)
async def validate_bolus_request(
    body: BolusValidationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BolusValidationResponse:
    """Validate a bolus request against safety limits.

    Mobile plugins MUST call this endpoint before attempting any
    insulin delivery. The response indicates whether the bolus is
    approved and includes detailed check results.

    This endpoint does NOT trigger delivery -- the caller is
    responsible for acting on the result.
    """
    log_entry, result = await validate_bolus(
        user_id=user.id,
        requested_dose_milliunits=body.requested_dose_milliunits,
        glucose_at_request_mgdl=body.glucose_at_request_mgdl,
        timestamp=body.timestamp,
        source=body.source.value,
        user_confirmed=body.user_confirmed,
        db=db,
    )
    # Commit validation + audit log atomically.
    await db.commit()
    await db.refresh(log_entry)

    disclaimer = _AI_DISCLAIMER if body.source == BolusSource.ai_suggested else None

    return BolusValidationResponse(
        approved=result.approved,
        rejection_reasons=result.rejection_reasons,
        warnings=result.warnings,
        disclaimer=disclaimer,
        validated_dose_milliunits=result.validated_dose_milliunits,
        safety_checks=[
            SafetyCheckResponse(
                check_type=cr.check_type,
                passed=cr.passed,
                message=cr.message,
                details=cr.details,
            )
            for cr in result.safety_check_results
        ],
        validation_id=log_entry.id,
        validated_at=log_entry.created_at,
    )
