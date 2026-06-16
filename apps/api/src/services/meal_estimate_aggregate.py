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
    verify-before-dosing framing stays dominant regardless of dispersion; this
    module never emits a dose and nothing here is read by IoB / treatment_safety.
  * The model's self-reported confidence is retained ONLY as internal audit/eval
    data (for 50.H3), never surfaced as a user-facing safety signal.
"""

from __future__ import annotations

import re
import statistics
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

# Token-set Jaccard at or above this means two food descriptions name the same
# food for agreement purposes. Below it (e.g. "creme brulee" vs "crema catalana",
# disjoint tokens -> 0.0) the samples disagree on identity. (50.H4 tunes this.)
_IDENTITY_AGREEMENT_JACCARD = 0.5

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


def _identity_tokens(description: str) -> frozenset[str]:
    """Normalize a food description to a comparable token set."""
    tokens = re.findall(r"[a-z0-9]+", (description or "").lower())
    return frozenset(t for t in tokens if t not in _IDENTITY_STOPWORDS)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


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
            if any(
                _jaccard(tokens, token_sets[idx]) >= _IDENTITY_AGREEMENT_JACCARD
                for idx in cluster
            ):
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
