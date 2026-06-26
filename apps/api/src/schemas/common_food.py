"""Common-food request/response schemas.

A common food is a user-named carb/nutrition baseline. It is a descriptive
baseline only -- there is deliberately no dose/insulin/units field, and these
values never flow into IoB / treatment_safety / carb-ratio math.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from src.schemas.food_record import validate_nutrition
from src.vision.carb_contract import CARB_GRAMS_MAX, CARB_GRAMS_MIN

# Keep in sync with CommonFood.name / common_foods.name length (String(120)).
_NAME_MAX = 120


class CommonFoodResponse(BaseModel):
    """A saved common-food baseline returned to the client."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    carbs_low: float = Field(ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    carbs_high: float = Field(ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    nutrition_json: dict | None = None
    created_at: datetime
    updated_at: datetime


class CommonFoodListResponse(BaseModel):
    """A page of common foods (most recently updated first)."""

    common_foods: list[CommonFoodResponse]
    total: int


class SaveAsCommonFoodRequest(BaseModel):
    """Promote a food record to a named common-food baseline.

    Carbs/nutrition are taken from the record (its corrected values if present,
    else the AI estimate); the user supplies the name. Saving under a name that
    already exists updates that baseline rather than creating a duplicate.
    """

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=_NAME_MAX)


class LinkCommonFoodRequest(BaseModel):
    """Link an existing food record to an existing common food."""

    model_config = {"extra": "forbid"}

    common_food_id: uuid.UUID


class CommonFoodUpdateRequest(BaseModel):
    """Rename a common food and/or update its baseline carbs/nutrition.

    All fields optional; only those provided are changed. Renaming to a name
    that collides with another of the user's common foods is rejected (409).
    """

    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    carbs_low: float | None = Field(default=None, ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    carbs_high: float | None = Field(default=None, ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    nutrition_json: dict | None = None

    @model_validator(mode="after")
    def validate_update(self) -> "CommonFoodUpdateRequest":
        # Carb bounds must be set together so the stored range is always valid.
        if (self.carbs_low is None) != (self.carbs_high is None):
            msg = "carbs_low and carbs_high must be provided together"
            raise ValueError(msg)
        if (
            self.carbs_low is not None
            and self.carbs_high is not None
            and self.carbs_low > self.carbs_high
        ):
            msg = "carbs_low must not exceed carbs_high"
            raise ValueError(msg)
        validate_nutrition(self.nutrition_json)
        return self
