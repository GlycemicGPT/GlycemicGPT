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
from src.schemas.auth import ErrorResponse
from src.schemas.food_record import FoodRecordListResponse, FoodRecordResponse
from src.services import food_image, food_vision

logger = get_logger(__name__)

router = APIRouter(prefix="/api/food-records", tags=["food-records"])

# Declared content types accepted at the boundary. The authoritative check is
# byte-level decoding in `food_image.process_upload`; this just rejects obvious
# mismatches early with a clear 415.
_ACCEPTED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _require_enabled() -> None:
    if not settings.meal_intelligence_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal intelligence is not enabled.",
        )


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
    _require_enabled()

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
    _require_enabled()
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
    _require_enabled()
    record = await _get_owned_record(record_id, current_user.id, db)
    return FoodRecordResponse.model_validate(record)


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
    _require_enabled()
    record = await _get_owned_record(record_id, current_user.id, db)
    storage_path = record.storage_path
    await db.delete(record)
    await db.commit()
    # Unlink after the row is gone so a failed unlink can't strand a dangling row.
    food_image.delete_stored_image(storage_path)
