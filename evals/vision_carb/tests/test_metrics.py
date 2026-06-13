"""Tests for the accuracy metric computation."""

import metrics


def test_score_item_basic():
    s = metrics.score_item(
        "x", truth_grams=50, predicted_low=40, predicted_high=55, confidence="medium"
    )
    assert s.scored
    assert s.midpoint == 47.5
    assert s.abs_error == 2.5
    assert s.covered is True
    assert s.range_width == 15


def test_score_item_not_covered():
    s = metrics.score_item(
        "x", truth_grams=80, predicted_low=40, predicted_high=55, confidence="low"
    )
    assert s.covered is False
    assert s.abs_error == 32.5


def test_score_item_unparseable():
    s = metrics.score_item(
        "x", truth_grams=50, predicted_low=None, predicted_high=None, confidence=None
    )
    assert not s.scored
    assert s.abs_error is None


def test_aggregate_headline_mae():
    scores = [
        metrics.score_item("a", 50, 45, 55, "high"),  # mid 50, AE 0
        metrics.score_item("b", 30, 20, 30, "medium"),  # mid 25, AE 5
        metrics.score_item("c", 40, 50, 70, "low"),  # mid 60, AE 20
    ]
    agg = metrics.aggregate(scores)
    assert agg.n_scored == 3
    assert abs(agg.mae_grams - 25 / 3) < 1e-9


def test_aggregate_coverage_and_tolerance():
    scores = [
        metrics.score_item("a", 50, 45, 55, "high"),  # covered, AE 0
        metrics.score_item("b", 30, 20, 30, "medium"),  # covered, AE 5
        metrics.score_item("c", 40, 50, 70, "low"),  # NOT covered, AE 20
    ]
    agg = metrics.aggregate(scores)
    assert abs(agg.coverage_rate - 2 / 3) < 1e-9
    assert abs(agg.within_10g_rate - 2 / 3) < 1e-9  # AE 0 and 5
    assert agg.within_20g_rate == 1.0  # all <= 20


def test_aggregate_ignores_unscored():
    scores = [
        metrics.score_item("a", 50, 45, 55, "high"),
        metrics.score_item("b", 30, None, None, None),  # failed
    ]
    agg = metrics.aggregate(scores)
    assert agg.n_total == 2
    assert agg.n_scored == 1
    assert agg.mae_grams == 0.0


def test_by_confidence_breakdown():
    scores = [
        metrics.score_item("a", 50, 45, 55, "high"),
        metrics.score_item("b", 50, 48, 52, "high"),
        metrics.score_item("c", 40, 10, 20, "low"),
    ]
    agg = metrics.aggregate(scores)
    assert agg.by_confidence["high"]["n"] == 2
    assert agg.by_confidence["high"]["coverage_rate"] == 1.0
    assert agg.by_confidence["low"]["n"] == 1


def test_empty_aggregate_is_safe():
    agg = metrics.aggregate([])
    assert agg.n_scored == 0
    assert agg.mae_grams is None
    assert agg.to_dict()["mae_grams"] is None
