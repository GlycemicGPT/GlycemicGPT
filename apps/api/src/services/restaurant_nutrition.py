"""On-demand restaurant / fast-food grounding (Story 50.E2).

Grounding mechanism (c): a *branded chain* item -- e.g. a McDonald's Quarter
Pounder -- is grounded against **that chain's own published nutrition**, fetched
on demand for that one item via the per-chain fetcher registry below. This is the
one gap the open/CC0/ODbL sources (USDA / Open Food Facts, Story 50.E1) don't
cover, and commercial aggregators (Nutritionix, ...) don't fit a free, open,
self-hosted product (non-redistributable licences, no-cache terms, no shared key).

Legal / compliance posture (a maintainer policy decision, see the user docs):
  * Nutrition *facts* aren't copyrightable (Feist); a user-triggered single-item
    fetch is categorically distinct from the bulk scraping that lost hiQ.
  * We ship code (fetchers), never a licensed dataset -> redistributable.
  * The AC2 mitigations are HARD requirements and live in this module: respect
    ``robots.txt``; rate-limit with exponential back-off and a descriptive
    User-Agent; fetch only on a user action (an identity confirmation); and cache
    only the *requesting user's own* fetched values -- OWNER-SCOPED, never the
    shared ``user_id IS NULL`` mirror USDA/OFF use, and never a bulk pre-crawl.

Safety posture (NON-NEGOTIABLE): grounding sharpens the *descriptive* estimate
only. A chain's published carbs are **reference data, not an AI estimate**, so the
disclaimer carries the canonical ``NEVER_DOSE_PROHIBITION`` (the OFF pattern), not
the ``MEAL_ESTIMATE_QUALIFIER`` "AI guess" framing. Nothing here returns a dose,
and the result is never read by IoB / treatment_safety / carb-ratio math.

Identity gate (AC8): this module is only ever reached from
``meal_grounding.ground_estimate``, which runs after the food-identity gate -- so a
chain is fetched-and-cited only for a *confirmed-identity* item. A misidentified or
unconfirmed label stays vision-only and never gets an authoritative chain citation.

Brittleness is expected: chain endpoints are undocumented internal APIs that change
without notice. Every fetcher is isolated and fails open to ``None`` (vision-only),
never breaking logging. The shipped chain endpoint shapes are modelled, not
live-verified at build time; a maintainer canary (see the user docs) confirms each
live fetcher still parses and degrades to vision-only when it doesn't.
"""

import asyncio
import hashlib
import json
import re
import time
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.config import settings
from src.database import get_session_maker
from src.logging_config import get_logger
from src.models.knowledge_chunk import KnowledgeChunk
from src.services.meal_rag import SOURCE_TYPE_FATSECRET, SOURCE_TYPE_RESTAURANT_CHAIN
from src.services.nutrition_sources import NutritionFact, comorbidity_from_meta
from src.vision.carb_contract import (
    CARB_GRAMS_MAX,
    CARB_GRAMS_MIN,
    NEVER_DOSE_PROHIBITION,
    find_dosing_violations,
)

logger = get_logger(__name__)

# The figure is published reference data, NOT an AI estimate -- so reuse only the
# canonical dosing prohibition (single source of truth), never the
# MEAL_ESTIMATE_QUALIFIER "AI guess" framing which would mislabel a chain's own
# published facts (mirrors the OFF disclaimer in nutrition_sources.py).
_RESTAURANT_DISCLAIMER = (
    "Published nutrition from the restaurant's own menu data -- a descriptive "
    "reference only (figures vary by location, size, and preparation, and can be "
    f"out of date); {NEVER_DOSE_PROHIBITION}."
)

_USER_AGENT = "GlycemicGPT/1.0 (+restaurant-nutrition-grounding)"
_MAX_RESPONSE_BYTES = 512_000
# A restaurant item is per-item, not per-100 g, so its carbs are bounded by the
# absolute single-meal carb range (reject-not-clamp), NOT the per-100 g cap that
# USDA/OFF use.
_SERVING_PER_ITEM = "per item"

# Robots cache + per-host throttle/back-off windows (monotonic seconds).
_ROBOTS_CACHE_TTL_SECONDS = 3600.0
_BACKOFF_BASE_SECONDS = 30.0
_BACKOFF_MAX_SECONDS = 3600.0

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


# --------------------------------------------------------------------------- #
# Text normalization + brand detection
# --------------------------------------------------------------------------- #
def _normalize_query(query: str) -> str:
    return " ".join((query or "").lower().split())[:200]


def _canon(text: str) -> str:
    """Lower-case, fold accents (NFKD), strip punctuation, collapse whitespace.

    So "McDonald's" and "mcdonalds" both canonicalize to a space-delimited token
    stream that brand-alias matching can compare without apostrophe/case noise.
    Accent folding mirrors the hardened own-history matcher
    (``meal_estimate_aggregate``) so an accented menu name normalizes consistently.
    """
    folded = unicodedata.normalize("NFKD", (text or "").lower())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return _NON_ALNUM.sub(" ", folded).strip()


def _padded(text: str) -> str:
    return f" {text} "


def _contains_phrase(haystack_canon: str, needle_canon: str) -> bool:
    """Whole-token (space-bounded) phrase containment, so "mcd" never matches
    inside "mcdonalds" and "taco" never matches "tacopalooza"."""
    if not needle_canon:
        return False
    return _padded(needle_canon) in _padded(haystack_canon)


# --------------------------------------------------------------------------- #
# Per-host throttle + back-off + robots.txt (AC2 compliance mitigations)
# --------------------------------------------------------------------------- #
# host -> {"last": monotonic, "backoff_until": monotonic, "fails": int}
_host_state: dict[str, dict] = {}
# host -> asyncio.Lock serializing the rate-limit check+update for that host.
_host_locks: dict[str, asyncio.Lock] = {}
# host -> (RobotFileParser, expiry_monotonic)
_robots_cache: dict[str, tuple[RobotFileParser, float]] = {}


def _reset_state_for_tests() -> None:
    """Clear throttle + robots state. Test-only; keeps cases independent."""
    _host_state.clear()
    _host_locks.clear()
    _robots_cache.clear()


def _in_backoff(host: str) -> bool:
    st = _host_state.get(host)
    return bool(st and st.get("backoff_until", 0.0) > time.monotonic())


async def _respect_rate_limit(host: str) -> None:
    """Sleep just enough to honour the per-host minimum fetch interval.

    Serialized per host with an ``asyncio.Lock`` so two concurrent fetches to the
    same host can't both read a stale ``last`` and slip past the gate together --
    the second waits for the first's slot (the AC2 rate-limit is a per-host
    politeness guarantee, not best-effort). Different hosts use different locks, so
    there's no cross-host contention.
    """
    lock = _host_locks.setdefault(host, asyncio.Lock())
    async with lock:
        st = _host_state.setdefault(host, {})
        min_interval = settings.restaurant_min_seconds_between_fetches
        if min_interval > 0:
            wait = min_interval - (time.monotonic() - st.get("last", 0.0))
            if wait > 0:
                await asyncio.sleep(wait)
        st["last"] = time.monotonic()


def _note_success(host: str) -> None:
    st = _host_state.setdefault(host, {})
    st["fails"] = 0
    st["backoff_until"] = 0.0


def _note_backoff(host: str) -> None:
    """Record a rate-limit/unavailable response and arm exponential back-off."""
    st = _host_state.setdefault(host, {})
    fails = st.get("fails", 0) + 1
    st["fails"] = fails
    delay = min(_BACKOFF_BASE_SECONDS * (2 ** (fails - 1)), _BACKOFF_MAX_SECONDS)
    st["backoff_until"] = time.monotonic() + delay


def _host_allowed(url: str, allowed_hosts: frozenset[str]) -> bool:
    """True only for an https URL whose host is in the caller's allow-list.

    The hosts are operator-fixed per-chain config (never user input -- only the
    item query rides as an encoded param), so an exact-membership host allow-list
    plus https-only is the appropriate SSRF guard, mirroring nutrition_sources.
    """
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "") in allowed_hosts


async def _get_bytes(
    url: str,
    params: dict | None,
    *,
    allowed_hosts: frozenset[str],
    host: str,
    headers: dict | None = None,
    track_throttle: bool = True,
) -> bytes | None:
    """Stream a GET from an allow-listed https host, time-boxed + redirect-free.

    Returns the body bytes, or None on any error. The body is capped mid-stream
    (an oversized response is aborted, not buffered whole). A 429/503 arms the
    per-host back-off. Never logs the URL/params/exception text -- a FatSecret
    Bearer token or query param could ride there.

    ``track_throttle`` is False for the robots.txt fetch so that a side-channel
    request (robots) never resets or arms the *data* endpoint's back-off counter
    -- only real data fetches drive the per-host throttle state.
    """
    if not _host_allowed(url, allowed_hosts):
        logger.warning(
            "Restaurant fetch host not allow-listed", host=urlparse(url).hostname
        )
        return None
    request_headers = {"User-Agent": _USER_AGENT}
    if headers:
        request_headers.update(headers)
    try:
        async with (
            httpx.AsyncClient(
                timeout=settings.nutrition_grounding_timeout_seconds,
                follow_redirects=False,
                headers=request_headers,
            ) as client,
            client.stream("GET", url, params=params) as resp,
        ):
            if resp.status_code != 200:
                if track_throttle and resp.status_code in (429, 503):
                    _note_backoff(host)
                logger.warning("Restaurant source non-200", status=resp.status_code)
                return None
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > _MAX_RESPONSE_BYTES:
                    logger.warning("Restaurant response too large")
                    return None
                chunks.append(chunk)
    except Exception:
        # Never surface the exception text -- it can echo the URL incl. a token.
        logger.warning("Restaurant source request failed")
        return None
    if track_throttle:
        _note_success(host)
    return b"".join(chunks)


async def _robots_allows(url: str, allowed_hosts: frozenset[str]) -> bool:
    """Honour the host's robots.txt for our User-Agent (AC2), cached per host.

    An unreachable / absent robots.txt is treated as allow-all, matching the
    de-facto crawler convention (RobotFileParser's behaviour for empty input).
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    cached = _robots_cache.get(host)
    if cached is None or cached[1] <= time.monotonic():
        robots_url = f"{parsed.scheme}://{host}/robots.txt"
        raw = await _get_bytes(
            robots_url,
            None,
            allowed_hosts=allowed_hosts,
            host=host,
            track_throttle=False,
        )
        text = raw.decode("utf-8", errors="replace") if raw is not None else ""
        parser = RobotFileParser()
        parser.parse(text.splitlines())
        cached = (parser, time.monotonic() + _ROBOTS_CACHE_TTL_SECONDS)
        _robots_cache[host] = cached
    try:
        return cached[0].can_fetch(_USER_AGENT, url)
    except Exception:
        # A malformed robots file must not hard-fail the fetch path; fail open.
        return True


async def _fetch_json(
    url: str,
    params: dict | None,
    *,
    host: str,
    allowed_hosts: frozenset[str],
    headers: dict | None = None,
) -> dict | None:
    """Compliance-gated GET that returns parsed JSON, or None.

    Order: host allow-list -> back-off window -> robots.txt -> rate-limit -> fetch.
    Every gate fails open to None so a blocked/throttled/broken fetch degrades to
    vision-only, never an exception into the grounding orchestrator.
    """
    if not _host_allowed(url, allowed_hosts):
        logger.warning(
            "Restaurant fetch host not allow-listed", host=urlparse(url).hostname
        )
        return None
    if _in_backoff(host):
        logger.warning("Restaurant host in back-off; skipping fetch", host=host)
        return None
    if not await _robots_allows(url, allowed_hosts):
        logger.warning("Restaurant fetch disallowed by robots.txt", host=host)
        return None
    await _respect_rate_limit(host)
    raw = await _get_bytes(
        url, params, allowed_hosts=allowed_hosts, host=host, headers=headers
    )
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        logger.warning("Restaurant source returned non-JSON")
        return None
    return data if isinstance(data, dict) else None


# --------------------------------------------------------------------------- #
# Carb + response parsing helpers
# --------------------------------------------------------------------------- #
def _coerce_number(value: object) -> float | None:
    """Coerce a number or numeric string to a float, else None (no bounds applied).

    Shared by the carb and comorbidity parsers so their numeric coercion (reject
    bool; pull the first signed decimal out of a string) can never drift apart;
    each caller applies its own reject-not-clamp bound on top.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match:
            return float(match.group(0))
    return None


def _valid_item_carbs(value: object) -> float | None:
    """Per-item carbs within the absolute single-meal bounds, or None.

    Reject-not-clamp (CARB_GRAMS_MIN..CARB_GRAMS_MAX): a value outside the band
    signals bad/mis-parsed source data, so we drop it and fall back to vision-only
    rather than cite a wrong "published" number. ``GroundingDetail`` enforces the
    same bound at construction, so an out-of-range value would otherwise raise.
    """
    carbs = _coerce_number(value)
    if carbs is None or not (CARB_GRAMS_MIN <= carbs <= CARB_GRAMS_MAX):
        return None
    return carbs


def _carb_from_nutrients(
    nutrients: object, *, name_key: str, value_key: str
) -> float | None:
    """Scan a [{name, value}, ...] nutrient list for the carbohydrate entry."""
    if not isinstance(nutrients, list):
        return None
    for nutrient in nutrients:
        if not isinstance(nutrient, dict):
            continue
        name = str(nutrient.get(name_key) or "").lower()
        if "carbohydrate" in name or name in ("carbs", "total carbs"):
            return _valid_item_carbs(nutrient.get(value_key))
    return None


# A per-item meal's sodium (mg) is bounded by an implausible-but-finite ceiling
# (reject-not-clamp), distinct from the per-item gram bound the macros use.
_MAX_ITEM_SODIUM_MG = 100_000.0


def _comorbidity_from_nutrients(
    nutrients: object, *, name_key: str, value_key: str
) -> dict[str, float]:
    """Scan a [{name, value}, ...] nutrient list for the comorbidity fields.

    Per-item grams are bounded by the absolute single-meal carb range; sodium (mg)
    by its own ceiling. Added sugars is matched before total sugars so the two are
    never conflated, and total sugars excludes "sugar alcohol" / polyols (a distinct
    field that is not a sugar). Returns only the fields the chain actually published.
    """
    result: dict[str, float] = {}
    if not isinstance(nutrients, list):
        return result
    for nutrient in nutrients:
        if not isinstance(nutrient, dict):
            continue
        name = str(nutrient.get(name_key) or "").lower()
        amount = _coerce_number(nutrient.get(value_key))
        if amount is None:
            continue
        if "saturated" in name:
            if CARB_GRAMS_MIN <= amount <= CARB_GRAMS_MAX:
                result.setdefault("saturated_fat_grams", amount)
        elif "added" in name and "sugar" in name:
            if CARB_GRAMS_MIN <= amount <= CARB_GRAMS_MAX:
                result.setdefault("added_sugars_grams", amount)
        elif "sugar" in name and "alcohol" not in name and "polyol" not in name:
            if CARB_GRAMS_MIN <= amount <= CARB_GRAMS_MAX:
                result.setdefault("sugars_grams", amount)
        elif "sodium" in name:
            if 0.0 <= amount <= _MAX_ITEM_SODIUM_MG:
                result.setdefault("sodium_mg", amount)
    return result


def _best_item(items: object, *, name_key: str, item_query: str) -> dict | None:
    """Pick the response item that matches the requested item, or None.

    Prefers an item whose name contains every query token. The bare first-item
    fallback is used ONLY for a genuine single-item response: when a multi-item
    (search-style) response has no token match, returning ``items[0]`` would risk
    citing a *different* menu item's carbs as the chain's authoritative figure for
    the confirmed identity -- exactly the wrong-number-with-authority failure the
    identity gate exists to prevent. So a non-matching multi-item response degrades
    to None (vision-only) instead of guessing. Returns None when there are no items.
    """
    if not isinstance(items, list) or not items:
        return None
    dict_items = [it for it in items if isinstance(it, dict)]
    if not dict_items:
        return None
    query_tokens = [t for t in _canon(item_query).split() if t]
    if query_tokens:
        for item in dict_items:
            name_canon = _canon(str(item.get(name_key) or ""))
            if all(_contains_phrase(name_canon, tok) for tok in query_tokens):
                return item
        # Multiple candidates and none matched the confirmed item -> don't guess
        # which one the user meant; fall back to vision-only.
        if len(dict_items) > 1:
            return None
    return dict_items[0]


# --------------------------------------------------------------------------- #
# Per-chain fetchers (framework)
# --------------------------------------------------------------------------- #
class RestaurantChain:
    """One branded chain's on-demand nutrition fetcher.

    Subclasses declare brand aliases + allow-listed hosts and implement
    ``fetch_item`` (the chain-specific endpoint + parse). The shared SSRF guard,
    robots.txt, rate-limit/back-off, and owner-scoped caching live in the module
    around them, so a new chain only writes its request shape + parser. Every
    ``fetch_item`` must fail open to None (never raise) so a changed endpoint
    degrades to vision-only.

    NOTE (brittleness): the endpoint URL/shape below is modelled, not
    live-verified at build time. The maintainer canary (user docs) confirms it.
    """

    chain_id: str = ""
    display_name: str = ""
    citation_url: str | None = None
    hosts: frozenset[str] = frozenset()
    # Raw aliases; canonicalized once at class definition via ``_canon``.
    _raw_aliases: tuple[str, ...] = ()

    def __init__(self) -> None:
        self.aliases: tuple[str, ...] = tuple(
            _canon(alias) for alias in self._raw_aliases if _canon(alias)
        )

    def match(self, normalized_description: str) -> str | None:
        """Return the item text (brand stripped) if this chain owns the
        description, else None. An empty remainder (brand only, no item) is None
        -- there's nothing to look up."""
        canon = _canon(normalized_description)
        for alias in self.aliases:
            if _contains_phrase(canon, alias):
                remainder = _padded(canon).replace(_padded(alias), " ").strip()
                return remainder or None
        return None

    async def fetch_item(self, item_query: str) -> NutritionFact | None:
        raise NotImplementedError


class _McDonalds(RestaurantChain):
    chain_id = "mcdonalds"
    display_name = "McDonald's"
    citation_url = "https://www.mcdonalds.com/us/en-us/full-menu-explorer.html"
    hosts = frozenset({"www.mcdonalds.com"})
    _raw_aliases = ("mcdonalds", "mcdonald's", "mc donalds", "mcd")

    async def fetch_item(self, item_query: str) -> NutritionFact | None:
        # Modelled shape: an item-search JSON feed returning a nutrient list per
        # item. The query rides as an encoded param, never the path.
        data = await _fetch_json(
            "https://www.mcdonalds.com/dnaapp/itemNutrition",
            {"name": item_query, "country": "us", "language": "en"},
            host="www.mcdonalds.com",
            allowed_hosts=self.hosts,
        )
        if data is None:
            return None
        item = _best_item(
            data.get("items"), name_key="item_name", item_query=item_query
        )
        if item is None:
            return None
        carbs = _carb_from_nutrients(
            item.get("nutrient_facts"), name_key="name", value_key="value"
        )
        if carbs is None:
            return None
        comorbidity = _comorbidity_from_nutrients(
            item.get("nutrient_facts"), name_key="name", value_key="value"
        )
        name = (
            str(item.get("item_name") or item_query).strip()[:120] or item_query[:120]
        )
        return _build_fact(
            source_name=self.display_name,
            source_url=self.citation_url,
            name=name,
            carbs=carbs,
            comorbidity=comorbidity,
        )


class _Chipotle(RestaurantChain):
    chain_id = "chipotle"
    display_name = "Chipotle"
    citation_url = "https://www.chipotle.com/nutrition-calculator"
    hosts = frozenset({"www.chipotle.com"})
    _raw_aliases = ("chipotle",)

    async def fetch_item(self, item_query: str) -> NutritionFact | None:
        # Modelled shape: a menu-item nutrition endpoint returning a nutrition
        # list per item.
        data = await _fetch_json(
            "https://www.chipotle.com/api/nutrition/items",
            {"q": item_query},
            host="www.chipotle.com",
            allowed_hosts=self.hosts,
        )
        if data is None:
            return None
        item = _best_item(data.get("items"), name_key="itemName", item_query=item_query)
        if item is None:
            return None
        carbs = _carb_from_nutrients(
            item.get("nutrition"), name_key="name", value_key="value"
        )
        if carbs is None:
            return None
        comorbidity = _comorbidity_from_nutrients(
            item.get("nutrition"), name_key="name", value_key="value"
        )
        name = str(item.get("itemName") or item_query).strip()[:120] or item_query[:120]
        return _build_fact(
            source_name=self.display_name,
            source_url=self.citation_url,
            name=name,
            carbs=carbs,
            comorbidity=comorbidity,
        )


# Chains with a dedicated free fetcher.
_CHAINS: tuple[RestaurantChain, ...] = (_Chipotle(), _McDonalds())

# Known restaurant brands WITHOUT a dedicated fetcher: detecting one routes the
# item to the optional FatSecret BYO-key provider (broader commercial coverage),
# never to USDA/OFF -- a branded item is not a generic food. Kept small and
# data-driven; add a dedicated fetcher to graduate a brand off this list.
# Include punctuation-free spellings: ``_canon`` turns "wendy's" into "wendy s"
# and "chick-fil-a" into "chick fil a", which would NOT match a user typing
# "wendys" / "chickfila", so a branded item would silently skip restaurant
# grounding. List the common collapsed variants alongside the canonical names.
_EXTRA_BRANDS: frozenset[str] = frozenset(
    _canon(b)
    for b in (
        "taco bell",
        "starbucks",
        "wendy's",
        "wendys",
        "burger king",
        "subway",
        "kfc",
        "chick-fil-a",
        "chick fil a",
        "chickfila",
        "dunkin",
        "panera",
        "popeyes",
        "in-n-out",
        "in n out",
        "innout",
        "five guys",
    )
)

_ALL_BRAND_ALIASES: frozenset[str] = (
    frozenset(alias for chain in _CHAINS for alias in chain.aliases) | _EXTRA_BRANDS
)


def _build_fact(
    *,
    source_name: str,
    source_url: str | None,
    name: str,
    carbs: float,
    serving: str = _SERVING_PER_ITEM,
    comorbidity: dict | None = None,
) -> NutritionFact | None:
    """Build an AUTHORITATIVE reference fact, or None if the (source-controlled)
    item name carries dosing language.

    Defence in depth: the item name comes from an undocumented third-party
    endpoint that "changes without notice". If it ever contains dosing-style text
    (e.g. a tampered/changed feed returning "bolus 6u"), drop the grounding
    entirely rather than surface that text in the citation note returned to the
    client -- the same no-dosing-language boundary the rest of the meal pipeline
    enforces on generated/source text.

    ``comorbidity`` carries the optional comorbidity fields (saturated fat /
    sugars / added sugars / sodium) the chain published for this item.
    """
    if find_dosing_violations(name):
        logger.warning("Restaurant item name carried dosing language; dropping")
        return None
    return NutritionFact(
        source_name=source_name,
        source_url=source_url,
        trust_tier=KnowledgeChunk.TIER_AUTHORITATIVE,
        name=name,
        carbs_grams=carbs,
        serving=serving,
        disclaimer=_RESTAURANT_DISCLAIMER,
        **(comorbidity or {}),
    )


def _identify_chain(description: str) -> tuple[RestaurantChain, str] | None:
    normalized = _normalize_query(description)
    if not normalized:
        return None
    for chain in _CHAINS:
        item = chain.match(normalized)
        if item is not None:
            return chain, item
    return None


def _has_known_brand(description: str) -> bool:
    canon = _canon(description)
    return any(_contains_phrase(canon, alias) for alias in _ALL_BRAND_ALIASES)


# --------------------------------------------------------------------------- #
# Optional FatSecret BYO-key provider (AC5)
# --------------------------------------------------------------------------- #
# Fixed FatSecret host allow-list. Unlike the per-chain hosts (which are distinct
# from the URL under test), the FatSecret api/token URLs are operator config, so
# the allow-list is a CONSTANT here rather than derived from the URL it guards --
# otherwise the SSRF check would tautologically accept any misconfigured URL.
_FATSECRET_HOSTS: frozenset[str] = frozenset(
    {"platform.fatsecret.com", "oauth.fatsecret.com"}
)


async def _post_form_bytes(
    url: str, *, data: dict, auth: tuple[str, str]
) -> bytes | None:
    """Stream a form POST to an allow-listed https FatSecret host, capped + redirect-free.

    The one place a credential rides in the request body (Basic auth for the
    OAuth2 token exchange). The same SSRF host allow-list, size cap, redirect
    refusal, and no-logging guards as the GET path apply. Returns body bytes/None.
    """
    if not _host_allowed(url, _FATSECRET_HOSTS):
        logger.warning(
            "FatSecret POST host not allow-listed", host=urlparse(url).hostname
        )
        return None
    try:
        async with (
            httpx.AsyncClient(
                timeout=settings.nutrition_grounding_timeout_seconds,
                follow_redirects=False,
                headers={"User-Agent": _USER_AGENT},
            ) as client,
            client.stream("POST", url, data=data, auth=auth) as resp,
        ):
            if resp.status_code != 200:
                logger.warning("FatSecret token non-200", status=resp.status_code)
                return None
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > _MAX_RESPONSE_BYTES:
                    logger.warning("FatSecret token response too large")
                    return None
                chunks.append(chunk)
    except Exception:
        # Never log the exception -- the Basic-auth credentials ride in the request.
        logger.warning("FatSecret token request failed")
        return None
    return b"".join(chunks)


async def _fatsecret_token() -> str | None:
    """OAuth2 client-credentials token, or None. Key/secret never logged."""
    key = settings.fatsecret_consumer_key
    secret = settings.fatsecret_consumer_secret
    if not key or not secret:
        return None
    raw = await _post_form_bytes(
        settings.fatsecret_token_url,
        data={"grant_type": "client_credentials", "scope": "basic"},
        auth=(key, secret),
    )
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        logger.warning("FatSecret token returned non-JSON")
        return None
    token = payload.get("access_token") if isinstance(payload, dict) else None
    return token if isinstance(token, str) and token else None


# FatSecret v1 foods.search embeds nutrients in a description string, e.g.
# "Per 1 burrito - Calories: 1050kcal | Fat: 41.00g | Carbs: 122.00g | ...".
_FATSECRET_CARB_RE = re.compile(r"carbs?:\s*([\d.]+)\s*g", re.IGNORECASE)
_FATSECRET_SERVING_RE = re.compile(r"^\s*per\s+([^-|]+?)\s*[-|]", re.IGNORECASE)


async def _fetch_fatsecret(query: str) -> NutritionFact | None:
    """Query FatSecret for a branded item via the operator's BYO key, or None.

    Disabled (returns None) when no key is configured. Results are cached
    owner-scoped for at most ``fatsecret_cache_ttl_hours`` (<=24 h, FatSecret's
    value-cache ToS limit), never shared. Fails open to None.
    """
    token = await _fatsecret_token()
    if token is None:
        return None
    api_url = settings.fatsecret_api_url
    host = urlparse(api_url).hostname or ""
    data = await _fetch_json(
        api_url,
        {
            "method": "foods.search",
            "search_expression": query,
            "format": "json",
            "max_results": 1,
        },
        host=host,
        allowed_hosts=_FATSECRET_HOSTS,
        headers={"Authorization": f"Bearer {token}"},
    )
    if data is None:
        return None
    foods = (
        (data.get("foods") or {}).get("food")
        if isinstance(data.get("foods"), dict)
        else None
    )
    if isinstance(foods, dict):  # single result is an object, not a list
        foods = [foods]
    if not isinstance(foods, list) or not foods:
        return None
    food = foods[0]
    if not isinstance(food, dict):
        return None
    description = str(food.get("food_description") or "")
    carb_match = _FATSECRET_CARB_RE.search(description)
    if not carb_match:
        return None
    carbs = _valid_item_carbs(carb_match.group(1))
    if carbs is None:
        return None
    name = str(food.get("food_name") or query).strip()[:120] or query[:120]
    serving_match = _FATSECRET_SERVING_RE.search(description)
    serving = (
        serving_match.group(1).strip()[:60] if serving_match else _SERVING_PER_ITEM
    )
    food_id = food.get("food_id")
    source_url = (
        f"https://www.fatsecret.com/calories-nutrition/food/{food_id}"
        if food_id
        else "https://platform.fatsecret.com"
    )
    return _build_fact(
        source_name="FatSecret",
        source_url=source_url,
        name=name,
        carbs=carbs,
        serving=f"per {serving}" if not serving.lower().startswith("per") else serving,
    )


# --------------------------------------------------------------------------- #
# Owner-scoped cache (the key difference from USDA/OFF's shared mirror)
# --------------------------------------------------------------------------- #
# These mirror the nutrition_sources cache family deliberately rather than sharing
# a helper: the one axis that differs -- writing ``user_id = requester`` here vs
# ``user_id IS NULL`` (shared) there -- is the owner-scoping safety invariant
# (FM7). Folding both write paths into one scope-parameterized function would put a
# cross-user-leak regression one boolean apart, so the paths are kept physically
# separate on purpose.
def _cache_key(source_type: str, user_id: uuid.UUID, normalized_query: str) -> str:
    # user_id is folded in (belt-and-suspenders): two users querying the same item
    # get distinct rows, so a restaurant fetch can never leak across users even if
    # the user_id filter were ever loosened.
    return hashlib.sha256(
        f"{source_type}:{user_id}:{normalized_query}".encode()
    ).hexdigest()


async def _cache_get(
    user_id: uuid.UUID, source_type: str, normalized_query: str, *, ttl_hours: float
) -> NutritionFact | None:
    """Owner-scoped cache read; a stale row is lazily purged and counts as a miss.

    The lazy purge is what keeps a FatSecret value from being served (or retained)
    past its 24 h ToS window once it is next touched. Runs on a dedicated session
    (decoupled from the caller's request transaction).
    """
    content_hash = _cache_key(source_type, user_id, normalized_query)
    cutoff = datetime.now(UTC) - timedelta(hours=ttl_hours)
    try:
        async with get_session_maker()() as db:
            chunk = await db.scalar(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.user_id == user_id,
                    KnowledgeChunk.source_type == source_type,
                    KnowledgeChunk.content_hash == content_hash,
                    KnowledgeChunk.valid_to.is_(None),
                )
            )
            if chunk is None:
                return None
            if chunk.retrieved_at is None or chunk.retrieved_at < cutoff:
                await db.delete(chunk)
                await db.commit()
                return None
            meta = chunk.metadata_json or {}
            carbs = _valid_item_carbs(meta.get("carbs_grams"))
            if carbs is None:
                return None
            return NutritionFact(
                source_name=meta.get("source_name") or chunk.source_name or source_type,
                source_url=meta.get("source_url") or chunk.source_url,
                trust_tier=meta.get("trust_tier") or chunk.trust_tier,
                name=meta.get("name") or chunk.source_name or normalized_query,
                carbs_grams=carbs,
                serving=meta.get("serving") or _SERVING_PER_ITEM,
                disclaimer=meta.get("disclaimer"),
                # Per-item basis, so grams are bounded by the absolute carb ceiling.
                **comorbidity_from_meta(meta, grams_max=CARB_GRAMS_MAX),
            )
    except Exception:
        logger.warning("Restaurant cache lookup failed", source=source_type)
        return None


async def _cache_put(
    user_id: uuid.UUID,
    source_type: str,
    normalized_query: str,
    fact: NutritionFact,
    *,
    ttl_hours: float,
) -> None:
    """Store a fetched fact as an OWNER-SCOPED cache chunk (best-effort).

    ``user_id`` is the requesting user (never None) -- the owner-scoping that
    distinguishes restaurant caching from the shared USDA/OFF mirror. Idempotent
    upsert on the partial UNIQUE(content_hash, user_id) index (migration 050).

    Also actively purges this user's OWN expired rows for this ``source_type``, so
    a FatSecret value can't be *retained* at rest past its 24 h ToS window even if
    its exact key is never re-read (the read-side lazy purge alone would leave an
    unread stale row in place). A scheduled sweep would catch a user who never logs
    another item of this source; that broader retention pass is a follow-up.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=ttl_hours)
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
        "source_name": fact.source_name,
        "source_url": fact.source_url,
        "trust_tier": fact.trust_tier,
        # Persist any grounded comorbidity values (present keys only).
        **(fact.comorbidity_dict() or {}),
    }
    stmt = pg_insert(KnowledgeChunk).values(
        user_id=user_id,
        trust_tier=fact.trust_tier,
        source_type=source_type,
        source_url=fact.source_url,
        source_name=fact.source_name,
        content=content,
        embedding=None,
        content_hash=_cache_key(source_type, user_id, normalized_query),
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
        async with get_session_maker()() as db:
            await db.execute(stmt)
            # Purge this user's own expired rows for this source (retention cap).
            await db.execute(
                delete(KnowledgeChunk).where(
                    KnowledgeChunk.user_id == user_id,
                    KnowledgeChunk.source_type == source_type,
                    KnowledgeChunk.retrieved_at < cutoff,
                )
            )
            await db.commit()
    except Exception:
        logger.warning("Failed to cache restaurant fact", source=source_type)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
async def lookup_restaurant(user_id: uuid.UUID, query: str) -> NutritionFact | None:
    """Ground a confirmed branded-chain item against the chain's own nutrition.

    On-demand, item-scoped, OWNER-SCOPED-cached, identity-gated by the caller
    (``meal_grounding.ground_estimate`` only reaches here for a confirmed
    identity). Returns a ``NutritionFact`` (AUTHORITATIVE) or None -- None means
    "no branded match / fetch unavailable", and the caller falls back to USDA/OFF
    then vision-only. Restaurant grounding fires ONLY when a known restaurant
    brand is present in the identity: a generic food (no brand) is left to
    USDA/OFF, so a branded chain never overrides USDA for plain foods.

    Every internal step fails open to None; this function never raises.
    """
    if not settings.restaurant_grounding_enabled:
        return None
    normalized = _normalize_query(query)
    if not normalized:
        return None

    # 1. A chain with a dedicated fetcher: try its own published nutrition first.
    match = _identify_chain(query)
    if match is not None:
        chain, item_query = match
        cached = await _cache_get(
            user_id,
            SOURCE_TYPE_RESTAURANT_CHAIN,
            normalized,
            ttl_hours=settings.restaurant_cache_ttl_hours,
        )
        if cached is not None:
            return cached
        try:
            fact = await chain.fetch_item(item_query)
        except Exception:
            logger.warning("Restaurant chain fetch raised", chain=chain.chain_id)
            fact = None
        if fact is not None:
            await _cache_put(
                user_id,
                SOURCE_TYPE_RESTAURANT_CHAIN,
                normalized,
                fact,
                ttl_hours=settings.restaurant_cache_ttl_hours,
            )
            return fact
        # Dedicated fetch unavailable -> fall through to the FatSecret breadth path.

    # 2. A known brand without (or beyond) a dedicated fetcher: optional FatSecret
    #    BYO-key. No brand at all -> not a restaurant item -> leave it to USDA/OFF.
    if _has_known_brand(query):
        cached = await _cache_get(
            user_id,
            SOURCE_TYPE_FATSECRET,
            normalized,
            ttl_hours=settings.fatsecret_cache_ttl_hours,
        )
        if cached is not None:
            return cached
        try:
            fact = await _fetch_fatsecret(normalized)
        except Exception:
            logger.warning("FatSecret fetch raised")
            fact = None
        if fact is not None:
            await _cache_put(
                user_id,
                SOURCE_TYPE_FATSECRET,
                normalized,
                fact,
                ttl_hours=settings.fatsecret_cache_ttl_hours,
            )
            return fact

    return None
