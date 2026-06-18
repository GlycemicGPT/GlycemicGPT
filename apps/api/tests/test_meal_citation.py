"""Tests for output-side carb-citation verification.

Deterministic string-in / string-out tests over fixed model-output fixtures and
explicit ``AllowedCarb`` sets -- no live model, no DB. Covers the full Test Plan:
matched passthrough, mismatch correction/scrub, extraction robustness, tolerance
boundaries, corrected-value preference, hallucinated meals, timestamp
misattribution, no-citation passthrough, multiple meals, replacement safety,
determiner grammar, and a pathological-input guard.
"""

from src.services.meal_citation import (
    CORRECT_TEMPLATE,
    SCRUB_TEMPLATE,
    SCRUB_TEMPLATE_DET,
    AllowedCarb,
    verify_carb_citations,
)
from src.vision.carb_contract import MEAL_ESTIMATE_QUALIFIER

# Common allow-sets. tol(60-80) = max(3, 0.10*80) = 8 -> accept value [52, 88].
# tol(25-35) = max(3, 0.10*35) = 3.5 -> accept value [21.5, 38.5].
ONE_DINNER = [AllowedCarb(60.0, 80.0, "3h ago")]
ONE_OATMEAL = [AllowedCarb(25.0, 35.0, "3h ago")]


def _verify(text, allowed):
    return verify_carb_citations(text, allowed)


# ── Matched citations pass through unchanged (no false positives) ──


class TestMatchedValuePasses:
    def test_single_value_within_range_unchanged(self):
        text = "Your dinner was about 70g of carbs -- how did it sit?"
        assert _verify(text, ONE_DINNER).text == text

    def test_exact_range_unchanged(self):
        text = "Spaghetti looked like ~60-80g carbs."
        assert _verify(text, ONE_DINNER).text == text

    def test_rounded_midpoint_unchanged(self):
        text = "about 30g carbs"
        assert _verify(text, ONE_OATMEAL).text == text

    def test_matched_citation_counts_only_matched(self):
        outcome = _verify("about 70g of carbs", ONE_DINNER)
        assert outcome.citations_seen == 1
        assert outcome.citations_matched == 1
        assert not outcome.changed


# ── Mismatches are corrected (single referent) or scrubbed (ambiguous) ──


class TestMismatchHandling:
    def test_single_record_mismatch_corrected_to_stored_range(self):
        outcome = _verify("Dinner was around 120g of carbs.", ONE_DINNER)
        assert outcome.text == (
            f"Dinner was ~60-80g carbs ({MEAL_ESTIMATE_QUALIFIER})."
        )
        assert outcome.citations_corrected == 1
        assert outcome.citations_scrubbed == 0

    def test_multi_record_mismatch_scrubbed_to_non_numeric(self):
        allowed = [AllowedCarb(40.0, 55.0, "a"), AllowedCarb(60.0, 80.0, "b")]
        outcome = _verify("dinner was about 200g of carbs", allowed)
        assert "200" not in outcome.text
        assert SCRUB_TEMPLATE in outcome.text
        assert outcome.citations_scrubbed == 1
        assert outcome.citations_corrected == 0

    def test_range_endpoint_drift_corrected(self):
        outcome = _verify("roughly 60-90g carbs", ONE_DINNER)
        assert "90" not in outcome.text
        assert outcome.text == (f"~60-80g carbs ({MEAL_ESTIMATE_QUALIFIER})")


# ── Number-extraction robustness ──


class TestExtractionRobustness:
    def test_en_dash_range_parsed(self):
        allowed = [AllowedCarb(40.0, 55.0, "Mon 19:30")]
        text = "That was ~40–55g carbs."
        assert _verify(text, allowed).text == text  # 40-55 matches exactly

    def test_word_to_separator_and_grams_word(self):
        allowed = [AllowedCarb(40.0, 55.0, "Mon 19:30")]
        text = "about 40 to 55 grams of carbs"
        assert _verify(text, allowed).text == text

    def test_grams_unit_spellings_match(self):
        allowed = [AllowedCarb(40.0, 55.0, "Mon 19:30")]
        for cite in ("50 g of carbs", "50 grams of carbs", "50g carbs"):
            assert _verify(cite, allowed).text == cite  # 50 in [36.5, 59.5]

    def test_no_grams_token_carb_word_anchor(self):
        # "150 carbs" with no grams unit is still a carb citation.
        outcome = _verify("Your oatmeal was about 150 carbs.", ONE_OATMEAL)
        assert "150" not in outcome.text
        assert outcome.citations_corrected == 1

    def test_carbohydrates_spelled_out(self):
        outcome = _verify("Your lunch had around 200 carbohydrates.", ONE_DINNER)
        assert "200" not in outcome.text
        assert outcome.citations_corrected == 1

    def test_adjectival_n_carb(self):
        outcome = _verify("Your dinner was a 120-carb plate.", ONE_DINNER)
        assert "120" not in outcome.text
        # determiner "a " precedes -> article-free correct form
        assert f"a ~60-80g carbs ({MEAL_ESTIMATE_QUALIFIER}) plate" in outcome.text

    def test_thousands_comma_not_split(self):
        # "1,025" must parse as 1025 (out of range), not a passing "025"/"25".
        outcome = _verify("roughly 1,025g of carbs", ONE_OATMEAL)
        assert "1,025" not in outcome.text
        assert outcome.citations_corrected == 1


# ── Tolerance boundary (documented: tol = max(3g, 10% of stored high)) ──


class TestToleranceBoundary:
    def test_single_value_just_inside_passes(self):
        text = "about 38g carbs"  # 38 <= 38.5
        assert _verify(text, ONE_OATMEAL).text == text

    def test_single_value_just_outside_flagged(self):
        outcome = _verify("about 39g carbs", ONE_OATMEAL)  # 39 > 38.5
        assert outcome.citations_corrected == 1

    def test_upper_band_boundary(self):
        assert _verify("88g carbs", ONE_DINNER).text == "88g carbs"  # 88 <= 88
        assert _verify("89g carbs", ONE_DINNER).citations_corrected == 1  # 89 > 88

    def test_range_within_tolerance_passes(self):
        text = "~62-78g carbs"  # |62-60|=2<=8, |78-80|=2<=8
        assert _verify(text, ONE_DINNER).text == text


# ── corrected_* preference is honored via the AllowedCarb the DB layer builds ──


class TestCorrectedValuePreference:
    def test_matches_corrected_value_not_original(self):
        # The DB layer feeds the corrected range; the original AI estimate must
        # not validate a citation of it.
        corrected = [AllowedCarb(90.0, 110.0, "3h ago")]
        assert _verify("you logged ~90-110g carbs", corrected).citations_matched == 1
        # A citation of the superseded original (60-80) does not match.
        outcome = _verify("the original ~60-80g carbs", corrected)
        assert outcome.citations_corrected == 1
        assert "60-80" not in outcome.text


# ── Hallucinated meal: nothing logged -> nothing specific asserted ──


class TestHallucinatedMeal:
    def test_no_records_scrubs_every_figure(self):
        outcome = _verify("You logged 90g of carbs.", [])
        assert "90" not in outcome.text
        assert SCRUB_TEMPLATE in outcome.text
        assert outcome.citations_scrubbed == 1


# ── Timestamp misattribution (bounded single-record guard) ──


class TestTimestampMisattribution:
    def test_absolute_day_mismatch_scrubbed(self):
        allowed = [AllowedCarb(60.0, 80.0, "Mon 19:30")]
        outcome = _verify("On Tuesday you had 70g of carbs.", allowed)
        # value matched but the stated weekday contradicts the stored day.
        assert "70g" not in outcome.text
        assert SCRUB_TEMPLATE in outcome.text
        # Removed via the scrub template -> counts as scrubbed, with the
        # timestamp counter as the reason sub-tag. Every figure lands in exactly
        # one bucket: seen == matched + corrected + scrubbed.
        assert outcome.timestamp_mismatches == 1
        assert outcome.citations_scrubbed == 1
        assert outcome.citations_matched == 0
        assert (
            outcome.citations_seen
            == outcome.citations_matched
            + outcome.citations_corrected
            + outcome.citations_scrubbed
        )

    def test_absolute_day_agreement_unchanged(self):
        allowed = [AllowedCarb(60.0, 80.0, "Mon 19:30")]
        text = "On Monday you had 70g of carbs."
        assert _verify(text, allowed).text == text

    def test_relative_when_never_false_fires(self):
        # A <48h meal renders "Nh ago"; a legitimate "today"/"Monday" near it
        # must not trip the guard.
        text = "Earlier today you had 70g of carbs."
        assert _verify(text, ONE_DINNER).text == text

    def test_relative_when_weekly_phrase_unchanged(self):
        text = "You've had ~60-80g carbs each day Monday through Friday."
        assert _verify(text, ONE_DINNER).text == text

    def test_timestamp_guard_inert_with_multiple_records(self):
        # Can't bind a value to a meal when several are logged -> no guard.
        allowed = [
            AllowedCarb(60.0, 80.0, "Mon 19:30"),
            AllowedCarb(40.0, 50.0, "Tue 12:00"),
        ]
        text = "On Wednesday you had 70g of carbs."
        assert _verify(text, allowed).text == text  # 70 matches first; not scrubbed


# ── No-citation passthrough: non-carb numbers are never touched ──


class TestNoCitationPassthrough:
    def test_glucose_insulin_time_iob_untouched(self):
        text = "Your glucose hit 120 mg/dL after a 2.5u bolus 48h ago, IoB 1.2u."
        assert _verify(text, ONE_DINNER).text == text

    def test_glucose_per_litre_concentration_untouched(self):
        text = "Your fasting glucose was 1.1 g/L this morning."
        assert _verify(text, ONE_DINNER).text == text

    def test_other_macros_untouched(self):
        # Only the carb figure is evaluated; protein/fiber grams pass through.
        text = "That meal had ~70g of carbs, 25g protein, 8g of fiber."
        assert _verify(text, ONE_DINNER).text == text

    def test_recipe_ingredient_grams_untouched(self):
        text = "The recipe calls for 50g of flour."
        assert _verify(text, ONE_DINNER).text == text

    def test_plain_text_with_no_numbers_unchanged(self):
        text = "How are you feeling after lunch today?"
        outcome = _verify(text, ONE_DINNER)
        assert outcome.text == text
        assert outcome.citations_seen == 0

    def test_kg_not_matched(self):
        text = "You weigh 70 kg."
        assert _verify(text, ONE_DINNER).text == text


# ── Multiple meals verified independently ──


class TestMultipleMeals:
    def test_each_figure_checked_independently(self):
        allowed = [AllowedCarb(40.0, 55.0, "a"), AllowedCarb(60.0, 80.0, "b")]
        outcome = _verify(
            "Lunch was ~40-55g carbs and dinner was ~200g carbs.", allowed
        )
        assert "~40-55g carbs" in outcome.text  # matched, untouched
        assert "200" not in outcome.text  # scrubbed
        assert outcome.citations_seen == 2
        assert outcome.citations_matched == 1
        assert outcome.citations_scrubbed == 1


# ── Determiner-aware replacement grammar ──


class TestDeterminerGrammar:
    def test_correct_form_reads_after_determiner(self):
        # The corrected form opens with the range, so it reads after a
        # determiner without an article clash or fused words.
        for det in ("a", "the", "your", "that", "this"):
            outcome = _verify(f"{det} 120g of carbs dinner", ONE_DINNER)
            assert (
                f"{det} ~60-80g carbs ({MEAL_ESTIMATE_QUALIFIER}) dinner"
                == outcome.text
            )

    def test_scrub_determiner_form_after_article(self):
        allowed = [AllowedCarb(40.0, 55.0, "a"), AllowedCarb(60.0, 80.0, "b")]
        outcome = _verify("You had a 200g of carbs snack", allowed)
        assert outcome.text == f"You had a {SCRUB_TEMPLATE_DET} snack"

    def test_no_determiner_keeps_article(self):
        outcome = _verify("Dinner was 120g of carbs.", ONE_DINNER)
        assert outcome.text == f"Dinner was ~60-80g carbs ({MEAL_ESTIMATE_QUALIFIER})."


# ── Replacement safety: AI-guess framing, never permissive dosing language ──


class TestReplacementSafety:
    def test_templates_carry_safety_qualifier(self):
        # Every emitted template names the prohibited action and never uses the
        # permissive "verify before dosing" phrasing -- we must not tell a user a
        # carb guess is safe to bolus from once checked.
        for tmpl in (
            SCRUB_TEMPLATE,
            SCRUB_TEMPLATE_DET,
            CORRECT_TEMPLATE.format(low=60, high=80),
        ):
            assert MEAL_ESTIMATE_QUALIFIER in tmpl
            assert "never use it to dose or bolus" in tmpl
            assert "verify before dosing" not in tmpl.lower()

    def test_rewritten_output_never_implies_dosing_is_ok(self):
        # A hallucinated carb figure is scrubbed; the substituted text frames it
        # as an AI guess that must not be dosed from -- never "verify before
        # dosing" (which would imply dosing off it is fine once checked).
        outcome = _verify("Nice -- looks like you had about 200g of carbs.", [])
        assert "200" not in outcome.text
        assert SCRUB_TEMPLATE in outcome.text
        assert "never use it to dose or bolus" in outcome.text
        assert "verify before dosing" not in outcome.text.lower()

    def test_scrub_and_correct_outputs_carry_prohibition(self):
        assert "never use it to dose or bolus" in _verify("90g of carbs", []).text
        assert (
            "never use it to dose or bolus" in _verify("999g of carbs", ONE_DINNER).text
        )


# ── Pathological input is handled without hanging (no catastrophic backtracking) ──


class TestPathologicalInput:
    def test_long_whitespace_vector_returns(self):
        text = "~" + " " * 5000 + "to" + " " * 5000 + "g"
        outcome = _verify(text, ONE_DINNER)
        # No real carb citation -> unchanged, and it must complete (no ReDoS).
        assert outcome.text == text

    def test_empty_input(self):
        outcome = _verify("", ONE_DINNER)
        assert outcome.text == ""
        assert outcome.citations_seen == 0

    def test_many_figures_complete(self):
        text = " ".join(["100g of carbs"] * 200)
        outcome = _verify(text, ONE_DINNER)
        assert outcome.citations_seen == 200
        assert "100g" not in outcome.text  # all corrected to stored range

    def test_long_digit_run_returns_quickly(self):
        # A bounded \\d{1,9} run means a long all-digits string cannot drive
        # super-linear backtracking; this must complete, not hang (ReDoS guard).
        text = "1" * 50000 + "g carbs"
        outcome = _verify(text, ONE_DINNER)
        # 50000-digit value is far out of range and has no carb anchor on a 1-9
        # digit window, so nothing is asserted as a verified figure.
        assert isinstance(outcome.text, str)


# ── Regressions for adversarial/senior review findings ──


class TestReviewRegressions:
    """Concrete cases the review surfaced: leading-carb-word false negatives,
    bare-grams false positives, both-unit ranges, and the ReDoS guard."""

    def test_leading_carb_word_no_grams_is_caught(self):
        # HIGH: "carb word, then bare number" used to slip through unverified.
        for text in (
            "Carbs: 200",
            "Carbohydrate count: 200",
            "Net carbs around 200",
            "carbs were about 200",
            "I estimate the carbs at 200.",
        ):
            outcome = _verify(text, ONE_DINNER)
            assert "200" not in outcome.text, text
            assert MEAL_ESTIMATE_QUALIFIER in outcome.text, text

    def test_leading_carb_label_matched_value_passes(self):
        text = "Carbs: 70"  # 70 in [52, 88]
        assert _verify(text, ONE_DINNER).text == text

    def test_bare_grams_without_carb_word_untouched(self):
        # HIGH: a grams weight with no carb word is ambiguous (water, serving,
        # recipe, body weight) and must NOT be rewritten into a carb claim.
        for text in (
            "Add 200g of water.",
            "The recipe needs 250g.",
            "A 90g serving.",
            "It took 90g to spike you.",
            "You weigh 70 kg.",
        ):
            assert _verify(text, ONE_DINNER).text == text, text

    def test_carb_word_does_not_reach_over_to_adjacent_macro(self):
        # The trailing carb figure is verified; the carb word must not bind to
        # the following protein grams.
        text = "That was ~70g of carbs, 25g protein."
        assert _verify(text, ONE_DINNER).text == text

    def test_carb_word_does_not_reach_over_to_glucose(self):
        for text in (
            "Your carbs were fine, glucose hit 120 mg/dL.",
            "carbs ok, bg 120 today",
        ):
            assert _verify(text, ONE_DINNER).text == text, text

    def test_range_with_unit_on_both_bounds_single_span(self):
        outcome = _verify("about 200g-210g carbs", ONE_DINNER)
        assert outcome.citations_seen == 1
        assert outcome.text == (f"~60-80g carbs ({MEAL_ESTIMATE_QUALIFIER})")

    def test_range_with_carb_word_on_both_bounds_single_span(self):
        outcome = _verify("around 200 carbs to 210 carbs", ONE_DINNER)
        assert outcome.citations_seen == 1
        assert outcome.text == (f"~60-80g carbs ({MEAL_ESTIMATE_QUALIFIER})")

    def test_and_joins_two_independent_citations(self):
        # "and" is not a range separator: two correct citations of different
        # meals stay separate and pass through.
        allowed = [AllowedCarb(40.0, 55.0, "a"), AllowedCarb(85.0, 95.0, "b")]
        text = "I had 40g carbs and 90g carbs."
        assert _verify(text, allowed).text == text

    def test_carbohydrate_grams_phrasing_no_dangling_unit(self):
        outcome = _verify("The meal had 200 carbohydrate grams.", ONE_DINNER)
        assert "grams" not in outcome.text  # trailing unit consumed
        assert "200" not in outcome.text
