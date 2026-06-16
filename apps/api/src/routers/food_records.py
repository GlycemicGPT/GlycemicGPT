"""Food-record API: meal-photo carb estimation.

Upload a meal photo, get a structured carbohydrate estimate (range + confidence
+ nutrition), and persist it as a food record. The feature is flag-gated
(``meal_intelligence_enabled``) and BETA.

Safety: every response describes food, never a dose. No endpoint here returns or
computes insulin/dosing, and food records are never fed into IoB /
treatment_safety / carb-ratio math.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.auth import DiabeticOrAdminUser
from src.database import get_db
from src.logging_config import get_logger
from src.middleware.rate_limit import limiter
from src.models.food_record import FoodRecord
from src.routers._meal_intelligence import (
    get_owned_common_food,
    require_meal_intelligence,
)
from src.schemas.auth import ErrorResponse
from src.schemas.common_food import (
    CommonFoodResponse,
    LinkCommonFoodRequest,
    SaveAsCommonFoodRequest,
)
from src.schemas.food_record import (
    FoodRecordAuditResponse,
    FoodRecordCorrectionRequest,
    FoodRecordIdentityRequest,
    FoodRecordListResponse,
    FoodRecordResponse,
)
from src.services import common_food as common_food_service
from src.services import food_image, food_vision, meal_audit

logger = get_logger(__name__)

router = APIRouter(prefix="/api/food-records", tags=["food-records"])

# Declared content types accepted at the boundary. The authoritative check is
# byte-level decoding in `food_image.process_upload`; this just rejects obvious
# mismatches early with a clear 415.
_ACCEPTED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


@router.post(
    "",
    response_model=FoodRecordResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "No AI provider configured"},
        413: {"model": ErrorResponse, "description": "Image too large"},
        415: {"model": ErrorResponse, "description": "Unsupported image type"},
        422: {"model": ErrorResponse, "description": "Vision unavailable / unusable"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
)
# Each upload triggers a full image decode + an AI vision call, so cap it
# tighter than the global per-IP limit.
@limiter.limit("20/minute")
async def upload_food_photo(
    request: Request,
    current_user: DiabeticOrAdminUser,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
) -> FoodRecordResponse:
    """Upload a meal photo and persist its structured carb estimate.

    The photo is validated, EXIF-stripped, and analyzed via the user's
    configured AI provider's vision route. If that provider has no vision route,
    a clear 422 is returned -- never a silent failure or a fabricated estimate.
    """
    require_meal_intelligence()

    if file.content_type and file.content_type not in _ACCEPTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported image type. Use JPEG, PNG, or WebP.",
        )

    # Bounded read: never pull more than the cap (plus one byte to detect
    # overflow) into memory.
    raw = await file.read(settings.food_image_max_bytes + 1)

    try:
        record = await food_vision.create_food_record_from_image(
            db=db, user=current_user, raw_image=raw
        )
    except food_image.ImageTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    except food_image.UnsupportedImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    except food_image.InvalidImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except food_vision.ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except food_vision.VisionUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except food_vision.EstimateRejectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except food_vision.VisionServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    return FoodRecordResponse.model_validate(record)


@router.get(
    "",
    response_model=FoodRecordListResponse,
    responses={401: {"model": ErrorResponse, "description": "Not authenticated"}},
)
async def list_food_records(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
) -> FoodRecordListResponse:
    """List the current user's food records, most recent meal first."""
    require_meal_intelligence()
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    total = await db.scalar(
        select(func.count())
        .select_from(FoodRecord)
        .where(FoodRecord.user_id == current_user.id)
    )
    result = await db.execute(
        select(FoodRecord)
        .where(FoodRecord.user_id == current_user.id)
        .order_by(FoodRecord.meal_timestamp.desc())
        .limit(limit)
        .offset(offset)
    )
    records = [FoodRecordResponse.model_validate(r) for r in result.scalars().all()]
    return FoodRecordListResponse(records=records, total=total or 0)


async def _get_owned_record(
    record_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> FoodRecord:
    """Fetch a record scoped to its owner; 404 if missing (no existence leak)."""
    result = await db.execute(
        select(FoodRecord).where(
            FoodRecord.id == record_id, FoodRecord.user_id == user_id
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Food record not found."
        )
    return record


@router.get(
    "/{record_id}",
    response_model=FoodRecordResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Food record not found"},
    },
)
async def get_food_record(
    record_id: uuid.UUID,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> FoodRecordResponse:
    """Get one of the current user's food records."""
    require_meal_intelligence()
    record = await _get_owned_record(record_id, current_user.id, db)
    return FoodRecordResponse.model_validate(record)


@router.get(
    "/{record_id}/audit",
    response_model=FoodRecordAuditResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Audit trail not found"},
    },
)
async def get_food_record_audit(
    record_id: uuid.UUID,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> FoodRecordAuditResponse:
    """Get the "how was this estimated" provenance trail for a record (50.H3).

    Owner-scoped (IDOR-safe): the record must belong to the caller, and the audit
    fetch is itself scoped by user id. Descriptive only -- raw per-sample reads,
    the empirical dispersion, and the precedence decision; never a dose.
    """
    require_meal_intelligence()
    # 404 if the record isn't the caller's (ownership check) ...
    await _get_owned_record(record_id, current_user.id, db)
    # ... and the audit fetch is independently owner-scoped.
    audit = await meal_audit.get_audit(db, record_id, current_user.id)
    if audit is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Audit trail not found"
        )
    return FoodRecordAuditResponse.from_audit(audit)


@router.delete(
    "/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Food record not found"},
    },
)
async def delete_food_record(
    record_id: uuid.UUID,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a food record and its stored photo (user-initiated)."""
    require_meal_intelligence()
    record = await _get_owned_record(record_id, current_user.id, db)
    storage_path = record.storage_path
    await db.delete(record)
    await db.commit()
    # Unlink after the row is gone so a failed unlink can't strand a dangling row.
    food_image.delete_stored_image(storage_path)


@router.post(
    "/{record_id}/correct",
    response_model=FoodRecordResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Food record not found"},
        422: {"model": ErrorResponse, "description": "Carb value out of range"},
    },
)
async def correct_food_record(
    record_id: uuid.UUID,
    correction: FoodRecordCorrectionRequest,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> FoodRecordResponse:
    """Correct a food record's carbs/nutrition.

    Fixes the *description of the food* -- never a dose. The user's values are
    written to the record's correction columns and provenance flips to
    ``user_corrected``; the original AI estimate is preserved. Corrected values
    are never read by IoB / treatment_safety / carb-ratio math.
    """
    require_meal_intelligence()
    record = await _get_owned_record(record_id, current_user.id, db)
    try:
        record = await common_food_service.correct_food_record(db, record, correction)
    except common_food_service.CarbValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return FoodRecordResponse.model_validate(record)


@router.post(
    "/{record_id}/confirm-identity",
    response_model=FoodRecordResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Food record not found"},
        422: {"model": ErrorResponse, "description": "Identity name invalid"},
    },
)
async def confirm_food_identity(
    record_id: uuid.UUID,
    identity: FoodRecordIdentityRequest,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> FoodRecordResponse:
    """Confirm or correct *what the food is* (Story 50.H2).

    Distinct from carb correction and never a dose. The confirmed identity opens
    the grounding gate: only now is external authoritative nutrition (USDA / Open
    Food Facts today; restaurant facts via 50.E2) looked up, keyed on the confirmed
    name -- so a misidentified label is never certified with an authoritative
    citation.
    """
    require_meal_intelligence()
    record = await _get_owned_record(record_id, current_user.id, db)
    try:
        record = await common_food_service.confirm_food_identity(
            db, record, identity.confirmed_food_name
        )
    # Defence in depth: the schema already rejects a blank/oversized name (422),
    # so this only fires for a non-HTTP caller -- mirrors the carb-correction path.
    except common_food_service.IdentityValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return FoodRecordResponse.model_validate(record)


@router.post(
    "/{record_id}/save-as-common-food",
    response_model=CommonFoodResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Food record not found"},
        422: {"model": ErrorResponse, "description": "Carb value out of range"},
    },
)
async def save_record_as_common_food(
    record_id: uuid.UUID,
    body: SaveAsCommonFoodRequest,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> CommonFoodResponse:
    """Promote a food record to a named common-food baseline and link it.

    Uses the record's corrected values when present, else the AI estimate.
    Saving under an existing name updates that baseline (dedupe by name) rather
    than creating a near-duplicate.
    """
    require_meal_intelligence()
    record = await _get_owned_record(record_id, current_user.id, db)
    try:
        common_food = await common_food_service.promote_to_common_food(
            db, record, body.name
        )
    except common_food_service.CarbValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return CommonFoodResponse.model_validate(common_food)


@router.post(
    "/{record_id}/link-common-food",
    response_model=FoodRecordResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Record or common food not found"},
    },
)
async def link_record_to_common_food(
    record_id: uuid.UUID,
    body: LinkCommonFoodRequest,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> FoodRecordResponse:
    """Link an existing food record to one of the user's existing common foods."""
    require_meal_intelligence()
    record = await _get_owned_record(record_id, current_user.id, db)
    # Both sides are owner-scoped: a missing or cross-user baseline 404s with no
    # existence leak.
    common_food = await get_owned_common_food(body.common_food_id, current_user.id, db)
    record = await common_food_service.link_record_to_common_food(
        db, record, common_food
    )
    return FoodRecordResponse.model_validate(record)
