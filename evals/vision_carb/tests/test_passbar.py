"""Tests for the local-model vision pass-bar decision logic.

The bar is variance/identity-first: a model accurate on average but high-variance
or frequently misidentifying food must FAIL, a no-vision model must FAIL, and a
model meeting every threshold at the certification N must PASS. Unmeasurable
metrics fail closed (do not certify). These assert the *decision*, not the
metrics (those are covered in test_metrics.py).
"""

from pathlib import Path

import passbar
from metrics import VarianceAggregate
from passbar import Verdict, evaluate_pass_bar

_FINDINGS = Path(__file__).resolve().parent.parent / "FINDINGS.md"


def _easy(**overrides) -> VarianceAggregate:
    """An easy-set aggregate that, by default, clears every gate with margin.

    Tests override one field at a time to push a single criterion over its bar,
    so each assertion isolates one gate (mirrors the cloud reference baseline:
    max CV 0.24, max spread 27 g, MAE 9.5 g, identity error 0%).
    """
    base = {
        "n_items": 9,
        "n_with_samples": 9,
        "n_with_variance": 9,
        "repeats": 5,
        "illustrative_icr": 10.0,
        "mae_grams": 9.5,
        "median_ae_grams": 4.5,
        "mean_cv": 0.10,
        "median_cv": 0.09,
        "max_cv": 0.24,
        "mean_spread_g": 12.0,
        "max_spread_g": 27.0,
        "max_illustrative_swing_units": 2.7,
        "identity_error_rate": 0.0,
        "identity_disagreement_rate": 0.0,
        "n_identity_measurable": 9,
        "n_partial_failures": 0,
        "samples_requested_total": 45,
        "samples_ok_total": 45,
    }
    base.update(overrides)
    return VarianceAggregate(**base)


def _evaluate(easy=None, *, has_vision=True, dosing=0, repeats=5, adversarial=None):
    return evaluate_pass_bar(
        has_vision=has_vision,
        dosing_violation_count=dosing,
        easy=_easy() if easy is None else easy,
        repeats=repeats,
        adversarial=adversarial,
    )


def _criterion(result, name):
    return next(c for c in result.criteria if c.name == name)


def test_passes_when_all_thresholds_met():
    result = _evaluate()
    assert result.verdict is Verdict.PASS
    assert result.passed is True
    assert result.failures == []
    assert result.unmeasured == []
    assert result.certifiable_n is True


def test_fails_high_variance_but_accurate_model():
    # The headline case: MAE is great (3 g) but the model swings wildly
    # photo-to-photo (max CV 0.45 > 0.30). Variance, not average, is the bar.
    result = _evaluate(_easy(mae_grams=3.0, max_cv=0.45))
    assert result.verdict is Verdict.FAIL
    assert "easy_max_cv" in result.failures
    assert _criterion(result, "easy_mae_g").passed is True  # accurate on average


def test_fails_high_mean_cv():
    result = _evaluate(_easy(mean_cv=0.22))
    assert result.verdict is Verdict.FAIL
    assert "easy_mean_cv" in result.failures


def test_fails_wide_per_image_spread():
    # Accurate and low CV, but one simple food swings 60 g across reads.
    result = _evaluate(_easy(max_spread_g=60.0))
    assert result.verdict is Verdict.FAIL
    assert "easy_max_spread_g" in result.failures


def test_fails_high_identity_error_rate():
    # Misidentification is upstream of carb error: 30% wrong-food disqualifies
    # even with tight variance and good MAE.
    result = _evaluate(_easy(identity_error_rate=0.30))
    assert result.verdict is Verdict.FAIL
    assert "easy_identity_error_rate" in result.failures


def test_fails_high_average_error():
    result = _evaluate(_easy(mae_grams=25.0))
    assert result.verdict is Verdict.FAIL
    assert "easy_mae_g" in result.failures


def test_fails_no_vision_model():
    result = _evaluate(has_vision=False)
    assert result.verdict is Verdict.FAIL
    assert "vision_available" in result.failures
    assert _criterion(result, "vision_available").passed is False


def test_fails_on_dosing_language():
    # Non-negotiable: any dosing/advice phrase disqualifies regardless of metrics.
    result = _evaluate(dosing=1)
    assert result.verdict is Verdict.FAIL
    assert "dosing_violations" in result.failures


def test_threshold_boundaries_are_inclusive():
    # Exactly at each ceiling must PASS (<= semantics), not fail.
    result = _evaluate(
        _easy(
            identity_error_rate=passbar.MAX_EASY_IDENTITY_ERROR_RATE,
            max_cv=passbar.MAX_EASY_MAX_CV,
            mean_cv=passbar.MAX_EASY_MEAN_CV,
            max_spread_g=passbar.MAX_EASY_MAX_SPREAD_G,
            mae_grams=passbar.MAX_EASY_MAE_G,
        )
    )
    assert result.verdict is Verdict.PASS


def test_just_over_a_boundary_fails():
    result = _evaluate(_easy(max_cv=passbar.MAX_EASY_MAX_CV + 0.001))
    assert result.verdict is Verdict.FAIL
    assert "easy_max_cv" in result.failures


def test_low_sampling_n_is_insufficient_not_pass():
    # All gates met, but sampled below the certification N -> cannot certify on
    # the optimistic small-N variance estimate.
    result = _evaluate(repeats=3)
    assert result.verdict is Verdict.INSUFFICIENT_DATA
    assert result.passed is False
    assert result.certifiable_n is False


def test_low_n_with_a_real_failure_still_fails():
    # A measured threshold breach is disqualifying even at low N (a fail at the
    # optimistic small-N variance is, if anything, a stronger signal).
    result = _evaluate(_easy(max_cv=0.5), repeats=3)
    assert result.verdict is Verdict.FAIL


def test_unmeasurable_identity_fails_closed():
    # No ground-truth identity could be scored -> the gate is unmeasured, so the
    # model is NOT certified (fail-closed), even though nothing was over a bar.
    result = _evaluate(_easy(identity_error_rate=None, n_identity_measurable=0))
    assert result.verdict is Verdict.INSUFFICIENT_DATA
    assert "easy_identity_error_rate" in result.unmeasured
    assert result.failures == []


def test_unmeasurable_variance_fails_closed():
    result = _evaluate(_easy(max_cv=None, mean_cv=None))
    assert result.verdict is Verdict.INSUFFICIENT_DATA
    assert "easy_max_cv" in result.unmeasured


def test_missing_easy_set_fails_closed():
    result = evaluate_pass_bar(
        has_vision=True, dosing_violation_count=0, easy=None, repeats=5
    )
    assert result.verdict is Verdict.INSUFFICIENT_DATA
    assert "easy_max_cv" in result.unmeasured


def test_adversarial_is_reported_not_gated():
    # A terrible adversarial identity-error rate must NOT flip a PASS to FAIL.
    adversarial = _easy(identity_error_rate=0.5, max_cv=0.6, mae_grams=40.0)
    result = _evaluate(adversarial=adversarial)
    assert result.verdict is Verdict.PASS
    adv = _criterion(result, "adversarial_identity_error_rate")
    assert adv.hard is False
    assert adv.observed == 0.5


def test_result_serializes_with_decision_fields():
    d = _evaluate().to_dict()
    for key in ("verdict", "passed", "has_vision", "repeats", "criteria", "summary"):
        assert key in d
    assert d["verdict"] == "pass"
    assert all({"name", "passed", "threshold"} <= set(c) for c in d["criteria"])


def test_summary_names_the_failing_gates():
    result = _evaluate(_easy(max_cv=0.5, identity_error_rate=0.4))
    assert "FAIL" in result.summary
    assert "easy_max_cv" in result.summary
    assert "easy_identity_error_rate" in result.summary


def test_findings_table_matches_passbar_constants():
    # Couple the prose pass-bar table in FINDINGS.md to these constants so the doc
    # and the gate cannot drift: each cell is rendered FROM the constant and must
    # appear verbatim in the document. Editing a constant without updating the
    # table (or vice versa) fails here. (Uses the doc's Unicode <= / >= glyphs.)
    text = _FINDINGS.read_text(encoding="utf-8")
    expected_cells = [
        f"{passbar.MAX_DOSING_VIOLATIONS} (hard)",
        f"≤ {passbar.MAX_EASY_IDENTITY_ERROR_RATE * 100:g} %",
        f"≤ {passbar.MAX_EASY_MAX_CV:.2f}",
        f"mean CV ≤ {passbar.MAX_EASY_MEAN_CV:.2f}",
        f"≤ {passbar.MAX_EASY_MAX_SPREAD_G:g} g",
        f"≤ {passbar.MAX_EASY_MAE_G:g} g",
        f"N ≥ {passbar.MIN_CERTIFICATION_REPEATS}",
    ]
    for cell in expected_cells:
        assert cell in text, (
            f"FINDINGS.md pass-bar table is out of sync: missing {cell!r}"
        )
