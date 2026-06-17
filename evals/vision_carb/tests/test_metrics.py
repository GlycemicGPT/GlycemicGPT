"""Tests for the accuracy metric computation."""

import statistics

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


# ---------------------------------------------------------------------------
# Variance / reproducibility metrics
# ---------------------------------------------------------------------------


def _variance(
    item_id="x",
    *,
    set_name="easy",
    truth_grams=40.0,
    expected_identity=("x",),
    sample_midpoints=(28.0, 30.0, 29.0),
    sample_descriptions=None,
    samples_requested=3,
    ambiguous=False,
    illustrative_icr=10.0,
):
    midpoints = list(sample_midpoints)
    if sample_descriptions is None:
        sample_descriptions = ["a food"] * len(midpoints)
    return metrics.score_variance(
        item_id,
        set_name=set_name,
        truth_grams=truth_grams,
        expected_identity=list(expected_identity) if expected_identity else None,
        sample_midpoints=midpoints,
        sample_descriptions=list(sample_descriptions),
        samples_requested=samples_requested,
        ambiguous=ambiguous,
        illustrative_icr=illustrative_icr,
    )


def test_cv_computed_from_known_values():
    mids = [28.0, 30.0, 29.0]
    s = _variance(
        sample_midpoints=mids,
        expected_identity=["cheese sandwich"],
        sample_descriptions=["cheese sandwich"] * 3,
    )
    expected_cv = statistics.stdev(mids) / statistics.fmean(mids)  # unbiased (N-1)
    assert abs(s.cv - expected_cv) < 1e-12
    assert s.mean_midpoint == 29.0


def test_worst_case_swing_is_max_minus_min_over_icr():
    # The study's pathological paella: same photo, 55 g to 484 g across repeats.
    s = _variance(
        sample_midpoints=[55.0, 484.0, 120.0],
        truth_grams=50.0,
        expected_identity=["paella"],
        sample_descriptions=["paella"] * 3,
        illustrative_icr=10.0,
    )
    assert s.spread_grams == 484.0 - 55.0
    assert s.illustrative_swing_units == (484.0 - 55.0) / 10.0


def test_swing_scales_with_illustrative_icr():
    s = _variance(
        sample_midpoints=[10.0, 30.0], illustrative_icr=20.0, samples_requested=2
    )
    assert s.spread_grams == 20.0
    assert s.illustrative_swing_units == 1.0  # 20 g / 20 g/U


def test_single_sample_has_no_measurable_variance_but_keeps_mae():
    s = _variance(
        sample_midpoints=[27.0],
        truth_grams=27.0,
        expected_identity=["banana"],
        sample_descriptions=["banana"],
        samples_requested=1,
    )
    assert s.cv is None
    assert s.spread_grams is None
    assert s.illustrative_swing_units is None
    assert s.mae_grams == 0.0  # MAE still measurable at N=1
    assert s.identity_error is False  # identity measurable from one sample


def test_mae_at_n1_equals_single_shot_abs_error():
    # Regression guard: the variance path's MAE at N=1 must reduce exactly to the
    # single-shot per-item absolute error on the same prediction.
    low, high, truth = 35.0, 45.0, 40.0
    single = metrics.score_item("x", truth, low, high, "high")
    v = _variance(
        sample_midpoints=[(low + high) / 2.0],
        truth_grams=truth,
        samples_requested=1,
    )
    assert v.mae_grams == single.abs_error


def test_mean_zero_cv_is_none():
    # A 0-carb food (eggs) can produce a 0-mean sample set; CV is undefined
    # (division by zero) and must be None, but the spread is still reported.
    s = _variance(
        sample_midpoints=[0.0, 0.0],
        truth_grams=2.0,
        expected_identity=["eggs"],
        sample_descriptions=["eggs", "eggs"],
        samples_requested=2,
    )
    assert s.cv is None
    assert s.spread_grams == 0.0


def test_identity_error_true_on_gross_misidentification():
    # crema catalana consistently called creme brulee: wrong food, but the runs
    # AGREE with each other (no disagreement) -- a confident, consistent misID.
    s = _variance(
        sample_midpoints=[28.0, 30.0, 32.0],
        truth_grams=30.0,
        expected_identity=["crema catalana"],
        sample_descriptions=["creme brulee"] * 3,
    )
    assert s.identity_error is True
    assert s.identity_disagreement is False


def test_identity_error_false_on_correct_food():
    s = _variance(
        expected_identity=["cheese sandwich"],
        sample_descriptions=["a cheese sandwich on white bread"] * 3,
    )
    assert s.identity_error is False


def test_identity_matches_verbose_real_descriptions():
    # Regression for the bug live testing exposed: the real model returns long,
    # varied prose, and symmetric Jaccard scored these correct IDs as misses.
    # Containment must recognize the expected food inside the verbose text.
    banana = _variance(
        expected_identity=["banana"],
        sample_descriptions=[
            "A single unpeeled banana, yellow with slight green tinging and a "
            "few brown spots, resting on a rock outdoors.",
            "One medium ripe banana, mostly yellow with light speckling.",
            "A whole banana on a stone surface, peak ripeness.",
        ],
    )
    assert banana.identity_error is False
    apple = _variance(
        expected_identity=["apple", "apples"],
        sample_descriptions=[
            "Two red apples - one whole and one nearly fully eaten with only the "
            "core remaining.",
            "A pair of red apples, one bitten down to the core.",
            "Two medium-to-large red apples on a surface.",
        ],
    )
    assert apple.identity_error is False
    # And a genuine gross misID inside verbose prose is still caught.
    misid = _variance(
        expected_identity=["crema catalana"],
        sample_descriptions=[
            "A classic creme brulee with a torched, caramelized sugar crust in a "
            "white ramekin.",
        ]
        * 3,
    )
    assert misid.identity_error is True


def test_identity_tie_is_unmeasurable_not_wrong():
    # 2 correct, 2 wrong -> no strict majority -> identity-vs-truth unmeasurable
    # (None), but the runs clearly disagree among themselves.
    s = _variance(
        sample_midpoints=[28.0, 30.0, 32.0, 29.0],
        truth_grams=30.0,
        expected_identity=["crema catalana"],
        sample_descriptions=[
            "crema catalana",
            "crema catalana",
            "creme brulee",
            "creme brulee",
        ],
        samples_requested=4,
    )
    assert s.identity_error is None
    assert s.identity_disagreement is True


def test_identity_unmeasurable_when_no_descriptions_survive():
    s = _variance(
        sample_midpoints=[28.0, 30.0],
        expected_identity=["crema catalana"],
        sample_descriptions=["", ""],
        samples_requested=2,
    )
    assert s.model_identity is None
    assert s.identity_error is None
    assert s.identity_disagreement is None


def test_identity_unmeasurable_without_expected_identity():
    s = _variance(
        sample_midpoints=[28.0, 30.0],
        expected_identity=None,
        sample_descriptions=["banana", "banana"],
        samples_requested=2,
    )
    assert s.identity_error is None  # no ground-truth identity to compare against


def test_ambiguous_item_skips_mae_keeps_variance():
    s = _variance(
        item_id="plate",
        set_name="adversarial",
        sample_midpoints=[40.0, 80.0],
        truth_grams=None,
        ambiguous=True,
        expected_identity=["mixed plate"],
        sample_descriptions=["mixed plate", "mixed plate"],
        samples_requested=2,
    )
    assert s.mae_grams is None
    assert s.spread_grams == 40.0
    assert s.cv is not None


def test_partial_failure_flagged():
    s = _variance(
        sample_midpoints=[26.0, 28.0],  # 2 usable
        samples_requested=3,  # 3 attempted
    )
    assert s.partial_failure is True
    assert s.samples_ok == 2


def test_no_usable_samples_degrades_gracefully():
    s = _variance(
        sample_midpoints=[],
        sample_descriptions=[],
        truth_grams=27.0,
        samples_requested=3,
    )
    assert s.samples_ok == 0
    assert s.partial_failure is True
    assert s.mae_grams is None
    assert s.cv is None
    assert s.identity_error is None


def test_score_variance_to_dict_keys():
    d = _variance().to_dict()
    for key in (
        "cv",
        "spread_g",
        "illustrative_insulin_swing_units",
        "illustrative_icr_g_per_u",
        "mae_grams",
        "identity_error",
        "partial_failure",
        "set",
    ):
        assert key in d


def test_aggregate_variance_rates_and_maxes():
    scores = [
        _variance(
            item_id="banana",
            set_name="easy",
            sample_midpoints=[26.0, 28.0, 27.0],
            truth_grams=27.0,
            expected_identity=["banana"],
            sample_descriptions=["banana"] * 3,
        ),
        _variance(
            item_id="crema",
            set_name="adversarial",
            sample_midpoints=[20.0, 60.0, 40.0],
            truth_grams=30.0,
            expected_identity=["crema catalana"],
            sample_descriptions=["creme brulee"] * 3,
        ),
    ]
    agg = metrics.aggregate_variance(scores, repeats=3)
    assert agg.n_items == 2
    assert agg.max_spread_g == 40.0  # crema: 60 - 20
    assert agg.identity_error_rate == 0.5  # crema wrong, banana right
    assert agg.n_identity_measurable == 2
    assert agg.repeats == 3


def test_aggregate_variance_empty_is_safe():
    agg = metrics.aggregate_variance([], repeats=3)
    assert agg.n_items == 0
    assert agg.max_cv is None
    assert agg.identity_error_rate is None
    assert agg.to_dict()["max_cv"] is None


def test_aggregate_variance_excludes_zero_sample_items_from_rates():
    scores = [
        _variance(  # measurable
            sample_midpoints=[26.0, 28.0],
            expected_identity=["banana"],
            sample_descriptions=["banana", "banana"],
            samples_requested=2,
        ),
        _variance(  # no usable samples -> excluded from CV/MAE/identity rates
            sample_midpoints=[],
            sample_descriptions=[],
            truth_grams=30.0,
            samples_requested=2,
        ),
    ]
    agg = metrics.aggregate_variance(scores, repeats=2)
    assert agg.n_with_samples == 1
    assert agg.n_with_variance == 1
    assert agg.n_partial_failures == 1
