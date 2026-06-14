"""Food record response schemas.

A food record is a descriptive nutrition observation. These schemas expose the
carb *range*, confidence, nutrition, and provenance -- and deliberately carry no
dose/insulin field. Nothing here computes or returns dosing guidance.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from src.models.food_record import FoodRecordSource
from src.vision.carb_contract import CARB_GRAMS_MAX, CARB_GRAMS_MIN


class FoodRecordResponse(BaseModel):
    """A persisted food record returned to the client.

    ``carbs_low`` / ``carbs_high`` are the original AI estimate. When the record
    has been corrected, ``corrected_carbs_*`` carry the user's values and
    ``source`` is ``user_corrected``; the original estimate is kept.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    meal_timestamp: datetime
    food_description: str | None = None
    # Reject-not-clamp bounds, consistent with SafetyLimits conventions.
    carbs_low: float = Field(ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    carbs_high: float = Field(ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    confidence: str | None = None
    nutrition_json: dict | None = None
    source: FoodRecordSource
    corrected_carbs_low: float | None = Field(
        default=None, ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX
    )
    corrected_carbs_high: float | None = Field(
        default=None, ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX
    )
    ai_model: str | None = None
    ai_provider: str | None = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_carb_ordering(self) -> "FoodRecordResponse":
        """Carb low must not exceed high (reject, never reorder silently)."""
        if self.carbs_low > self.carbs_high:
            msg = "carbs_low must not exceed carbs_high"
            raise ValueError(msg)
        if (
            self.corrected_carbs_low is not None
            and self.corrected_carbs_high is not None
            and self.corrected_carbs_low > self.corrected_carbs_high
        ):
            msg = "corrected_carbs_low must not exceed corrected_carbs_high"
            raise ValueError(msg)
        return self


class FoodRecordListResponse(BaseModel):
    """A page of food records (most recent first)."""

    records: list[FoodRecordResponse]
    total: int
