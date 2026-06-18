"""Multi-sample aggregation for vision carb estimates (Story 50.H1).

The research-driven amendment (2026-06-15): a model's *self-reported* confidence
is uncorrelated with accuracy (diabettech's 27,000-run study measured r ~= -0.01,
with accuracy *declining* above 0.85 self-reported confidence). The only
validated uncertainty signal is **querying the same photo several times and
observing how much the answers disagree.** So the pipeline now samples one image
N times and this module turns those N samples into:

  * an **empirical carb range** from the observed spread (not one response's
    self-described range), and
  * an **empirical confidence band** from the dispersion (coefficient of
    variation) of the samples, NOT the model's self-reported confidence, and
  * an **identity-agreement** signal: when the samples disagree on *what the
    food is* (the dominant, upstream error), that is surfaced as low confidence
    and flagged so the 50.H2 identity-confirmation gate is required before any
    grounding can certify a label.

Safety posture (NON-NEGOTIABLE):
  * Consistency is NOT correctness. A tight spread must never be presented as
    "safe to dose" -- a systematically-wrong-but-consistent estimate (the study's
    cheese-sandwich class) would have low dispersion yet be wrong. The
    never-dose-or-bolus framing stays dominant regardless of dispersion; this
    module never emits a dose and nothing here is read by IoB / treatment_safety.
  * The model's self-reported confidence is retained ONLY as internal audit/eval
    data (for 50.H3), never surfaced as a user-facing safety signal.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass, field

from src.vision.carb_contract import (
    CARB_GRAMS_MAX,
    CARB_GRAMS_MIN,
    ParsedEstimate,
)

# Coefficient-of-variation thresholds mapping sample dispersion -> a confidence
# band. Deliberately conservative: anything but tight agreement lands at medium
# or low. These are the H1 starting points; 50.H4's variance harness tunes them
# (and N) against the accuracy-vs-cost curve.
_CV_HIGH_MAX = 0.10  # CV below this -> tight agreement -> "high"
_CV_MEDIUM_MAX = 0.25  # CV below this -> "medium"; at/above -> "low"

# A "high" band needs enough draws to be evidence of stability, not luck: two
# agreeing samples is just the lucky/unlucky-draw problem one level up (and a
# single tolerated partial failure routinely leaves exactly two). So "high"
# requires at least this many usable samples; fewer caps at "medium".
_MIN_SAMPLES_FOR_HIGH = 3

# Confidence bands (mirror carb_contract.CONFIDENCE_LEVELS ordering).
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

# Upper bound on content tokens compared per description (DoS guard for the
# O(tokens^2) identity match; a food identity never needs this many).
_MAX_IDENTITY_TOKENS = 24

# Common filler words stripped before comparing food identities, so "a plate of
# grilled chicken" and "grilled chicken breast" still cluster together.
_IDENTITY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "with",
        "and",
        "on",
        "in",
        "plate",
        "bowl",
        "serving",
        "some",
        "dish",
        "food",
        "meal",
        "fresh",
        "homemade",
    }
)


@dataclass(frozen=True)
class SampleRecord:
    """One vision sample's salient values, retained for 50.H3 audit.

    ``self_reported_confidence`` is captured for audit/eval ONLY -- it is never
    surfaced as a user-facing safety signal (the whole point of H1).
    """

    carbs_low: float | None
    carbs_high: float | None
    midpoint: float | None
    food_description: str
    self_reported_confidence: str | None
    parse_ok: bool


@dataclass(frozen=True)
class AggregatedEstimate:
    """The aggregate of N vision samples for one photo.

    ``carbs_low`` / ``carbs_high`` are the empirical band; ``confidence`` is the
    dispersion-derived band (never self-reported). ``samples`` is the raw
    per-sample audit data (for 50.H3 retention).
    """

    carbs_low: float
    carbs_high: float
    confidence: str
    food_description: str
    nutrition: dict
    dispersion_cv: float | None
    identity_agreement: bool
    distinct_identities: list[str]
    samples_requested: int
    samples_ok: int
    wide_spread: bool
    samples: list[SampleRecord] = field(default_factory=list)


def _sample_in_bounds(sample: ParsedEstimate) -> bool:
    """True when a sample's carb range is present and within absolute bounds."""
    low, high = sample.carbs_low, sample.carbs_high
    return (
        low is not None
        and high is not None
        and CARB_GRAMS_MIN <= low <= high <= CARB_GRAMS_MAX
    )


def _strip_accents(text: str) -> str:
    """Drop combining marks so "creme brulee" matches "crème brûlée"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _identity_tokens(description: str) -> frozenset[str]:
    """Normalize a food description to a comparable, stopword-stripped token set.

    Accents are folded (NFKD) before tokenizing so unicode spelling variants of
    the same food ("crème brûlée" / "creme brulee") share tokens instead of
    reading as different foods. The content tokens are capped at
    ``_MAX_IDENTITY_TOKENS``: ``_identity_match`` is O(tokens_a * tokens_b) per pair
    and clustering is O(N^2) pairs, so an unbounded model description (the raw,
    pre-storage-cap sidecar text) would be a synchronous CPU sink -- and a food
    identity never needs that many content tokens, only the leading ones carry it.
    """
    normalized = _strip_accents(description or "").lower()
    tokens = re.findall(r"[a-z0-9]+", normalized)
    content = [t for t in tokens if t not in _IDENTITY_STOPWORDS]
    return frozenset(content[:_MAX_IDENTITY_TOKENS])


def _plural_eq(a: str, b: str) -> bool:
    """Token equality tolerant of simple English pluralization.

    Compares by suffix *addition* only (never stripping), so "potato" matches
    "potatoes" (potato + "es") and "apple" matches "apples" (apple + "s") without
    over-stripping that would collapse "apples" back to "appl". It can still
    over-ADD on short words (any word that is another word plus "s"/"es" collapses,
    e.g. "bus"/"buses"), but those are not plausible food-identity tokens, so it is
    good enough for the food nouns that drive identity here. Mirrors the eval
    harness helper (``evals/vision_carb/metrics.py``).
    """
    if a == b:
        return True
    longer, shorter = (a, b) if len(a) > len(b) else (b, a)
    return longer in (shorter + "s", shorter + "es")


def _identity_match(a: frozenset[str], b: frozenset[str]) -> bool:
    """True when two descriptions name the same food, by token containment.

    The shorter token set is the candidate "name"; it matches when **all** of its
    content tokens appear (plural-tolerant) in the longer set -- i.e. the terse
    description is fully contained in the verbose one. Unlike the original
    symmetric Jaccard this does not collapse when one description is far more
    verbose than the other (a terse "banana" is fully contained in "a ripe banana
    with brown speckles on the peel"), which was the bug this hardening fixes:
    the same food read two ways scored low Jaccard and read as disagreement.

    Full containment (rather than a partial-overlap ratio) keeps the safe
    direction intact: two genuinely different multi-token names that merely share a
    common noun -- "chicken salad" vs "chicken soup", "beef taco" vs "fish taco" --
    are NOT fully contained, so they correctly disagree (a partial ratio would have
    matched them on the one shared token). Disjoint sets ("creme brulee" vs "crema
    catalana") never match.

    This is the same all-content-tokens rule the offline variance harness uses
    (``evals/vision_carb/metrics.py`` ``_identity_matches``); the harness applies it
    against a curated ground-truth name, while here -- with no ground truth -- it is
    applied symmetrically between two unlabeled samples, the shorter as the
    candidate name. Normalization (NFKD accent folding, stopwords, ``_plural_eq``)
    is shared with that harness; the threshold choice is not (the harness has no
    ratio, it requires all tokens, which is what this now does).

    Residual: a single generic token that is fully contained in an unrelated dish
    ("rice" in "fried rice with shrimp") still matches -- structurally identical to
    the legitimate terse-vs-verbose case ("banana" in "...banana..."), so it cannot
    be distinguished without a food ontology. This is the conservative direction
    (it only inflates the empirical confidence band / suppresses the "confirm the
    food" UX note; external grounding is gated on user identity confirmation, never
    on this signal) and is rare for N samples of one photo.

    Two empty token sets count as a match (mirrors the old semantics: no identity
    evidence either way, so not manufactured disagreement); one empty and one
    non-empty never match.
    """
    if not a and not b:
        return True
    if not a or not b:
        return False
    smaller, larger = (a, b) if len(a) <= len(b) else (b, a)
    return all(any(_plural_eq(token, other) for other in larger) for token in smaller)


def _largest_identity_cluster(
    descriptions: list[str],
) -> tuple[list[int], list[str]]:
    """Greedily cluster sample descriptions by identity similarity.

    Returns ``(indices_of_largest_cluster, distinct_identity_labels)``. A simple
    greedy single-link clustering is enough here: we only need "do the samples
    largely agree on the food, and which one represents the majority", not a
    perfect partition.
    """
    token_sets = [_identity_tokens(d) for d in descriptions]
    clusters: list[list[int]] = []
    for i, tokens in enumerate(token_sets):
        placed = False
        for cluster in clusters:
            # True single-link: match if this sample is close to ANY member, so
            # transitive matches (A≈B, B≈C) aren't split into false disagreement.
            # With full-containment matching, chaining needs a real subset relation
            # at each hop, so distinct multi-token foods sharing one noun no longer
            # bridge (only a fully-contained terse name, e.g. a bare head noun, can).
            if any(_identity_match(tokens, token_sets[idx]) for idx in cluster):
                cluster.append(i)
                placed = True
                break
        if not placed:
            clusters.append([i])

    largest = max(clusters, key=len) if clusters else []
    distinct = [
        descriptions[c[0]].strip() for c in clusters if descriptions[c[0]].strip()
    ]
    return largest, distinct


def _confidence_from_cv(cv: float | None, samples_ok: int) -> str:
    """Map sample dispersion to a confidence band.

    A single usable sample cannot measure dispersion at all, and two agreeing
    samples are weak evidence of stability, so "high" requires both tight
    agreement AND at least ``_MIN_SAMPLES_FOR_HIGH`` usable samples -- the
    lucky/unlucky-draw problem multi-sampling exists to expose. A 2-sample run
    can reach at most "medium".
    """
    if samples_ok <= 1 or cv is None:
        return CONFIDENCE_LOW
    if cv < _CV_HIGH_MAX and samples_ok >= _MIN_SAMPLES_FOR_HIGH:
        return CONFIDENCE_HIGH
    if cv < _CV_MEDIUM_MAX:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _pick_representative(
    ok_samples: list[ParsedEstimate], cluster_indices: list[int]
) -> ParsedEstimate:
    """Choose the sample whose midpoint is the cluster's median.

    Its description + nutrition represent the aggregate. Using the median (not the
    first) avoids letting a tail-outlier sample's prose stand in for the group.
    """
    cluster = [ok_samples[i] for i in cluster_indices] or ok_samples
    with_midpoint = [s for s in cluster if s.midpoint is not None]
    if not with_midpoint:
        return cluster[0]
    with_midpoint.sort(key=lambda s: s.midpoint or 0.0)
    return with_midpoint[len(with_midpoint) // 2]


def aggregate_samples(
    samples: list[ParsedEstimate],
    *,
    samples_requested: int,
) -> AggregatedEstimate | None:
    """Aggregate N parsed vision samples into one empirical estimate.

    Returns ``None`` when no sample is usable (the caller raises a clear error
    rather than persisting a fabricated estimate). Uses only the samples that
    parsed into an in-range numeric estimate; a failed/partial sample degrades
    gracefully (AC6).
    """
    audit = [
        SampleRecord(
            carbs_low=s.carbs_low,
            carbs_high=s.carbs_high,
            midpoint=s.midpoint,
            food_description=s.food_description,
            self_reported_confidence=s.confidence,
            parse_ok=s.parse_ok,
        )
        for s in samples
    ]

    # Reject-not-clamp, enforced PER SAMPLE (AC7): a single hallucinated
    # out-of-range sample is dropped here so it can't poison the union band or
    # the dispersion. If every sample is unusable, return None (the caller raises
    # a clear error rather than persisting a fabricated estimate).
    ok = [s for s in samples if s.parse_ok and _sample_in_bounds(s)]
    if not ok:
        return None

    # Empirical band = the union of every usable sample's own range. This folds
    # both each sample's stated uncertainty AND cross-sample disagreement into
    # one honest band: wide when the model contradicts itself, tight only when
    # every look agrees.
    carbs_low = min(s.carbs_low for s in ok)  # type: ignore[type-var]
    carbs_high = max(s.carbs_high for s in ok)  # type: ignore[type-var]

    # Dispersion is measured on the per-sample point estimates (midpoints): the
    # run-to-run swing the study cares about. Uses the unbiased sample stdev
    # (N-1) -- these N draws are a *sample* of the model's output distribution,
    # not the whole population, and at the small N this runs (2-3) the population
    # stdev would understate the true spread and lean optimistic. Needs >=2
    # samples and a non-zero mean to be meaningful.
    midpoints = [s.midpoint for s in ok if s.midpoint is not None]
    cv: float | None = None
    if len(midpoints) >= 2:
        mean = statistics.fmean(midpoints)
        if mean > 0:
            cv = statistics.stdev(midpoints) / mean

    # Identity agreement is judged ONLY over samples that still have a usable
    # description: a description emptied by the dosing scrub carries no identity
    # signal, so it must not count as a distinct "disagreeing" food (which would
    # surface a misleading "the AI couldn't agree what this is" to the user).
    described_indices = [i for i, s in enumerate(ok) if s.food_description.strip()]
    if described_indices:
        local_cluster, distinct = _largest_identity_cluster(
            [ok[i].food_description for i in described_indices]
        )
        largest_cluster = [described_indices[j] for j in local_cluster]
        # A strict majority of *described* samples sharing one identity = agreement.
        identity_agreement = len(largest_cluster) * 2 > len(described_indices)
    else:
        # No description survived to compare -- no evidence of disagreement.
        largest_cluster = []
        distinct = []
        identity_agreement = True

    confidence = _confidence_from_cv(cv, len(ok))
    if not identity_agreement:
        confidence = CONFIDENCE_LOW

    wide_spread = (cv is not None and cv >= _CV_MEDIUM_MAX) or not identity_agreement

    representative = _pick_representative(ok, largest_cluster)

    return AggregatedEstimate(
        carbs_low=carbs_low,
        carbs_high=carbs_high,
        confidence=confidence,
        food_description=representative.food_description,
        nutrition=representative.nutrition or {},
        dispersion_cv=cv,
        identity_agreement=identity_agreement,
        distinct_identities=distinct,
        samples_requested=samples_requested,
        samples_ok=len(ok),
        wide_spread=wide_spread,
        samples=audit,
    )
