"""Accuracy and reproducibility metrics for vision carb estimates.

The single-shot accuracy block (``score_item`` / ``aggregate``) is the original
accuracy metric set. The headline go/no-go number there is the mean absolute error
(MAE) of the estimate midpoint against the known-label carbohydrate value, in
grams. We also report the metrics that matter for a *range + confidence* product:

  * MAE / median AE / MAPE on the midpoint -- raw accuracy.
  * range coverage -- how often the true value falls inside the predicted
    range. A range product is only honest if the truth usually lands in it.
  * within-tolerance rates (+/-10 g, +/-15 g, +/-20 g) -- clinically legible
    bands for carb counting.
  * mean / median range width -- a range that is always 0-200 g would "cover"
    everything while being useless; width keeps coverage honest.
  * per-confidence breakdown -- does the model's confidence signal correlate
    with its accuracy? (Calibration is what makes the confidence field usable.)

The variance block (``score_variance`` / ``aggregate_variance``)
adds the reproducibility metrics the single-shot number is blind to. Average
accuracy is an optimistic, incomplete safety signal: the diabettech 27,000-run
study found models that are right on average yet swing wildly photo-to-photo
(e.g. one model estimated a paella anywhere from 55 g to 484 g across repeats),
and that the acute-hypo risk lives in that tail, not in the mean. So we sample
each photo N times and measure:

  * coefficient of variation (CV) of the per-run midpoints -- the run-to-run
    dispersion, the metric the study validated as the only honest uncertainty
    signal (a model's *self-reported* confidence is uncorrelated with accuracy).
  * per-image spread (max - min of the run midpoints) and an illustrative
    worst-case insulin-equivalent swing -- the latter is an ANALYSIS DEVICE
    only (a fixed yardstick), never a dose and never read by any dosing code.
  * food-identity error rate (how often the model's majority-identified food is
    the wrong food vs ground truth) -- misidentification is upstream of, and
    dominates, carb error, so it is a first-class metric here.

These mirror, by independent re-derivation, the production multi-sample
aggregator (``src.services.meal_estimate_aggregate``) so this harness can
*validate* the shipped N and confidence thresholds rather than inherit their
bugs. Consistency is never correctness: a tight CV on a systematically-wrong
food (the study's cheese-sandwich class) is still wrong, and nothing here is a
dosing output.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass, field

# Word characters used to tokenize a food name for identity comparison.
_ALNUM_RE = re.compile(r"[a-z0-9]+")


@dataclass
class ItemScore:
    item_id: str
    truth_grams: float
    predicted_low: float | None
    predicted_high: float | None
    midpoint: float | None
    confidence: str | None
    abs_error: float | None
    pct_error: float | None
    covered: bool | None
    range_width: float | None
    scored: bool
    note: str = ""


def score_item(
    item_id: str,
    truth_grams: float,
    predicted_low: float | None,
    predicted_high: float | None,
    confidence: str | None,
    note: str = "",
) -> ItemScore:
    if predicted_low is None or predicted_high is None:
        return ItemScore(
            item_id=item_id,
            truth_grams=truth_grams,
            predicted_low=predicted_low,
            predicted_high=predicted_high,
            midpoint=None,
            confidence=confidence,
            abs_error=None,
            pct_error=None,
            covered=None,
            range_width=None,
            scored=False,
            note=note or "no parseable estimate",
        )
    midpoint = (predicted_low + predicted_high) / 2.0
    abs_error = abs(midpoint - truth_grams)
    pct_error = abs_error / truth_grams if truth_grams else None
    covered = predicted_low <= truth_grams <= predicted_high
    return ItemScore(
        item_id=item_id,
        truth_grams=truth_grams,
        predicted_low=predicted_low,
        predicted_high=predicted_high,
        midpoint=midpoint,
        confidence=confidence,
        abs_error=abs_error,
        pct_error=pct_error,
        covered=covered,
        range_width=predicted_high - predicted_low,
        scored=True,
        note=note,
    )


@dataclass
class Aggregate:
    n_total: int
    n_scored: int
    mae_grams: float | None
    median_ae_grams: float | None
    mape_pct: float | None
    coverage_rate: float | None
    within_10g_rate: float | None
    within_15g_rate: float | None
    within_20g_rate: float | None
    mean_range_width_g: float | None
    median_range_width_g: float | None
    by_confidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "n_total": self.n_total,
            "n_scored": self.n_scored,
            "mae_grams": _round(self.mae_grams),
            "median_ae_grams": _round(self.median_ae_grams),
            "mape_pct": _round(self.mape_pct),
            "coverage_rate": _round(self.coverage_rate),
            "within_10g_rate": _round(self.within_10g_rate),
            "within_15g_rate": _round(self.within_15g_rate),
            "within_20g_rate": _round(self.within_20g_rate),
            "mean_range_width_g": _round(self.mean_range_width_g),
            "median_range_width_g": _round(self.median_range_width_g),
            "by_confidence": self.by_confidence,
        }


def _round(value: float | None, ndigits: int = 2) -> float | None:
    return round(value, ndigits) if value is not None else None


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _rate(flags: list[bool]) -> float | None:
    return sum(1 for f in flags if f) / len(flags) if flags else None


def aggregate(scores: list[ItemScore]) -> Aggregate:
    scored = [s for s in scores if s.scored]
    abs_errors = [s.abs_error for s in scored if s.abs_error is not None]
    pct_errors = [s.pct_error for s in scored if s.pct_error is not None]
    widths = [s.range_width for s in scored if s.range_width is not None]
    covered = [bool(s.covered) for s in scored if s.covered is not None]

    by_confidence: dict[str, dict] = {}
    for level in ("low", "medium", "high", "unknown"):
        bucket = [s for s in scored if (s.confidence or "unknown") == level]
        if not bucket:
            continue
        bucket_ae = [s.abs_error for s in bucket if s.abs_error is not None]
        bucket_cov = [bool(s.covered) for s in bucket if s.covered is not None]
        by_confidence[level] = {
            "n": len(bucket),
            "mae_grams": _round(_mean(bucket_ae)),
            "coverage_rate": _round(_rate(bucket_cov)),
        }

    return Aggregate(
        n_total=len(scores),
        n_scored=len(scored),
        mae_grams=_mean(abs_errors),
        median_ae_grams=_median(abs_errors),
        mape_pct=(_mean(pct_errors) * 100.0) if pct_errors else None,
        coverage_rate=_rate(covered),
        within_10g_rate=_rate([e <= 10 for e in abs_errors]),
        within_15g_rate=_rate([e <= 15 for e in abs_errors]),
        within_20g_rate=_rate([e <= 20 for e in abs_errors]),
        mean_range_width_g=_mean(widths),
        median_range_width_g=_median(widths),
        by_confidence=by_confidence,
    )


# ---------------------------------------------------------------------------
# Variance / reproducibility metrics
# ---------------------------------------------------------------------------

# Illustrative carb-to-insulin ratio (grams of carbohydrate per unit) used ONLY
# to express a carb swing as an "insulin-equivalent" number so a variance figure
# is legible as "how big could the consequence of this swing be". It is a fixed
# yardstick for an ANALYSIS metric -- never a dose, never a recommendation, and
# never read by IoB / treatment_safety / any dosing code. A real person's ratio
# is their own and is irrelevant to this measurement; 10 g/U is a common textbook
# starting value chosen purely so swings are comparable across foods and runs.
DEFAULT_ILLUSTRATIVE_ICR = 10.0

# Identity matching is CONTAINMENT against the known correct identity, not the
# symmetric token-set Jaccard the production aggregator uses. That is a deliberate
# divergence justified by what this harness has that production does not: ground
# truth. Production must cluster the N descriptions *against each other* (Jaccard)
# to guess the dominant identity, because it has no label; the eval knows the
# right answer (``expected_identity``), so it asks the direct question -- "does
# this description name the expected food?" -- by checking whether all content
# tokens of some expected synonym appear in the description. This is robust to the
# real model's verbose output ("A single whole banana, unpeeled, resting on a
# rock..." cleanly contains "banana"), where symmetric Jaccard collapses: a long
# description shares few tokens with a 1-2 word name, so its overlap ratio falls
# below any threshold and a correct identification scores as a miss. (Live testing
# exposed exactly this; the production aggregator's sample-to-sample Jaccard
# clustering is likely also weak on verbose descriptions -- tracked as a
# follow-up.) Accents are stripped
# (NFKD) so "creme brulee" matches "crème brûlée"; this flags GROSS
# misidentification ("crema catalana" vs "creme brulee" share no tokens) but,
# being containment, also matches when the description adds modifiers around the
# expected name -- which is the desired behavior for a ground-truth check.

# Filler words stripped before comparing food names, so "a plate of grilled
# chicken" still contains "grilled chicken". Mirrors the production stopword set.
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


def _strip_accents(text: str) -> str:
    """Drop combining marks so "creme brulee" matches "crème brûlée"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _identity_tokens(name: str) -> frozenset[str]:
    """Normalize a food name to a comparable, stopword-stripped token set."""
    normalized = _strip_accents(name or "").lower()
    tokens = _ALNUM_RE.findall(normalized)
    return frozenset(t for t in tokens if t not in _IDENTITY_STOPWORDS)


def _normalize_expected(expected: object) -> list[str]:
    """Coerce an ``expected_identity`` field to a list of synonym strings.

    Accepts a bare string or a list of strings (the review-hardened form: a
    correct short name like "donut" must not score as a miss against "glazed
    doughnut"). Anything else yields an empty list (identity is unmeasurable).
    """
    if isinstance(expected, str):
        return [expected] if expected.strip() else []
    if isinstance(expected, (list, tuple)):
        return [s for s in expected if isinstance(s, str) and s.strip()]
    return []


def _identity_matches(description: str, expected: list[str]) -> bool:
    """True when ``description`` names the expected food (token containment).

    Matches if the content tokens of ANY expected synonym are all present in the
    description's tokens -- so a verbose "two red apples, one bitten" contains the
    synonym "apples", and "a cheese sandwich on white bread" contains "cheese
    sandwich", while "creme brulee" does not contain "crema catalana". A synonym
    that normalizes to no tokens (pure stopwords) never matches.
    """
    description_tokens = _identity_tokens(description)
    if not description_tokens or not expected:
        return False
    for synonym in expected:
        synonym_tokens = _identity_tokens(synonym)
        if synonym_tokens and synonym_tokens <= description_tokens:
            return True
    return False


@dataclass
class VarianceScore:
    """Per-image reproducibility metrics across N samples of one photo.

    ``cv`` / ``spread_grams`` / ``illustrative_swing_units`` are ``None`` when
    fewer than two usable samples exist (variance is unmeasurable from one
    look -- which is exactly the blind spot the single-shot number had).
    ``mae_grams`` is ``None`` for an ``ambiguous`` item (no honest truth to
    score against). ``identity_error`` is tri-state: ``True``/``False`` from a
    strict-majority vote of the per-sample containment check against the known
    correct identity, else ``None`` (no ground-truth identity, no described
    sample, or a tie -- unmeasurable is not the same as wrong).
    """

    item_id: str
    set_name: str
    ambiguous: bool
    truth_grams: float | None
    samples_requested: int
    samples_ok: int
    mean_midpoint: float | None
    cv: float | None
    spread_grams: float | None
    illustrative_swing_units: float | None
    illustrative_icr: float
    mae_grams: float | None
    expected_identity: list[str]
    model_identity: str | None
    identity_error: bool | None
    identity_disagreement: bool | None
    partial_failure: bool
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "set": self.set_name,
            "ambiguous": self.ambiguous,
            "truth_grams": self.truth_grams,
            "samples_requested": self.samples_requested,
            "samples_ok": self.samples_ok,
            "mean_midpoint_g": _round(self.mean_midpoint),
            "cv": _round(self.cv, 4),
            "spread_g": _round(self.spread_grams),
            "illustrative_insulin_swing_units": _round(self.illustrative_swing_units),
            "illustrative_icr_g_per_u": self.illustrative_icr,
            "mae_grams": _round(self.mae_grams),
            "expected_identity": self.expected_identity,
            "model_identity": self.model_identity,
            "identity_error": self.identity_error,
            "identity_disagreement": self.identity_disagreement,
            "partial_failure": self.partial_failure,
            "note": self.note,
        }


def score_variance(
    item_id: str,
    *,
    set_name: str,
    truth_grams: float | None,
    expected_identity: object,
    sample_midpoints: list[float],
    sample_descriptions: list[str],
    samples_requested: int,
    ambiguous: bool = False,
    illustrative_icr: float = DEFAULT_ILLUSTRATIVE_ICR,
    note: str = "",
) -> VarianceScore:
    """Score one image's N samples for reproducibility and identity error.

    ``sample_midpoints`` / ``sample_descriptions`` are the USABLE samples only
    (parsed, in-bounds) -- the caller drops failed/out-of-range samples so a
    single hallucination cannot poison the spread, and ``samples_requested``
    records how many were attempted so a shortfall is flagged (partial-failure
    handling, mirroring the production pipeline). The two lists are positionally
    aligned.

    CV uses the sample standard deviation with the N-1 (Bessel) divisor: these N
    draws are a *sample* of the model's output distribution, so at the small N
    this harness runs the population (N-divisor) stdev would understate the true
    spread and read optimistic.
    """
    expected = _normalize_expected(expected_identity)
    samples_ok = len(sample_midpoints)
    partial_failure = samples_ok < samples_requested

    mean_midpoint = _mean(sample_midpoints)

    cv: float | None = None
    spread_grams: float | None = None
    swing_units: float | None = None
    if samples_ok >= 2:
        spread_grams = max(sample_midpoints) - min(sample_midpoints)
        # Guard the ICR even though the harness validates it: a 0/negative ratio
        # would make the analysis metric meaningless rather than crash.
        if illustrative_icr > 0:
            swing_units = spread_grams / illustrative_icr
        if mean_midpoint and mean_midpoint > 0:
            cv = statistics.stdev(sample_midpoints) / mean_midpoint

    # MAE is the central (mean) estimate vs the known truth. At N=1 the mean is
    # the single midpoint, so this reduces exactly to the single-shot per-item
    # error (the regression guard). Ambiguous items have no honest truth -> no MAE.
    mae_grams: float | None = None
    if not ambiguous and truth_grams is not None and mean_midpoint is not None:
        mae_grams = abs(mean_midpoint - truth_grams)

    # Identity is scored per sample against ground truth (containment), then
    # majority-voted -- no fragile description-to-description clustering. A
    # representative description is kept for the report.
    described = [d for d in sample_descriptions if d and d.strip()]
    model_identity = described[0] if described else None
    matches = sum(1 for d in described if _identity_matches(d, expected))
    n_described = len(described)

    # Identity error needs ground truth AND a described sample to be measurable;
    # then it is a strict-majority vote. A tie -> None (unmeasurable, not wrong).
    identity_error: bool | None = None
    if expected and n_described:
        if matches * 2 > n_described:
            identity_error = False  # most samples name the right food
        elif (n_described - matches) * 2 > n_described:
            identity_error = True  # most samples name the wrong food

    # Run-to-run disagreement: do the samples agree among themselves on whether
    # this is the expected food? A split (some match, some don't) is instability.
    identity_disagreement: bool | None = None
    if expected and n_described >= 2:
        identity_disagreement = 0 < matches < n_described

    return VarianceScore(
        item_id=item_id,
        set_name=set_name,
        ambiguous=ambiguous,
        truth_grams=truth_grams,
        samples_requested=samples_requested,
        samples_ok=samples_ok,
        mean_midpoint=mean_midpoint,
        cv=cv,
        spread_grams=spread_grams,
        illustrative_swing_units=swing_units,
        illustrative_icr=illustrative_icr,
        mae_grams=mae_grams,
        expected_identity=expected,
        model_identity=model_identity,
        identity_error=identity_error,
        identity_disagreement=identity_disagreement,
        partial_failure=partial_failure,
        note=note,
    )


@dataclass
class VarianceAggregate:
    """Fleet-level reproducibility summary across all scored images."""

    n_items: int
    n_with_samples: int
    n_with_variance: int
    repeats: int
    illustrative_icr: float
    mae_grams: float | None
    median_ae_grams: float | None
    mean_cv: float | None
    median_cv: float | None
    max_cv: float | None
    mean_spread_g: float | None
    max_spread_g: float | None
    max_illustrative_swing_units: float | None
    identity_error_rate: float | None
    identity_disagreement_rate: float | None
    n_identity_measurable: int
    n_partial_failures: int
    samples_requested_total: int
    samples_ok_total: int

    def to_dict(self) -> dict:
        return {
            "n_items": self.n_items,
            "n_with_samples": self.n_with_samples,
            "n_with_variance": self.n_with_variance,
            "repeats": self.repeats,
            "illustrative_icr_g_per_u": self.illustrative_icr,
            "mae_grams": _round(self.mae_grams),
            "median_ae_grams": _round(self.median_ae_grams),
            "mean_cv": _round(self.mean_cv, 4),
            "median_cv": _round(self.median_cv, 4),
            "max_cv": _round(self.max_cv, 4),
            "mean_spread_g": _round(self.mean_spread_g),
            "max_spread_g": _round(self.max_spread_g),
            "max_illustrative_insulin_swing_units": _round(
                self.max_illustrative_swing_units
            ),
            "identity_error_rate": _round(self.identity_error_rate),
            "identity_disagreement_rate": _round(self.identity_disagreement_rate),
            "n_identity_measurable": self.n_identity_measurable,
            "n_partial_failures": self.n_partial_failures,
            "samples_requested_total": self.samples_requested_total,
            "samples_ok_total": self.samples_ok_total,
        }


def aggregate_variance(
    scores: list[VarianceScore],
    *,
    repeats: int,
    illustrative_icr: float = DEFAULT_ILLUSTRATIVE_ICR,
) -> VarianceAggregate:
    """Aggregate per-image variance scores into a fleet summary.

    ``repeats`` is the requested N for this aggregation (recorded so a sweep can
    label each row). ``illustrative_icr`` is threaded in explicitly (like
    ``repeats``) so the reported fleet ICR reflects caller intent and does not
    assume per-item homogeneity. Rates are computed over the measurable
    denominator only: identity error over items where identity was measurable, CV
    stats over items with >=2 usable samples, MAE over non-ambiguous items with a
    truth value.
    """
    with_samples = [s for s in scores if s.samples_ok >= 1]
    cvs = [s.cv for s in scores if s.cv is not None]
    spreads = [s.spread_grams for s in scores if s.spread_grams is not None]
    swings = [
        s.illustrative_swing_units
        for s in scores
        if s.illustrative_swing_units is not None
    ]
    maes = [s.mae_grams for s in scores if s.mae_grams is not None]

    identity_measurable = [s for s in scores if s.identity_error is not None]
    identity_errors = [bool(s.identity_error) for s in identity_measurable]
    disagree_measurable = [
        bool(s.identity_disagreement)
        for s in scores
        if s.identity_disagreement is not None
    ]

    return VarianceAggregate(
        n_items=len(scores),
        n_with_samples=len(with_samples),
        n_with_variance=len(cvs),
        repeats=repeats,
        illustrative_icr=illustrative_icr,
        mae_grams=_mean(maes),
        median_ae_grams=_median(maes),
        mean_cv=_mean(cvs),
        median_cv=_median(cvs),
        max_cv=max(cvs) if cvs else None,
        mean_spread_g=_mean(spreads),
        max_spread_g=max(spreads) if spreads else None,
        max_illustrative_swing_units=max(swings) if swings else None,
        identity_error_rate=_rate(identity_errors),
        identity_disagreement_rate=_rate(disagree_measurable),
        n_identity_measurable=len(identity_measurable),
        n_partial_failures=sum(1 for s in scores if s.partial_failure),
        samples_requested_total=sum(s.samples_requested for s in scores),
        samples_ok_total=sum(s.samples_ok for s in scores),
    )
