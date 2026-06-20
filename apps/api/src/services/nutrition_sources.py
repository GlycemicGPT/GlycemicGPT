"""External published-nutrition grounding: USDA FoodData Central + Open Food Facts.

Story 50.E1, grounding mechanism (b): published nutrition *facts*. Generic foods
are grounded against **USDA FoodData Central** (CC0/public domain) and packaged
products against **Open Food Facts** (ODbL, no key). Both licences permit caching
and redistribution -- unlike commercial aggregators (Nutritionix, Edamam, ...) --
so a result is stored as a ``knowledge_chunks`` row (the cache + citation store)
at the ``AUTHORITATIVE`` (USDA) / ``RESEARCHED`` (OFF) trust tier, keeping it
architecturally separate from own-history (``USER_PROVIDED``) grounding (AC4).

These cache chunks are **shared** (``user_id IS NULL``) because the facts are
public and identical for everyone -- but they are deliberately tagged with a
food-grounding ``source_type`` that the clinical-knowledge retriever excludes, so
they never leak into a clinical RAG prompt.

Security: the base URLs are fixed operator config (never user input); only the
search term is user-influenced and it travels as an encoded query *parameter*,
never the path. Each call validates the host against an allow-list (defence in
depth vs a misconfigured base URL pointing at an internal service), refuses
redirects, is hard time-boxed, and caps the response body. The data.gov API key
is sent as a request parameter and is never logged. Any failure returns None so
the estimate falls back to vision-only.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_session_maker
from src.logging_config import get_logger
from src.models.knowledge_chunk import KnowledgeChunk
from src.services.meal_rag import SOURCE_TYPE_OPEN_FOOD_FACTS, SOURCE_TYPE_USDA
from src.vision.carb_contract import NEVER_DOSE_PROHIBITION, find_dosing_violations

logger = get_logger(__name__)

# Hosts we are willing to talk to. The base URL is operator config, so this is a
# defence-in-depth guard against a misconfiguration (or an injected env var)
# pointing the lookup at an internal/metadata endpoint.
_ALLOWED_HOSTS = frozenset(
    {
        "api.nal.usda.gov",
        "world.openfoodfacts.org",
        # Country sub-domains share the same search API + ODbL terms.
        "us.openfoodfacts.org",
    }
)

# Carbs per 100 g can never exceed 100 g; a value outside this band signals bad
# source data (wrong basis / parse error), so we drop it rather than ground on it.
_MAX_CARBS_PER_100G = 100.0

_MAX_RESPONSE_BYTES = 512_000

# USDA nutrient number for "Carbohydrate, by difference".
_USDA_CARB_NUTRIENT_NUMBER = "205"

# Restrict USDA to generic data types whose nutrient values are reported per
# 100 g (Branded items are per-serving and would break the per-100 g basis).
_USDA_GENERIC_DATATYPES = "Foundation,SR Legacy,Survey (FNDDS)"

# The safety prohibition is the canonical ``NEVER_DOSE_PROHIBITION`` (single source
# of truth); the rest is OFF-specific attribution + the not-medically-verified
# framing. Note the figure is published reference data, NOT an AI estimate, so the
# full ``MEAL_ESTIMATE_QUALIFIER`` ("AI estimate, often wrong ...") would mislabel
# it -- only the shared dosing prohibition is reused here.
_OFF_DISCLAIMER = (
    "Nutrition data from Open Food Facts (ODbL), contributed by volunteers and "
    f"not medically verified -- a descriptive reference only; {NEVER_DOSE_PROHIBITION}."
)

_SERVING_PER_100G = "per 100 g"


@dataclass(frozen=True)
class NutritionFact:
    """A grounded nutrition fact from a published source.

    The comorbidity fields -- saturated fat / sugars / added sugars /
    sodium -- are optional: present only when the source publishes them. They are
    blood-pressure / cardiovascular awareness data, never a dosing input.
    """

    source_name: str
    source_url: str | None
    trust_tier: str  # KnowledgeChunk.TIER_AUTHORITATIVE | TIER_RESEARCHED
    name: str
    carbs_grams: float
    serving: str
    disclaimer: str | None
    # Grounding-backed comorbidity nutrition; None when unpublished.
    saturated_fat_grams: float | None = None
    sugars_grams: float | None = None
    added_sugars_grams: float | None = None
    sodium_mg: float | None = None

    def comorbidity_dict(self) -> dict | None:
        """The present comorbidity values as a dict, or None when there are none."""
        present = {
            k: v
            for k, v in (
                ("saturated_fat_grams", self.saturated_fat_grams),
                ("sugars_grams", self.sugars_grams),
                ("added_sugars_grams", self.added_sugars_grams),
                ("sodium_mg", self.sodium_mg),
            )
            if v is not None
        }
        return present or None


def _normalize_query(query: str) -> str:
    return " ".join((query or "").lower().split())[:200]


def _cache_key(source_type: str, normalized_query: str) -> str:
    # Keyed on (source_type, normalized query) only -- it intentionally omits the
    # request shape (USDA dataType, OFF fields). If the *basis* of a result ever
    # changes (e.g. dropping the per-100 g dataType restriction), bump the
    # source_type constant so stale-basis cache rows are not reused.
    return hashlib.sha256(f"{source_type}:{normalized_query}".encode()).hexdigest()


def _host_allowed(base_url: str) -> bool:
    parsed = urlparse(base_url)
    return parsed.scheme == "https" and (parsed.hostname or "") in _ALLOWED_HOSTS


def _safe_off_citation_url(raw: object, code: object) -> str | None:
    """Return a trustworthy OFF citation URL, or the server-built fallback.

    The ``url`` field on an Open Food Facts product is volunteer-contributed, so
    it must not be cited verbatim -- a ``javascript:`` or off-domain link would be
    rendered to the user as "the source". Accept it only when it is an https
    openfoodfacts.org URL; otherwise fall back to the URL we construct ourselves
    from the product barcode.
    """
    if isinstance(raw, str):
        parsed = urlparse(raw)
        host = parsed.hostname or ""
        if parsed.scheme == "https" and (
            host == "openfoodfacts.org" or host.endswith(".openfoodfacts.org")
        ):
            return raw
    if code:
        return f"{settings.open_food_facts_base_url.rstrip('/')}/product/{code}"
    return None


def _valid_carbs(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    carbs = float(value)
    if not (0.0 <= carbs <= _MAX_CARBS_PER_100G):
        return None
    return carbs


# --- Comorbidity nutrition extraction -------------------------- #
# Per-100 g grams (saturated fat / sugars) can't exceed 100 g; sodium per 100 g
# is in mg and bounded by an implausible-but-finite ceiling (pure salt is ~38.8 g
# sodium / 100 g). Reject-not-clamp: a value past the ceiling signals bad/mis-parsed
# source data, so it is dropped rather than grounded on.
_MAX_GRAMS_PER_100G = 100.0
_MAX_SODIUM_MG_PER_100G = 100_000.0

# USDA FoodData Central nutrient numbers for the comorbidity fields.
_USDA_SATURATED_FAT_NUMBER = "606"
_USDA_ADDED_SUGARS_NUMBER = "539"
_USDA_SODIUM_NUMBER = "307"
# Total sugars shifted nutrient number between USDA datasets (269 / 269.3).
_USDA_TOTAL_SUGARS_NUMBERS = frozenset({"269", "269.3"})


def _bounded(value: object, *, maximum: float) -> float | None:
    """A finite, non-negative number within ``maximum``, else None (reject-not-clamp)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not (0.0 <= number <= maximum):
        return None
    return number


def _usda_comorbidity(food_nutrients: object) -> dict[str, float]:
    """Pull the comorbidity nutrients out of a USDA ``foodNutrients`` list.

    Returns only the fields the source actually published, each bounded per 100 g.
    Matched by USDA nutrient number first (stable), falling back to the nutrient
    name -- and added sugars is matched separately from total sugars so the two are
    never conflated.
    """
    result: dict[str, float] = {}
    if not isinstance(food_nutrients, list):
        return result
    for nutrient in food_nutrients:
        if not isinstance(nutrient, dict):
            continue
        number = str(nutrient.get("nutrientNumber") or "")
        name = str(nutrient.get("nutrientName") or "").lower()
        raw = nutrient.get("value")
        if number == _USDA_SATURATED_FAT_NUMBER or "saturated" in name:
            value = _bounded(raw, maximum=_MAX_GRAMS_PER_100G)
            if value is not None:
                result.setdefault("saturated_fat_grams", value)
        elif number == _USDA_ADDED_SUGARS_NUMBER or (
            # USDA names this "Sugars, added", so match both word orders rather than
            # the (never-matching) "added sugar" substring.
            "added" in name and "sugar" in name
        ):
            value = _bounded(raw, maximum=_MAX_GRAMS_PER_100G)
            if value is not None:
                result.setdefault("added_sugars_grams", value)
        elif number in _USDA_TOTAL_SUGARS_NUMBERS or (
            "sugars" in name and "added" not in name
        ):
            value = _bounded(raw, maximum=_MAX_GRAMS_PER_100G)
            if value is not None:
                result.setdefault("sugars_grams", value)
        elif number == _USDA_SODIUM_NUMBER or name == "sodium, na":
            value = _bounded(raw, maximum=_MAX_SODIUM_MG_PER_100G)
            if value is not None:
                result.setdefault("sodium_mg", value)
    return result


def comorbidity_from_meta(
    meta: dict, *, grams_max: float = _MAX_GRAMS_PER_100G
) -> dict[str, float]:
    """Reconstruct a cached fact's comorbidity values, each re-bounded.

    Defence in depth: although the cache is written by us, re-validate every value
    on read so a hand-edited / corrupted ``metadata_json`` can never resurrect an
    out-of-range comorbidity figure. Shared by the USDA/OFF (per-100 g) and
    restaurant (per-item) caches; ``grams_max`` is the gram ceiling for that basis.
    """
    result: dict[str, float] = {}
    for key in ("saturated_fat_grams", "sugars_grams", "added_sugars_grams"):
        value = _bounded(meta.get(key), maximum=grams_max)
        if value is not None:
            result[key] = value
    sodium = _bounded(meta.get("sodium_mg"), maximum=_MAX_SODIUM_MG_PER_100G)
    if sodium is not None:
        result["sodium_mg"] = sodium
    return result


def _off_comorbidity(product: dict) -> dict[str, float]:
    """Pull the comorbidity nutrients out of an Open Food Facts product.

    OFF reports per 100 g; sodium is in grams there, so it is converted to mg. When
    only salt is given, sodium is derived as ``salt / 2.5`` (the standard factor).
    OFF has no reliable added-sugars field, so that key is left unset.
    """
    result: dict[str, float] = {}
    sat = _bounded(product.get("saturated-fat_100g"), maximum=_MAX_GRAMS_PER_100G)
    if sat is not None:
        result["saturated_fat_grams"] = sat
    sugars = _bounded(product.get("sugars_100g"), maximum=_MAX_GRAMS_PER_100G)
    if sugars is not None:
        result["sugars_grams"] = sugars
    sodium_g = _bounded(product.get("sodium_100g"), maximum=_MAX_GRAMS_PER_100G)
    if sodium_g is not None:
        result["sodium_mg"] = sodium_g * 1000.0
    else:
        salt_g = _bounded(product.get("salt_100g"), maximum=_MAX_GRAMS_PER_100G)
        if salt_g is not None:
            result["sodium_mg"] = salt_g / 2.5 * 1000.0
    return result


async def _cache_get(
    db: AsyncSession, source_type: str, normalized_query: str
) -> NutritionFact | None:
    """Return a cached, still-valid fact for this query, or None."""
    content_hash = _cache_key(source_type, normalized_query)
    try:
        chunk = await db.scalar(
            select(KnowledgeChunk).where(
                KnowledgeChunk.source_type == source_type,
                KnowledgeChunk.user_id.is_(None),
                KnowledgeChunk.content_hash == content_hash,
                KnowledgeChunk.valid_to.is_(None),
            )
        )
    except Exception:
        logger.warning("Nutrition cache lookup failed", source=source_type)
        return None
    if chunk is None:
        return None
    meta = chunk.metadata_json or {}
    carbs = _valid_carbs(meta.get("carbs_grams"))
    if carbs is None:
        return None
    return NutritionFact(
        source_name=chunk.source_name or source_type,
        source_url=chunk.source_url,
        trust_tier=chunk.trust_tier,
        name=meta.get("name") or chunk.source_name or normalized_query,
        carbs_grams=carbs,
        serving=meta.get("serving") or _SERVING_PER_100G,
        disclaimer=meta.get("disclaimer"),
        **comorbidity_from_meta(meta),
    )


async def _cache_put(
    db: AsyncSession,
    *,
    source_type: str,
    normalized_query: str,
    fact: NutritionFact,
) -> None:
    """Store a fetched fact as a shared, cite-able cache chunk (best-effort).

    The chunk is not embedded: it is keyed by ``content_hash`` for cache reuse and
    is excluded from clinical retrieval, so a vector is unnecessary. Idempotent
    upsert on the partial UNIQUE(content_hash, user_id) index (migration 050), so
    two concurrent first-time lookups for the same query update rather than one
    silently losing the write on an IntegrityError.
    """
    now = datetime.now(UTC)
    # A published nutrition name should never contain dosing/advice phrasing; if
    # it somehow does, flag it (defence in depth -- these chunks are not fed to a
    # model today, but a future reader should not trust the name blindly).
    injection_risk = bool(find_dosing_violations(fact.name))
    content = (
        f"{fact.name}: ~{fact.carbs_grams:g} g carbohydrate {fact.serving} "
        f"({fact.source_name})"
    )[:1000]
    metadata = {
        "query": normalized_query,
        "name": fact.name,
        "carbs_grams": fact.carbs_grams,
        "serving": fact.serving,
        "disclaimer": fact.disclaimer,
        # Persist any grounded comorbidity values so a cache hit
        # surfaces them too (only the present keys are written).
        **(fact.comorbidity_dict() or {}),
    }
    stmt = pg_insert(KnowledgeChunk).values(
        user_id=None,
        trust_tier=fact.trust_tier,
        source_type=source_type,
        source_url=fact.source_url,
        source_name=fact.source_name,
        content=content,
        embedding=None,
        content_hash=_cache_key(source_type, normalized_query),
        retrieved_at=now,
        injection_risk=injection_risk,
        metadata_json=metadata,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["content_hash", "user_id"],
        index_where=KnowledgeChunk.content_hash.isnot(None),
        set_={
            "trust_tier": stmt.excluded.trust_tier,
            "source_url": stmt.excluded.source_url,
            "source_name": stmt.excluded.source_name,
            "content": stmt.excluded.content,
            "retrieved_at": stmt.excluded.retrieved_at,
            "injection_risk": stmt.excluded.injection_risk,
            "metadata_json": stmt.excluded.metadata_json,
            "updated_at": now,
        },
    )
    try:
        await db.execute(stmt)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.warning("Failed to cache nutrition fact", source=source_type)


async def _get_json(base_url: str, path: str, params: dict) -> dict | None:
    """Fetch JSON from an allow-listed host, time-boxed and redirect-free.

    Returns the parsed object, or None on any error (the caller falls back to
    vision-only). Never logs the URL or params (the data.gov key rides in params).
    """
    if not _host_allowed(base_url):
        logger.warning("Nutrition base URL host not allow-listed", source=path)
        return None
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        # Stream so an oversized body is aborted mid-transfer, not buffered whole
        # into memory and only then rejected.
        async with (
            httpx.AsyncClient(
                timeout=settings.nutrition_grounding_timeout_seconds,
                follow_redirects=False,
                headers={"User-Agent": "GlycemicGPT/1.0 (+nutrition-grounding)"},
            ) as client,
            client.stream("GET", url, params=params) as resp,
        ):
            if resp.status_code != 200:
                logger.warning("Nutrition source non-200", status=resp.status_code)
                return None
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > _MAX_RESPONSE_BYTES:
                    logger.warning("Nutrition response too large")
                    return None
                chunks.append(chunk)
        data = json.loads(b"".join(chunks))
    except Exception:
        # Never surface the exception text -- it can echo the URL incl. the key.
        logger.warning("Nutrition source request failed")
        return None
    return data if isinstance(data, dict) else None


async def lookup_usda(query: str) -> NutritionFact | None:
    """Ground a generic food against USDA FoodData Central (CC0).

    Skipped (returns None) when no data.gov key is configured. Cached results are
    reused before any HTTP call. Cache reads/writes run on a dedicated session so
    grounding never commits the caller's request transaction.
    """
    normalized = _normalize_query(query)
    if not normalized or not settings.usda_fdc_api_key:
        return None

    async with get_session_maker()() as db:
        cached = await _cache_get(db, SOURCE_TYPE_USDA, normalized)
    if cached is not None:
        return cached

    data = await _get_json(
        settings.usda_fdc_base_url,
        "foods/search",
        {
            "api_key": settings.usda_fdc_api_key,
            "query": query,
            "pageSize": 1,
            "dataType": _USDA_GENERIC_DATATYPES,
        },
    )
    if data is None:
        return None
    foods = data.get("foods")
    if not isinstance(foods, list) or not foods:
        return None
    food = foods[0]
    if not isinstance(food, dict):
        return None

    carbs = None
    for nutrient in food.get("foodNutrients") or []:
        if not isinstance(nutrient, dict):
            continue
        number = str(nutrient.get("nutrientNumber") or "")
        name = str(nutrient.get("nutrientName") or "").lower()
        # Match "Carbohydrate, by difference" specifically -- not e.g.
        # "Carbohydrate, other" -- so the per-100 g total carb is used.
        if (
            number == _USDA_CARB_NUTRIENT_NUMBER
            or name == "carbohydrate, by difference"
        ):
            carbs = _valid_carbs(nutrient.get("value"))
            break
    if carbs is None:
        return None

    fdc_id = food.get("fdcId")
    comorbidity = _usda_comorbidity(food.get("foodNutrients"))
    fact = NutritionFact(
        source_name="USDA FoodData Central",
        source_url=(
            f"https://fdc.nal.usda.gov/fdc-app.html#/food-details/{fdc_id}/nutrients"
            if fdc_id
            else None
        ),
        trust_tier=KnowledgeChunk.TIER_AUTHORITATIVE,
        name=str(food.get("description") or query)[:120],
        carbs_grams=carbs,
        serving=_SERVING_PER_100G,
        disclaimer=None,
        **comorbidity,
    )
    async with get_session_maker()() as db:
        await _cache_put(
            db, source_type=SOURCE_TYPE_USDA, normalized_query=normalized, fact=fact
        )
    return fact


async def lookup_open_food_facts(query: str) -> NutritionFact | None:
    """Ground a packaged product against Open Food Facts (ODbL, no key).

    OFF's real strength is barcode lookup; a name/text search is used here. (A
    barcode-scan input is a noted future enhancer, out of scope for 50.E1.)
    Attribution + the non-medical disclaimer ride on the returned fact. Cache
    reads/writes run on a dedicated session (decoupled from the caller).
    """
    normalized = _normalize_query(query)
    if not normalized or not settings.open_food_facts_enabled:
        return None

    async with get_session_maker()() as db:
        cached = await _cache_get(db, SOURCE_TYPE_OPEN_FOOD_FACTS, normalized)
    if cached is not None:
        return cached

    data = await _get_json(
        settings.open_food_facts_base_url,
        "cgi/search.pl",
        {
            "search_terms": query,
            "search_simple": 1,
            "action": "process",
            "json": 1,
            "page_size": 1,
            "fields": (
                "product_name,carbohydrates_100g,code,url,"
                # Comorbidity fields (per 100 g; sodium in grams here).
                "saturated-fat_100g,sugars_100g,sodium_100g,salt_100g"
            ),
        },
    )
    if data is None:
        return None
    products = data.get("products")
    if not isinstance(products, list) or not products:
        return None
    product = products[0]
    if not isinstance(product, dict):
        return None

    carbs = _valid_carbs(product.get("carbohydrates_100g"))
    if carbs is None:
        return None

    name = str(product.get("product_name") or query).strip()[:120]
    if not name:
        name = query[:120]
    source_url = _safe_off_citation_url(product.get("url"), product.get("code"))
    comorbidity = _off_comorbidity(product)
    fact = NutritionFact(
        source_name="Open Food Facts",
        source_url=source_url,
        trust_tier=KnowledgeChunk.TIER_RESEARCHED,
        name=name,
        carbs_grams=carbs,
        serving=_SERVING_PER_100G,
        disclaimer=_OFF_DISCLAIMER,
        **comorbidity,
    )
    async with get_session_maker()() as db:
        await _cache_put(
            db,
            source_type=SOURCE_TYPE_OPEN_FOOD_FACTS,
            normalized_query=normalized,
            fact=fact,
        )
    return fact


async def lookup_published_nutrition(
    query: str,
) -> tuple[NutritionFact | None, NutritionFact | None]:
    """Run the USDA and OFF lookups concurrently, each failing open to None.

    Each lookup uses its own session (see above), so running them concurrently is
    safe -- they never share a connection.
    """

    async def _safe(coro):
        try:
            return await coro
        except Exception:
            logger.warning("Nutrition lookup raised", exc_info=True)
            return None

    usda, off = await asyncio.gather(
        _safe(lookup_usda(query)),
        _safe(lookup_open_food_facts(query)),
    )
    return usda, off
