"""Own-history meal RAG: index logged foods and recall similar prior ones.

Story 50.E1, grounding mechanism (a): the user's own food history. A logged food
record (and its promoted common-food baseline) is indexed into ``knowledge_chunks``
at the ``USER_PROVIDED`` trust tier, owner-scoped. At estimate time the
vision-identified food is embedded and the user's similar prior foods are
retrieved by vector similarity -- "you've logged this before (~N g)" -- preferring
the user's corrected value.

This is *similarity* recall (vector), deliberately distinct from:
  * Story 50.F1's recent-meals injection, which is *temporal* (last 48 h), and
  * Story 50.E1's external research (USDA / Open Food Facts), which is a
    different trust tier (RESEARCHED / AUTHORITATIVE). The trust-tier model keeps
    the two grounding mechanisms architecturally separate (AC4).

Safety posture (NON-NEGOTIABLE): recall sharpens a *descriptive* estimate only.
Nothing here returns a dose, and the indexed chunks are never read by IoB /
treatment_safety / carb-ratio math. Indexing and retrieval are strictly
owner-scoped (``user_id`` equality), never shared across users.
"""

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.database import get_session_maker
from src.logging_config import get_logger
from src.models.common_food import CommonFood
from src.models.food_record import FoodRecord
from src.models.knowledge_chunk import KnowledgeChunk
from src.services.embedding import embed_text

logger = get_logger(__name__)

# Source-type vocabulary for every food-grounding chunk. Kept here as the single
# home so the clinical-knowledge retriever can exclude them (food grounding must
# not leak into clinical RAG prompts) and the external-source service can tag its
# cache chunks consistently.
SOURCE_TYPE_FOOD_RECORD = "user_food_record"
SOURCE_TYPE_COMMON_FOOD = "user_common_food"
SOURCE_TYPE_USDA = "usda_fdc"
SOURCE_TYPE_OPEN_FOOD_FACTS = "open_food_facts"
# Story 50.E2 restaurant grounding. Unlike USDA/OFF (shared, ``user_id IS NULL``),
# these cache chunks are OWNER-SCOPED (``user_id`` = the requesting user) because a
# chain's fetched values must not be pooled into a shared, redistributable mirror.
SOURCE_TYPE_RESTAURANT_CHAIN = "restaurant_chain"
SOURCE_TYPE_FATSECRET = "restaurant_fatsecret"

OWN_HISTORY_SOURCE_TYPES = frozenset({SOURCE_TYPE_FOOD_RECORD, SOURCE_TYPE_COMMON_FOOD})
EXTERNAL_SOURCE_TYPES = frozenset({SOURCE_TYPE_USDA, SOURCE_TYPE_OPEN_FOOD_FACTS})
# Restaurant grounding chunks are external published facts but cached owner-scoped;
# kept in their own set so own-history recall (which queries only
# OWN_HISTORY_SOURCE_TYPES) never matches them, while clinical retrieval still
# excludes them via FOOD_GROUNDING_SOURCE_TYPES below.
RESTAURANT_SOURCE_TYPES = frozenset(
    {SOURCE_TYPE_RESTAURANT_CHAIN, SOURCE_TYPE_FATSECRET}
)
# Every source_type used by the meal-grounding feature. Clinical retrieval
# excludes these so nutrition grounding never pollutes clinical knowledge
# prompts (the mechanisms stay separate -- AC4). Own-history recall narrows to
# OWN_HISTORY_SOURCE_TYPES, so restaurant/external chunks never surface there.
FOOD_GROUNDING_SOURCE_TYPES = (
    OWN_HISTORY_SOURCE_TYPES | EXTERNAL_SOURCE_TYPES | RESTAURANT_SOURCE_TYPES
)

# Cosine-distance ceiling for "this is the same food I logged before". Tighter
# than the clinical retriever's 0.6 (which casts a wide net for related
# material): a re-photographed known food embeds very close to its prior log, so
# we only treat a near match as own-history grounding.
RECALL_MAX_DISTANCE = 0.35

# Cap the embedded text so a long description can't blow the embedding model's
# input budget; the leading text carries the food identity.
_MAX_EMBED_CHARS = 512


@dataclass(frozen=True)
class MealRecall:
    """A prior logged food that closely matches the current estimate."""

    name: str
    carbs_low: float
    carbs_high: float
    is_corrected: bool
    food_record_id: str | None
    common_food_id: str | None
    distance: float


async def _embed(text: str) -> list[float] | None:
    """Embed text off the event loop; return None on any failure (best-effort).

    The embedding model is heavy and optional to the core estimate -- a failure
    here must degrade grounding gracefully, never break the upload.
    """
    cleaned = (text or "").strip()[:_MAX_EMBED_CHARS]
    if not cleaned:
        return None
    try:
        return await asyncio.to_thread(embed_text, cleaned)
    except Exception:
        logger.warning("Meal-RAG embedding failed", exc_info=True)
        return None


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


async def recall_similar_meal(
    user_id: uuid.UUID,
    food_description: str,
    *,
    exclude_food_record_id: uuid.UUID | str | None = None,
) -> MealRecall | None:
    """Return the user's closest prior logged food, or None.

    Owner-scoped vector search over the user's own food-history chunks only. The
    carb range comes from the chunk metadata (already the user's corrected value
    when one exists -- see ``index_food_record``).

    ``exclude_food_record_id`` drops the chunk for the record currently being
    grounded, so a freshly-uploaded record can't recall *itself* as history (its
    own chunk is indexed at upload). A common-food baseline carries
    ``common_food_id`` (not ``food_record_id``), so ``IS DISTINCT FROM`` is used
    to keep those rows rather than drop them on a NULL comparison.

    Ties on distance are broken deterministically: the user's **corrected** value
    wins, then the **most-recently** indexed -- so when a corrected and an
    uncorrected chunk for one food are equidistant or near-equidistant, grounding
    reliably prefers the correction instead of an implementation-defined row.

    Runs on its own short-lived session, decoupled from any caller transaction:
    embedding offloads to a worker thread, and reusing the request session across
    that boundary inside the ASGI server can break SQLAlchemy's async greenlet
    bridge. A dedicated session sidesteps that and keeps recall read-only.
    """
    embedding = await _embed(food_description)
    if embedding is None:
        return None

    distance = KnowledgeChunk.embedding.cosine_distance(embedding)
    conditions = [
        # Strictly owner-scoped: never another user's history, and never the
        # shared (NULL) clinical/external chunks.
        KnowledgeChunk.user_id == user_id,
        KnowledgeChunk.source_type.in_(OWN_HISTORY_SOURCE_TYPES),
        KnowledgeChunk.valid_to.is_(None),
        KnowledgeChunk.embedding.is_not(None),
        # Only chunks carrying a usable carb range (BOTH bounds) -- so the closest
        # match with complete metadata is chosen, not a closer-but-unusable row
        # that would then return None.
        KnowledgeChunk.metadata_json["carbs_low"].astext.isnot(None),
        KnowledgeChunk.metadata_json["carbs_high"].astext.isnot(None),
        distance < RECALL_MAX_DISTANCE,
    ]
    if exclude_food_record_id is not None:
        conditions.append(
            KnowledgeChunk.metadata_json["food_record_id"].astext.is_distinct_from(
                str(exclude_food_record_id)
            )
        )
    # Corrected (the user's truth) wins a distance tie; CASE maps the JSON bool to
    # 1/0 so a missing/false flag never sorts ahead of a corrected match.
    corrected_first = case(
        (KnowledgeChunk.metadata_json["is_corrected"].astext == "true", 1),
        else_=0,
    ).desc()
    # Full deterministic order: nearest, then corrected, then most-recent
    # (NULLS LAST so a missing timestamp can't outrank a real one), then a stable
    # tie-break on the PK so even an all-keys tie resolves to a single fixed row.
    ordering = (
        distance,
        corrected_first,
        KnowledgeChunk.retrieved_at.desc().nulls_last(),
        KnowledgeChunk.id,
    )
    try:
        async with get_session_maker()() as db:
            result = await db.execute(
                select(KnowledgeChunk, distance.label("distance"))
                .where(*conditions)
                .order_by(*ordering)
                .limit(1)
            )
            row = result.first()
    except Exception:
        logger.warning(
            "Meal-RAG recall query failed", user_id=str(user_id), exc_info=True
        )
        return None

    if row is None:
        return None

    chunk, dist = row
    meta = chunk.metadata_json or {}
    low = _coerce_float(meta.get("carbs_low"))
    high = _coerce_float(meta.get("carbs_high"))
    if low is None or high is None:
        return None

    return MealRecall(
        name=chunk.source_name or "a previously logged food",
        carbs_low=low,
        carbs_high=high,
        is_corrected=bool(meta.get("is_corrected")),
        food_record_id=meta.get("food_record_id"),
        common_food_id=meta.get("common_food_id"),
        distance=float(dist),
    )


async def _store_food_chunk(
    *,
    user_id: uuid.UUID,
    source_type: str,
    ref_key: str,
    ref_id: uuid.UUID,
    name: str,
    embed_source: str,
    metadata: dict,
) -> None:
    """Index (or re-index) a single food into a USER_PROVIDED chunk.

    Idempotent upsert keyed on the chunk's deterministic ``content_hash``
    (``sha256(source_type:ref_id)``), which is covered by the partial
    UNIQUE(content_hash, user_id) index (migration 050). A re-index (e.g. after a
    correction) updates the existing row in place via ``ON CONFLICT DO UPDATE`` --
    race-safe and without the delete-then-insert window. Runs on its own session
    so it never touches the caller's transaction -- indexing is a best-effort side
    effect that must not commit (or break) the caller's work.
    """
    embedding = await _embed(embed_source)
    if embedding is None:
        return

    now = datetime.now(UTC)
    content = name.strip()[:_MAX_EMBED_CHARS] or "logged food"
    content_hash = hashlib.sha256(f"{source_type}:{ref_id}".encode()).hexdigest()
    values = {
        "user_id": user_id,
        "trust_tier": KnowledgeChunk.TIER_USER_PROVIDED,
        "source_type": source_type,
        "source_name": content[:200],
        "content": content,
        "embedding": embedding,
        "content_hash": content_hash,
        "retrieved_at": now,
        "metadata_json": {ref_key: str(ref_id), **metadata},
    }
    stmt = pg_insert(KnowledgeChunk).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["content_hash", "user_id"],
        index_where=KnowledgeChunk.content_hash.isnot(None),
        set_={
            "source_name": stmt.excluded.source_name,
            "content": stmt.excluded.content,
            "embedding": stmt.excluded.embedding,
            "retrieved_at": stmt.excluded.retrieved_at,
            "metadata_json": stmt.excluded.metadata_json,
            "updated_at": now,
            "update_source": "meal_rag_reindex",
        },
    )
    async with get_session_maker()() as db:
        await db.execute(stmt)
        await db.commit()


def _record_effective_carbs(record: FoodRecord) -> tuple[float, float, bool]:
    """Prefer the user's corrected carbs (their truth) over the AI estimate."""
    if (
        record.corrected_carbs_low is not None
        and record.corrected_carbs_high is not None
    ):
        return record.corrected_carbs_low, record.corrected_carbs_high, True
    return record.carbs_low, record.carbs_high, False


async def index_food_record(record: FoodRecord) -> None:
    """Index a food record into own-history RAG (best-effort, owner-scoped).

    Embeds the food's identity so a re-photograph of the same food recalls it.
    Prefers the user's **confirmed** identity (Story 50.H2) over the AI-identified
    ``food_description`` -- so once the user corrects "soup" to "chili", a future
    photo recalls/suggests the user's truth, not the stale AI label. A record with
    no usable name is skipped. Reads already-loaded fields, persists on its own
    session.
    """
    description = (record.confirmed_food_name or record.food_description or "").strip()
    if not description:
        return
    low, high, corrected = _record_effective_carbs(record)
    user_id = record.user_id
    record_id = record.id
    common_food_id = str(record.common_food_id) if record.common_food_id else None
    try:
        await _store_food_chunk(
            user_id=user_id,
            source_type=SOURCE_TYPE_FOOD_RECORD,
            ref_key="food_record_id",
            ref_id=record_id,
            name=description,
            embed_source=description,
            metadata={
                "carbs_low": low,
                "carbs_high": high,
                "is_corrected": corrected,
                "common_food_id": common_food_id,
            },
        )
    except Exception:
        logger.warning(
            "Failed to index food record for recall",
            food_record_id=str(record_id),
            exc_info=True,
        )


async def index_common_food(common_food: CommonFood) -> None:
    """Index a common-food baseline into own-history RAG (best-effort).

    The named baseline is the user's curated truth for a frequently-eaten food;
    indexing it by name lets a future photo of that food recall the baseline.
    """
    user_id = common_food.user_id
    common_food_id = common_food.id
    name = common_food.name
    low = common_food.carbs_low
    high = common_food.carbs_high
    try:
        await _store_food_chunk(
            user_id=user_id,
            source_type=SOURCE_TYPE_COMMON_FOOD,
            ref_key="common_food_id",
            ref_id=common_food_id,
            name=name,
            embed_source=name,
            metadata={
                "carbs_low": low,
                "carbs_high": high,
                # A common food is the user's curated baseline -- treat it as the
                # corrected/preferred value for precedence.
                "is_corrected": True,
            },
        )
    except Exception:
        logger.warning(
            "Failed to index common food for recall",
            common_food_id=str(common_food_id),
            exc_info=True,
        )
