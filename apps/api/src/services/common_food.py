"""Correction loop + common-food promotion service.

This is the truth-correction and personalization layer on top of the meal-photo
estimation pipeline:

  * ``correct_food_record`` applies a user's carb/nutrition correction to a
    record -- writing the ``corrected_*`` seams, flipping provenance to
    ``USER_CORRECTED``, and preserving the original AI estimate.
  * ``promote_to_common_food`` saves a record's (corrected, else AI) values as a
    user-named, deduped baseline and links the record to it.
  * ``link_record_to_common_food`` / ``update_common_food`` handle explicit
    linking and baseline edits.

Safety posture (NON-NEGOTIABLE): a correction fixes a *description of the food*,
never a dose. Nothing here returns or computes insulin, and neither corrected
records nor common foods are ever read by IoB / treatment_safety / carb-ratio
math. All work is scoped to the authenticated owner by the caller.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.logging_config import get_logger
from src.models.common_food import CommonFood, normalize_common_food_name
from src.models.food_record import FoodRecord, FoodRecordSource
from src.schemas.common_food import CommonFoodUpdateRequest
from src.schemas.food_record import FoodRecordCorrectionRequest
from src.services import meal_rag
from src.vision.carb_contract import CarbBoundsError, validate_carb_range

logger = get_logger(__name__)


class CommonFoodError(Exception):
    """Base class for correction / common-food service failures."""


class CarbValidationError(CommonFoodError):
    """A user-supplied carb range fell outside the reject-not-clamp bounds."""


class DuplicateCommonFoodError(CommonFoodError):
    """A common food with the same (normalized) name already exists."""


async def correct_food_record(
    db: AsyncSession,
    record: FoodRecord,
    correction: FoodRecordCorrectionRequest,
) -> FoodRecord:
    """Apply a user correction to ``record`` and flip provenance.

    The original AI estimate (``carbs_low`` / ``carbs_high`` / ``nutrition_json``
    / ``food_description``) is left untouched; the user's values land in the
    ``corrected_*`` columns. Carb bounds are enforced reject-not-clamp, matching
    the create path.
    """
    try:
        low, high = validate_carb_range(
            correction.corrected_carbs_low, correction.corrected_carbs_high
        )
    except CarbBoundsError as exc:
        raise CarbValidationError(str(exc)) from exc

    record.corrected_carbs_low = low
    record.corrected_carbs_high = high
    record.corrected_nutrition_json = correction.corrected_nutrition or None
    record.corrected_at = datetime.now(UTC)
    record.source = FoodRecordSource.USER_CORRECTED

    await db.commit()
    await db.refresh(record)

    # Re-index own-history RAG so a future photo recalls the user's corrected
    # value (the truth) rather than the original AI estimate. Best-effort -- a
    # re-index failure must not fail the correction response.
    if settings.meal_intelligence_enabled:
        try:
            await meal_rag.index_food_record(record)
        except Exception:
            logger.warning("RAG re-indexing failed for corrected record", exc_info=True)
    return record


def _effective_values(record: FoodRecord) -> tuple[float, float, dict | None]:
    """Return the carbs/nutrition to baseline from a record.

    Prefers the user's corrected values (the truth the platform stores) and
    falls back to the original AI estimate when the record was never corrected.

    Nutrition fallback is intentional: a user who corrects only carbs (the common
    case -- ``corrected_nutrition`` is optional) keeps the AI's nutrition, which
    is still the best available figure, rather than dropping it. So a corrected
    record can baseline corrected carbs alongside the original nutrition.
    """
    if (
        record.corrected_carbs_low is not None
        and record.corrected_carbs_high is not None
    ):
        nutrition = record.corrected_nutrition_json or record.nutrition_json
        return record.corrected_carbs_low, record.corrected_carbs_high, nutrition
    return record.carbs_low, record.carbs_high, record.nutrition_json


async def promote_to_common_food(
    db: AsyncSession,
    record: FoodRecord,
    name: str,
) -> CommonFood:
    """Promote ``record`` to a named common-food baseline and link it.

    Deduped per user on the normalized name: saving under an existing name
    updates that baseline (its carbs/nutrition + display name) rather than
    creating a near-duplicate. The record is linked to the resulting baseline.

    Must be called with no other pending session state: the unique-constraint
    race path below rolls the session back, which would discard any unrelated
    in-flight changes. The sole caller passes a freshly-loaded record.
    """
    low, high, nutrition = _effective_values(record)
    try:
        low, high = validate_carb_range(low, high)
    except CarbBoundsError as exc:  # pragma: no cover - record values are pre-bounded
        raise CarbValidationError(str(exc)) from exc

    normalized = normalize_common_food_name(name)
    if not normalized:
        raise CarbValidationError("Common food name must not be empty.")

    existing = await db.scalar(
        select(CommonFood).where(
            CommonFood.user_id == record.user_id,
            CommonFood.normalized_name == normalized,
        )
    )
    if existing is not None:
        common_food = existing
        common_food.name = name.strip()
        common_food.carbs_low = low
        common_food.carbs_high = high
        common_food.nutrition_json = nutrition
    else:
        common_food = CommonFood(
            user_id=record.user_id,
            name=name.strip(),
            normalized_name=normalized,
            carbs_low=low,
            carbs_high=high,
            nutrition_json=nutrition,
        )
        db.add(common_food)

    try:
        await db.flush()
    except IntegrityError:
        # Lost a race on the unique constraint: re-fetch and update the winner.
        await db.rollback()
        common_food = await db.scalar(
            select(CommonFood).where(
                CommonFood.user_id == record.user_id,
                CommonFood.normalized_name == normalized,
            )
        )
        if common_food is None:  # pragma: no cover - defensive
            raise
        # Re-bind the record (the rollback expired it) before linking below.
        record = await db.get(FoodRecord, record.id)
        common_food.name = name.strip()
        common_food.carbs_low = low
        common_food.carbs_high = high
        common_food.nutrition_json = nutrition

    record.common_food_id = common_food.id
    await db.commit()
    await db.refresh(common_food)
    await db.refresh(record)

    # Index the named baseline (and re-index the now-linked record) into
    # own-history RAG so a future photo of this food recalls the user's curated
    # baseline. Best-effort -- an indexing failure must not fail the promotion.
    if settings.meal_intelligence_enabled:
        try:
            await meal_rag.index_common_food(common_food)
            await meal_rag.index_food_record(record)
        except Exception:
            logger.warning("RAG indexing failed for promotion", exc_info=True)
    return common_food


async def link_record_to_common_food(
    db: AsyncSession,
    record: FoodRecord,
    common_food: CommonFood,
) -> FoodRecord:
    """Link an existing record to an existing (owned) common food."""
    record.common_food_id = common_food.id
    await db.commit()
    await db.refresh(record)
    return record


async def update_common_food(
    db: AsyncSession,
    common_food: CommonFood,
    update: CommonFoodUpdateRequest,
) -> CommonFood:
    """Rename and/or update a common food's baseline.

    Renaming to a name that collides with another of the user's common foods is
    rejected with ``DuplicateCommonFoodError``.
    """
    if update.name is not None:
        normalized = normalize_common_food_name(update.name)
        if not normalized:
            raise CarbValidationError("Common food name must not be empty.")
        if normalized != common_food.normalized_name:
            clash = await db.scalar(
                select(func.count())
                .select_from(CommonFood)
                .where(
                    CommonFood.user_id == common_food.user_id,
                    CommonFood.normalized_name == normalized,
                    CommonFood.id != common_food.id,
                )
            )
            if clash:
                raise DuplicateCommonFoodError(
                    "A common food with that name already exists."
                )
        common_food.name = update.name.strip()
        common_food.normalized_name = normalized

    if update.carbs_low is not None and update.carbs_high is not None:
        # Defense-in-depth: the request schema already enforces these bounds, so
        # this mirrors the create/correct paths and the DB CHECK rather than
        # being the primary gate (the except branch is not normally reachable).
        try:
            low, high = validate_carb_range(update.carbs_low, update.carbs_high)
        except CarbBoundsError as exc:
            raise CarbValidationError(str(exc)) from exc
        common_food.carbs_low = low
        common_food.carbs_high = high

    if "nutrition_json" in update.model_fields_set:
        common_food.nutrition_json = update.nutrition_json

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateCommonFoodError(
            "A common food with that name already exists."
        ) from exc
    await db.refresh(common_food)
    return common_food
