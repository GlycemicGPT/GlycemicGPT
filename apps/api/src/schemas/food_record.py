"""Food record response schemas.

A food record is a descriptive nutrition observation. These schemas expose the
carb *range*, confidence, nutrition, and provenance -- and deliberately carry no
dose/insulin field. Nothing here computes or returns dosing guidance.
"""

import json
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from src.models.food_record import FoodRecordSource
from src.vision.carb_contract import CARB_GRAMS_MAX, CARB_GRAMS_MIN


class GroundingDetail(BaseModel):
    """Grounding detail returned alongside a fresh estimate (Story 50.E1).

    Describes *which* source grounded the estimate and the grounded carb range it
    suggests. This is a descriptive, cite-able reference -- never a dose. The
    persisted record keeps its own vision estimate in ``carbs_low`` / ``carbs_high``;
    this object carries the supplementary grounded figure + citation for the UI.

    It is computed at estimate time (the create path) and is not persisted beyond
    the attribution fields (``grounding_source`` / ``grounding_source_url`` /
    ``grounding_trust_tier``), so reads of an existing record carry those flat
    fields but not this object.
    """

    source: str
    source_url: str | None = None
    trust_tier: str
    # Grounded carb range from the source (own-history prior value, or the
    # published per-serving/per-100g figure). May be absent if the source only
    # confirms identity without a usable number.
    carbs_low: float | None = Field(default=None, ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    carbs_high: float | None = Field(default=None, ge=CARB_GRAMS_MIN, le=CARB_GRAMS_MAX)
    # The basis of the grounded figure (e.g. "per 100 g", "your last log").
    serving: str | None = None
    # Human-readable note ("You've logged this before (~45g)").
    note: str | None = None
    # Source licence / non-medical disclaimer to surface (e.g. Open Food Facts).
    disclaimer: str | None = None

    @model_validator(mode="after")
    def validate_carb_ordering(self) -> "GroundingDetail":
        """Carb low must not exceed high when both are present (reject inversion)."""
        if (
            self.carbs_low is not None
            and self.carbs_high is not None
            and self.carbs_low > self.carbs_high
        ):
            msg = "carbs_low must not exceed carbs_high"
            raise ValueError(msg)
        return self


class EstimateDispersion(BaseModel):
    """Multi-sample dispersion detail returned with a fresh estimate (Story 50.H1).

    The same photo is sampled N times; ``confidence`` is derived from how much
    those samples disagree (their coefficient of variation), NOT from the model's
    self-reported confidence -- which research shows is uncorrelated with accuracy
    and is therefore never surfaced as a safety signal. ``carbs_low`` / ``carbs_high``
    on the record are the empirical band (the observed spread across samples).

    This is computed at estimate time (the create path) and is transient: it is
    not persisted by H1 (50.H3 adds durable audit retention), so reads of an
    existing record do not carry it.

    Safety: ``wide_spread`` and ``note`` exist to communicate uncertainty
    viscerally, never to bless a number. Low dispersion is NOT "safe to dose" --
    consistency is not correctness -- so callers keep the verify-before-dosing
    qualifier dominant regardless of this value.
    """

    # Empirical, dispersion-derived band (constrained so a typo'd band can't pass
    # this system boundary).
    confidence: Literal["low", "medium", "high"]
    coefficient_of_variation: float | None = None
    # The configured target sample count (settings.meal_estimate_sample_count),
    # not necessarily the number of network calls made; ``samples_used`` is how
    # many produced a usable, in-bounds estimate.
    samples_requested: int
    samples_used: int
    identity_agreement: bool
    distinct_identities: list[str] = Field(default_factory=list)
    wide_spread: bool = False
    note: str | None = None


class FoodRecordResponse(BaseModel):
    """A persisted food record returned to the client.

    ``carbs_low`` / ``carbs_high`` are the original AI estimate. When the record
    has been corrected, ``corrected_carbs_*`` carry the user's values and
    ``source`` is ``user_corrected``; the original estimate is kept.

    ``confidence`` is the **empirical** dispersion-derived band (Story 50.H1), not
    the model's self-reported confidence (which is no longer surfaced).
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
    # Food-identity confirmation (Story 50.H2). ``food_description`` is the
    # AI-identified name; ``confirmed_food_name`` is the user's confirmed/corrected
    # identity (null until confirmed); external grounding only runs once
    # ``identity_confirmed`` is true. ``suggested_identity`` is a transient
    # create-time own-history pre-fill ("looks like your saved X"); absent later.
    confirmed_food_name: str | None = None
    identity_confirmed: bool = False
    suggested_identity: str | None = None
    # Grounding provenance (Story 50.E1). The flat fields are persisted on the
    # record and present on every read; ``grounding`` is the richer create-time
    # detail (grounded range + note + disclaimer) and is absent on later reads.
    grounding_source: str | None = None
    grounding_source_url: str | None = None
    grounding_trust_tier: str | None = None
    grounding: GroundingDetail | None = None
    # Multi-sample dispersion (Story 50.H1). Transient create-time detail
    # (empirical confidence + observed spread); absent on later reads.
    estimate_dispersion: EstimateDispersion | None = None
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


# Cap a user-supplied identity at the schema boundary (the service caps again as
# defence-in-depth; keep in sync with common_food._MAX_IDENTITY_CHARS).
_MAX_IDENTITY_NAME_CHARS = 200


class FoodRecordIdentityRequest(BaseModel):
    """A user confirmation/correction of *what the food is* (Story 50.H2).

    Confirming identity is distinct from correcting carbs and never implies a
    dose. The confirmed name opens the grounding gate: external authoritative
    nutrition (USDA / Open Food Facts today; restaurant facts via 50.E2) is only
    looked up once an identity has been confirmed, so a misidentified label is
    never certified with a citation.
    """

    model_config = {"extra": "forbid"}

    confirmed_food_name: str = Field(min_length=1, max_length=_MAX_IDENTITY_NAME_CHARS)

    @model_validator(mode="after")
    def validate_identity(self) -> "FoodRecordIdentityRequest":
        if not self.confirmed_food_name.strip():
            msg = "confirmed_food_name must not be blank"
            raise ValueError(msg)
        return self
