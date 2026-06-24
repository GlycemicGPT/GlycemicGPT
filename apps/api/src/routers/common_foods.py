"""Common-foods API: user-named carb/nutrition baselines.

Manage the baselines a user saves for foods they eat often: list, fetch,
rename + update baseline values, and delete. Promotion ("save as common food")
and linking live on the food-records router, since they act on a record.

The feature is gated by the user's own ``meal_intelligence_enabled`` preference.
Every query is scoped to the authenticated owner.

Safety: a common food is a descriptive baseline, never a dose. No endpoint here
returns or computes insulin, and common-food values never flow into IoB /
treatment_safety / carb-ratio math.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import DiabeticOrAdminUser
from src.database import get_db
from src.logging_config import get_logger
from src.models.common_food import CommonFood
from src.routers._meal_intelligence import (
    get_owned_common_food,
    require_meal_intelligence,
)
from src.schemas.auth import ErrorResponse
from src.schemas.common_food import (
    CommonFoodListResponse,
    CommonFoodResponse,
    CommonFoodUpdateRequest,
)
from src.services import common_food as common_food_service

logger = get_logger(__name__)

router = APIRouter(prefix="/api/common-foods", tags=["common-foods"])


@router.get(
    "",
    response_model=CommonFoodListResponse,
    responses={401: {"model": ErrorResponse, "description": "Not authenticated"}},
)
async def list_common_foods(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
) -> CommonFoodListResponse:
    """List the current user's common foods, most recently updated first."""
    require_meal_intelligence(current_user)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    total = await db.scalar(
        select(func.count())
        .select_from(CommonFood)
        .where(CommonFood.user_id == current_user.id)
    )
    result = await db.execute(
        select(CommonFood)
        .where(CommonFood.user_id == current_user.id)
        .order_by(CommonFood.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    foods = [CommonFoodResponse.model_validate(f) for f in result.scalars().all()]
    return CommonFoodListResponse(common_foods=foods, total=total or 0)


@router.get(
    "/{common_food_id}",
    response_model=CommonFoodResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Common food not found"},
    },
)
async def get_common_food(
    common_food_id: uuid.UUID,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> CommonFoodResponse:
    """Get one of the current user's common foods."""
    require_meal_intelligence(current_user)
    common_food = await get_owned_common_food(common_food_id, current_user.id, db)
    return CommonFoodResponse.model_validate(common_food)


@router.patch(
    "/{common_food_id}",
    response_model=CommonFoodResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Common food not found"},
        409: {"model": ErrorResponse, "description": "Name already in use"},
        422: {"model": ErrorResponse, "description": "Carb value out of range"},
    },
)
async def update_common_food(
    common_food_id: uuid.UUID,
    update: CommonFoodUpdateRequest,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> CommonFoodResponse:
    """Rename and/or update a common food's baseline carbs/nutrition."""
    require_meal_intelligence(current_user)
    common_food = await get_owned_common_food(common_food_id, current_user.id, db)
    try:
        common_food = await common_food_service.update_common_food(
            db, common_food, update
        )
    except common_food_service.DuplicateCommonFoodError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except common_food_service.CarbValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return CommonFoodResponse.model_validate(common_food)


@router.delete(
    "/{common_food_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Common food not found"},
    },
)
async def delete_common_food(
    common_food_id: uuid.UUID,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a common food. Linked records are unlinked (FK ON DELETE SET NULL).

    Deliberately NOT gated on the meal-intelligence preference: a user who turns
    the feature off must still be able to delete data they already created.
    Owner-scoping below is the access control.
    """
    common_food = await get_owned_common_food(common_food_id, current_user.id, db)
    await db.delete(common_food)
    await db.commit()
