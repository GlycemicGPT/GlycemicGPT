"""Grounding orchestrator: reconcile an estimate against history + published facts.

Story 50.E1, AC4. Given a vision-identified food, this picks the single best
grounding source in trust order and returns a descriptive citation. Precedence:

  1. own-history **corrected** value  (USER_PROVIDED -- the user's own truth)
  2. branded restaurant chain          (AUTHORITATIVE -- the chain's own menu facts)
  3. USDA FoodData Central             (AUTHORITATIVE -- official, CC0)
  4. Open Food Facts                   (RESEARCHED   -- crowd-sourced, ODbL)
  5. own-history **uncorrected** value (USER_PROVIDED -- a prior estimate)
  6. none -> pure vision

The mechanisms stay architecturally distinct (own-history RAG vs external research
vs on-demand restaurant fetch), separated by trust tier and source module; this
module only chooses between their already-computed results.

Safety posture (NON-NEGOTIABLE): grounding sharpens the *descriptive* estimate
only. It returns a carb range + citation, never a dose, and the result is never
read by IoB / treatment_safety / carb-ratio math. The never-dose-or-bolus framing
is preserved by the callers (the persistent qualifier on every estimate surface).
"""

import uuid

from src.config import settings
from src.logging_config import get_logger
from src.models.knowledge_chunk import KnowledgeChunk
from src.schemas.food_record import GroundingDetail
from src.services import meal_rag, nutrition_sources, restaurant_nutrition

logger = get_logger(__name__)


def _recall_detail(recall: meal_rag.MealRecall) -> GroundingDetail:
    low, high = recall.carbs_low, recall.carbs_high
    span = f"~{low:g}g" if low == high else f"~{low:g}-{high:g}g"
    basis = "your corrected value" if recall.is_corrected else "your earlier estimate"
    return GroundingDetail(
        source="Your meal history",
        source_url=None,
        trust_tier=KnowledgeChunk.TIER_USER_PROVIDED,
        carbs_low=low,
        carbs_high=high,
        serving="your last log",
        note=f"You've logged this before ({span}, {basis}).",
        disclaimer=None,
    )


def _fact_detail(fact: nutrition_sources.NutritionFact) -> GroundingDetail:
    return GroundingDetail(
        source=fact.source_name,
        source_url=fact.source_url,
        trust_tier=fact.trust_tier,
        carbs_low=fact.carbs_grams,
        carbs_high=fact.carbs_grams,
        serving=fact.serving,
        note=f"{fact.name}: ~{fact.carbs_grams:g}g carbohydrate {fact.serving}.",
        disclaimer=fact.disclaimer,
        # Carry any published comorbidity values (saturated fat /
        # sugars / added sugars / sodium) so the confirm path can persist them. An
        # own-history recall has no label, so ``_recall_detail`` leaves them None.
        saturated_fat_grams=fact.saturated_fat_grams,
        sugars_grams=fact.sugars_grams,
        added_sugars_grams=fact.added_sugars_grams,
        sodium_mg=fact.sodium_mg,
    )


async def ground_estimate(
    user_id: uuid.UUID,
    identity: str | None,
    *,
    identity_confirmed: bool,
    exclude_food_record_id: uuid.UUID | str | None = None,
) -> GroundingDetail | None:
    """Return the best grounding for a *confirmed-identity* estimate, or None.

    Story 50.H2 wraps the whole precedence ladder in a food-identity gate: food
    misidentification is the dominant, upstream error, and grounding a
    misidentified label to USDA / Open Food Facts / a restaurant page certifies a
    confident-wrong answer with an authoritative citation. So nothing here runs
    until the user has confirmed (or corrected) *what the food is*; an unconfirmed
    vision label stays vision-only (range + empirical confidence) and is grounded
    only after confirmation, against the confirmed ``identity``.

    Decoupled from any caller transaction: the own-history recall and the external
    lookups each manage their own DB sessions and each fails open to None
    internally, so this orchestrator stays free of redundant try/except layers.
    The single hard fail-open boundary is the caller (``food_vision``).

    ``exclude_food_record_id`` is forwarded to own-history recall so the record
    being grounded never recalls itself (a first log must not cite itself).
    """
    # Defence in depth: the only callers are already flag-gated, but enforce the
    # feature flag at this boundary too so a future caller can't run grounding
    # (embedding + external fetch) while meal intelligence is off.
    if not settings.meal_intelligence_enabled:
        return None

    # The identity gate (AC3): never ground an unconfirmed / uncorrected label.
    if not identity_confirmed:
        return None

    description = (identity or "").strip()
    if not description:
        return None

    recall = await meal_rag.recall_similar_meal(
        user_id, description, exclude_food_record_id=exclude_food_record_id
    )

    # 1. A corrected own-history match is the user's own truth -- top precedence,
    # and lets us skip the external calls entirely.
    if recall is not None and recall.is_corrected:
        return _recall_detail(recall)

    # 2. A branded restaurant item, grounded against that chain's OWN published
    # nutrition (AUTHORITATIVE), above generic USDA -- a chain's figure for its own
    # menu item beats a generic-food lookup. Owner-scoped + fail-open; returns None
    # for any non-branded food, so a plain food still flows to USDA/OFF below.
    restaurant = await restaurant_nutrition.lookup_restaurant(user_id, description)
    if restaurant is not None:
        return _fact_detail(restaurant)

    # 3/4. Published facts (USDA preferred over OFF). Each fails open to None.
    usda, off = await nutrition_sources.lookup_published_nutrition(description)
    if usda is not None:
        return _fact_detail(usda)
    if off is not None:
        return _fact_detail(off)

    # 5. An uncorrected prior log still grounds when nothing published matched.
    if recall is not None:
        return _recall_detail(recall)

    # 6. Pure vision.
    return None


async def suggest_identity(
    user_id: uuid.UUID,
    food_description: str | None,
) -> str | None:
    """Suggest a confirmable identity from the user's own history (Story 50.H2 AC4).

    Read-only own-history RAG recall used to PRE-FILL the identity field ("looks
    like your saved <X>") so a repeat food is a one-tap confirm. This is only a
    suggestion -- it never grounds anything by itself (that waits for the user to
    confirm); the safe fast path is the user confirming the suggestion. Returns
    the recalled food name, or None when nothing close enough was logged before.
    """
    if not settings.meal_intelligence_enabled:
        return None
    description = (food_description or "").strip()
    if not description:
        return None
    recall = await meal_rag.recall_similar_meal(user_id, description)
    return recall.name if recall is not None else None
