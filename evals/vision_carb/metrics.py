"""Accuracy metrics for vision carb estimates.

The headline go/no-go number is the mean absolute error (MAE) of the estimate
midpoint against the known-label carbohydrate value, in grams. We also report
the metrics that matter for a *range + confidence* product:

  * MAE / median AE / MAPE on the midpoint -- raw accuracy.
  * range coverage -- how often the true value falls inside the predicted
    range. A range product is only honest if the truth usually lands in it.
  * within-tolerance rates (+/-10 g, +/-15 g, +/-20 g) -- clinically legible
    bands for carb counting.
  * mean / median range width -- a range that is always 0-200 g would "cover"
    everything while being useless; width keeps coverage honest.
  * per-confidence breakdown -- does the model's confidence signal correlate
    with its accuracy? (Calibration is what makes the confidence field usable.)
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field


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
