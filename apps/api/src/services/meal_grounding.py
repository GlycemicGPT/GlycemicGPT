"""Grounding orchestrator: reconcile an estimate against history + published facts.

Story 50.E1, AC4. Given a vision-identified food, this picks the single best
grounding source in trust order and returns a descriptive citation. Precedence:

  1. own-history **corrected** value  (USER_PROVIDED -- the user's own truth)
  2. USDA FoodData Central             (AUTHORITATIVE -- official, CC0)
  3. Open Food Facts                   (RESEARCHED   -- crowd-sourced, ODbL)
  4. own-history **uncorrected** value (USER_PROVIDED -- a prior estimate)
  5. none -> pure vision

The two mechanisms stay architecturally distinct (own-history RAG vs external
research), separated by trust tier; this module only chooses between their
already-computed results.

Safety posture (NON-NEGOTIABLE): grounding sharpens the *descriptive* estimate
only. It returns a carb range + citation, never a dose, and the result is never
read by IoB / treatment_safety / carb-ratio math. The verify-before-dosing framing
is preserved by the callers (the persistent qualifier on every estimate surface).
"""

import uuid

from src.config import settings
from src.logging_config import get_logger
from src.models.knowledge_chunk import KnowledgeChunk
from src.schemas.food_record import GroundingDetail
from src.services import meal_rag, nutrition_sources

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
    )


async def ground_estimate(
    user_id: uuid.UUID,
    food_description: str | None,
) -> GroundingDetail | None:
    """Return the best grounding for a vision estimate, or None (pure vision).

    Decoupled from any caller transaction: the own-history recall and the external
    lookups each manage their own DB sessions and each fails open to None
    internally (``recall_similar_meal`` and ``lookup_published_nutrition`` never
    raise), so this orchestrator stays free of redundant try/except layers. The
    single hard fail-open boundary for any truly unexpected error is the caller
    (``food_vision._ground_estimate``).
    """
    # Defence in depth: the only caller is already flag-gated, but enforce the
    # feature flag at this boundary too so a future caller can't run grounding
    # (embedding + external fetch) while meal intelligence is off.
    if not settings.meal_intelligence_enabled:
        return None

    description = (food_description or "").strip()
    if not description:
        return None

    recall = await meal_rag.recall_similar_meal(user_id, description)

    # 1. A corrected own-history match is the user's own truth -- top precedence,
    # and lets us skip the external calls entirely.
    if recall is not None and recall.is_corrected:
        return _recall_detail(recall)

    # 2/3. Published facts (USDA preferred over OFF). Each fails open to None.
    usda, off = await nutrition_sources.lookup_published_nutrition(description)
    if usda is not None:
        return _fact_detail(usda)
    if off is not None:
        return _fact_detail(off)

    # 4. An uncorrected prior log still grounds when nothing published matched.
    if recall is not None:
        return _recall_detail(recall)

    # 5. Pure vision.
    return None
