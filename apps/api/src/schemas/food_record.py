"""Food record response schemas.

A food record is a descriptive nutrition observation. These schemas expose the
carb *range*, confidence, nutrition, and provenance -- and deliberately carry no
dose/insulin field. Nothing here computes or returns dosing guidance.
"""

import json
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
    corrected_nutrition_json: dict | None = None
    corrected_at: datetime | None = None
    common_food_id: uuid.UUID | None = None
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


# Cap user-supplied nutrition so a correction can't store an unbounded JSON blob.
# Bound both the field count and the serialized size: the key count alone does
# not stop a single key holding a deeply-nested / multi-MB value.
_MAX_NUTRITION_KEYS = 30
_MAX_NUTRITION_SERIALIZED_CHARS = 2000


def validate_nutrition(nutrition: dict | None) -> dict | None:
    """Reject an oversized nutrition object; otherwise return it unchanged.

    Shared by the food-record correction and common-food schemas so user-supplied
    nutrition is bounded identically everywhere it is accepted.
    """
    if nutrition is None:
        return None
    if len(nutrition) > _MAX_NUTRITION_KEYS:
        msg = f"nutrition has too many fields (max {_MAX_NUTRITION_KEYS})"
        raise ValueError(msg)
    if len(json.dumps(nutrition, default=str)) > _MAX_NUTRITION_SERIALIZED_CHARS:
        msg = "nutrition is too large"
        raise ValueError(msg)
    return nutrition


class FoodRecordCorrectionRequest(BaseModel):
    """A user correction of a food record's carbs/nutrition.

    Correction fixes a *description of the food*, never a dose. There is
    deliberately no insulin/units/dose field here, and the corrected values are
    never read by IoB / treatment_safety / carb-ratio math. The original AI
    estimate is preserved on the record; these values land in the
    ``corrected_*`` columns and flip provenance to ``user_corrected``.
    """

    model_config = {"extra": "forbid"}

    # Reject-not-clamp bounds, identical to the create path.
    corrected_carbs_low: float = Field(ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    corrected_carbs_high: float = Field(ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    corrected_nutrition: dict | None = None

    @model_validator(mode="after")
    def validate_correction(self) -> "FoodRecordCorrectionRequest":
        if self.corrected_carbs_low > self.corrected_carbs_high:
            msg = "corrected_carbs_low must not exceed corrected_carbs_high"
            raise ValueError(msg)
        validate_nutrition(self.corrected_nutrition)
        return self
