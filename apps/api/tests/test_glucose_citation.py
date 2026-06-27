"""Tests for output-side glucose-citation verification.

Covers the single-value verifier, the free-text extractor (which must tell a
glucose reading apart from an ISF / carb-ratio figure), the correct-or-scrub
rewrite, and the flag path -- in both mg/dL and mmol/L, plus the round-trip
safety property over the whole [20, 500] range.
"""

import pytest

from src.core.units import (
    MGDL_PER_MMOL,
    GlucoseUnit,
    format_glucose_value,
)
from src.schemas.safety_validation import SuggestionType
from src.services.glucose_citation import (
    GLUCOSE_VALUE_PATTERN,
    _extract,
    find_glucose_citation_flags,
    verify_glucose_citation,
    verify_glucose_citations,
)


class TestSingleValueVerifier:
    """`verify_glucose_citation` applies the rounding-tolerant band, not equality."""

    def test_mgdl_within_one_passes(self):
        assert verify_glucose_citation(120, "mgdl", 120)
        assert verify_glucose_citation(121, "mgdl", 120)
        assert verify_glucose_citation(119, "mgdl", 120)

    def test_mgdl_outside_one_fails(self):
        assert not verify_glucose_citation(122, "mgdl", 120)
        assert not verify_glucose_citation(118, "mgdl", 120)

    def test_mmol_within_one_tenth_passes(self):
        assert verify_glucose_citation(6.7, "mmol", 120)
        assert verify_glucose_citation(6.6, "mmol", 120)

    def test_mmol_outside_one_tenth_fails(self):
        assert not verify_glucose_citation(6.4, "mmol", 120)

    def test_unit_token_accepts_labels(self):
        # The token may arrive as a display label, not just the short form.
        assert verify_glucose_citation(6.7, "mmol/L", 120)
        assert verify_glucose_citation(120, "mg/dL", 120)


class TestRoundingDriftBoundaries:
    """Conventional anchors: converted-and-rounded display values must verify, a
    genuinely wrong number must not."""

    def test_99_mgdl_spoken_5_5_mmol_passes(self):
        assert verify_glucose_citation(5.5, "mmol", 99)

    def test_100_mgdl_spoken_5_6_mmol_passes(self):
        assert verify_glucose_citation(5.6, "mmol", 100)

    def test_180_mgdl_spoken_10_0_mmol_passes(self):
        assert verify_glucose_citation(10.0, "mmol", 180)

    def test_record_99_spoken_9_9_mmol_fails(self):
        # A tenfold misread (5.5 -> 9.9) is the wrong-number case that must fail.
        assert not verify_glucose_citation(9.9, "mmol", 99)

    def test_uses_consolidated_factor_not_a_local_literal(self):
        # 100 mg/dL converts to 5.55 mmol with 18.0156; the legacy 18.0182 would
        # render 5.5, so this pins the consolidated constant.
        assert round(100 / MGDL_PER_MMOL, 1) == 5.6


class TestExtractor:
    """The extractor pulls glucose figures while leaving ISF / carb-ratio alone."""

    def test_extracts_mgdl_and_mmol(self):
        cites = _extract("BG was 120 mg/dL, now 6.7 mmol/L")
        assert [(c.value, c.unit) for c in cites] == [
            (120.0, GlucoseUnit.MGDL),
            (6.7, GlucoseUnit.MMOL),
        ]

    def test_range_not_extracted_passes_through(self):
        # A range states bounds (a target/summary), not a reading -> pass through.
        assert _extract("ranged from 70 to 180 mg/dL") == []

    def test_ignores_isf_one_to_x(self):
        assert _extract("Adjust ISF from 1:50 to 1:45 mg/dL") == []

    def test_ignores_isf_context_keyword(self):
        assert _extract("change correction factor from 50 to 45 mg/dL") == []

    def test_ignores_carb_ratio(self):
        # No per-volume suffix at all -- never a glucose citation.
        assert _extract("carb ratio 1:8 is fine") == []

    def test_ignores_isf_rate(self):
        assert _extract("your ISF is 50.0 mg/dL per unit") == []

    def test_ignores_bare_grams_and_g_per_dl(self):
        # A carb concentration ("g/dL") is not a glucose reading suffix.
        assert _extract("about 80 g of carbs, albumin 4 g/dL") == []

    def test_pattern_requires_per_volume_denominator(self):
        # A bare "mg" / "mmol" (the abbreviated ISF suffix) is not a reading.
        assert GLUCOSE_VALUE_PATTERN.search("dose 5 mg now") is None
        assert GLUCOSE_VALUE_PATTERN.search("120 mg/dL") is not None


class TestCommaSeparators:
    """A comma is a European decimal point or a thousands separator -- the figure
    must be parsed whole, never half-read (which would turn a correct citation
    into a mismatch and leave an orphan fragment)."""

    def test_comma_decimal_mmol_matches(self):
        # 120 mg/dL == 6.66 mmol -> displays "6.7"; "6,7" must read as 6.7.
        outcome = verify_glucose_citations(
            "Your glucose was 6,7 mmol/L.", [120], GlucoseUnit.MMOL
        )
        assert outcome.text == "Your glucose was 6,7 mmol/L."
        assert outcome.citations_matched == 1

    def test_comma_decimal_wrong_value_scrubbed_cleanly(self):
        # A genuinely wrong comma decimal is removed with no orphan "9," left.
        outcome = verify_glucose_citations(
            "You spiked to 9,2 mmol/L.", [120, 90], GlucoseUnit.MMOL
        )
        assert "9,2" not in outcome.text
        assert "9," not in outcome.text
        assert outcome.citations_scrubbed == 1

    def test_thousands_comma_parses_whole(self):
        # "1,025" is 1025 (out of range) -> not the orphan "1,120".
        cites = _extract("Reading was 1,025 mg/dL.")
        assert cites[0].value == 1025.0

    def test_comma_decimal_flag_reason_is_clean(self):
        (flag,) = find_glucose_citation_flags(
            "You spiked to 9,2 mmol/L.", [120], GlucoseUnit.MMOL
        )
        assert "9.2 mmol/L" in flag.reason


class TestIsfExclusionPrecision:
    """A real reading sharing a sentence with an ISF change is still verified --
    the exclusion covers only the ISF figure, not the prose around it."""

    def test_reading_beside_isf_change_is_extracted(self):
        text = (
            "Your correction factor analysis: BG was 250 mg/dL, "
            "recommend moving from 50 to 45 mg/dL."
        )
        cites = _extract(text)
        # Only the real reading 250 is a glucose citation; the ISF figures are not.
        assert [c.value for c in cites] == [250.0]

    def test_hallucinated_reading_beside_isf_keyword_is_corrected(self):
        text = "correction factor note: BG 250 mg/dL today, move 50 to 45 mg/dL"
        outcome = verify_glucose_citations(text, [120], GlucoseUnit.MGDL)
        assert "250" not in outcome.text
        assert "120 mg/dL" in outcome.text  # corrected, not bypassed

    def test_isf_rate_with_drop_word_excluded(self):
        # The correction-analysis prompt phrases the rate as "X mg/dL drop per unit".
        assert _extract("observed ISF is 50 mg/dL drop per unit") == []


class TestRewrite:
    """`verify_glucose_citations`: matched unchanged, single referent corrected,
    ambiguous scrubbed."""

    def test_matched_value_unchanged(self):
        text = "Your average was 6.7 mmol/L today."
        outcome = verify_glucose_citations(text, [120], GlucoseUnit.MMOL)
        assert outcome.text == text
        assert outcome.citations_matched == 1
        assert not outcome.changed

    def test_single_referent_corrected_in_user_unit(self):
        outcome = verify_glucose_citations(
            "Your glucose is 200 mg/dL now.", [120], GlucoseUnit.MGDL
        )
        assert "120 mg/dL" in outcome.text
        assert "200" not in outcome.text
        assert outcome.citations_corrected == 1

    def test_single_referent_corrects_into_mmol(self):
        outcome = verify_glucose_citations(
            "Your glucose is 9.9 mmol/L now.", [120], GlucoseUnit.MMOL
        )
        assert "6.7 mmol/L" in outcome.text
        assert "9.9" not in outcome.text
        assert outcome.citations_corrected == 1

    def test_ambiguous_scrubbed(self):
        outcome = verify_glucose_citations(
            "You hit 250 mg/dL overnight.", [120, 140, 90], GlucoseUnit.MGDL
        )
        assert "250" not in outcome.text
        assert "can't verify" in outcome.text
        assert outcome.citations_scrubbed == 1

    def test_range_passes_through_untouched(self):
        # A range states bounds, not a reading, so it is never corrected/scrubbed
        # -- even one that doesn't trace to the data is left exactly as written.
        text = "ranged 40 to 300 mg/dL"
        outcome = verify_glucose_citations(text, [120], GlucoseUnit.MGDL)
        assert outcome.text == text
        assert outcome.citations_seen == 0

    def test_directive_threshold_passes_through(self):
        # A hypo-treatment threshold must never be "corrected" to the reading.
        for text, unit in [
            ("Call if below 3.9 mmol/L.", GlucoseUnit.MMOL),
            ("Severe low is 54 mg/dL.", GlucoseUnit.MGDL),
            ("Keep above 5.0 mmol/L.", GlucoseUnit.MMOL),
            ("Your target is 6.7 mmol/L.", GlucoseUnit.MMOL),
        ]:
            outcome = verify_glucose_citations(text, [120], unit)
            assert outcome.text == text
            assert outcome.citations_seen == 0

    def test_reading_still_acted_on_beside_a_threshold(self):
        # A genuine reading misquote is still corrected even when the same reply
        # also states a (passed-through) threshold.
        outcome = verify_glucose_citations(
            "Your glucose is 200 mg/dL; call if below 3.9 mmol/L.",
            [120],
            GlucoseUnit.MGDL,
        )
        assert "120 mg/dL" in outcome.text  # the reading is corrected
        assert "below 3.9 mmol/L" in outcome.text  # the threshold is untouched
        assert outcome.citations_corrected == 1

    def test_empty_records_scrubs_every_figure(self):
        outcome = verify_glucose_citations(
            "BG 120 mg/dL and 6.7 mmol/L", [], GlucoseUnit.MGDL
        )
        assert outcome.citations_scrubbed == 2
        assert "120" not in outcome.text and "6.7" not in outcome.text

    def test_empty_text_is_noop(self):
        outcome = verify_glucose_citations("", [120], GlucoseUnit.MGDL)
        assert outcome.text == ""
        assert outcome.citations_seen == 0

    def test_does_not_mutate_records(self):
        records = [120, 140]
        verify_glucose_citations("BG 999 mg/dL", records, GlucoseUnit.MGDL)
        assert records == [120, 140]

    def test_bucket_invariant_holds(self):
        outcome = verify_glucose_citations(
            "BG 120 mg/dL, then 250 mg/dL, then 90 mg/dL", [120], GlucoseUnit.MGDL
        )
        assert outcome.citations_seen == (
            outcome.citations_matched
            + outcome.citations_corrected
            + outcome.citations_scrubbed
        )

    def test_determiner_scrub_drops_article(self):
        # "the 250 mg/dL" -> "the glucose value...", not "the a glucose value...".
        outcome = verify_glucose_citations(
            "BG reached the 250 mg/dL overnight.", [120, 140, 90], GlucoseUnit.MGDL
        )
        assert "the glucose value I can't verify" in outcome.text
        assert "the a glucose" not in outcome.text
        assert "250" not in outcome.text

    def test_no_determiner_keeps_article(self):
        outcome = verify_glucose_citations(
            "You hit 250 mg/dL.", [120, 140, 90], GlucoseUnit.MGDL
        )
        assert "hit a glucose value I can't verify" in outcome.text

    def test_referents_decide_correction_not_padded_match_set(self):
        # The match set carries padded aggregates (target bounds), but a single
        # real reading referent still drives a correction rather than a scrub.
        outcome = verify_glucose_citations(
            "Your glucose is 200 mg/dL now.",
            [70, 120, 180],
            GlucoseUnit.MGDL,
            referents=[120],
        )
        assert "120 mg/dL" in outcome.text
        assert outcome.citations_corrected == 1

    def test_multiple_referents_scrub(self):
        outcome = verify_glucose_citations(
            "Your glucose is 200 mg/dL now.",
            [70, 120, 180],
            GlucoseUnit.MGDL,
            referents=[120, 140],
        )
        assert outcome.citations_scrubbed == 1

    def test_multiple_citations_one_line(self):
        outcome = verify_glucose_citations(
            "BG went 120 mg/dL then 250 mg/dL same line.", [120], GlucoseUnit.MGDL
        )
        assert outcome.citations_seen == 2
        assert outcome.citations_matched == 1  # 120 matches
        assert outcome.citations_corrected == 1  # 250 -> single referent 120


class TestFlagPath:
    """`find_glucose_citation_flags` for the validate_ai_suggestion surface."""

    def test_mismatch_flagged_with_unit_correct_reason(self):
        flags = find_glucose_citation_flags(
            "You spiked to 9.9 mmol/L.", [99, 120], GlucoseUnit.MMOL
        )
        assert len(flags) == 1
        flag = flags[0]
        assert flag.suggestion_type == SuggestionType.GLUCOSE_CITATION
        # Reason states the spoken value and the closest reading in the same unit.
        assert "9.9 mmol/L" in flag.reason
        assert "6.7 mmol/L" in flag.reason
        assert "0.1 mmol/L" in flag.reason

    def test_mgdl_reason_uses_mgdl_band(self):
        (flag,) = find_glucose_citation_flags(
            "BG read 200 mg/dL.", [120], GlucoseUnit.MGDL
        )
        assert "200 mg/dL" in flag.reason
        assert "1 mg/dL" in flag.reason

    def test_matched_figures_not_flagged(self):
        assert (
            find_glucose_citation_flags(
                "Your average was 6.7 mmol/L.", [120], GlucoseUnit.MMOL
            )
            == []
        )

    def test_no_records_no_flags(self):
        assert find_glucose_citation_flags("BG 200 mg/dL", [], GlucoseUnit.MGDL) == []

    def test_change_pct_is_zero_not_a_factor_change(self):
        (flag,) = find_glucose_citation_flags(
            "BG read 200 mg/dL.", [120], GlucoseUnit.MGDL
        )
        assert flag.change_pct == 0.0
        assert flag.max_allowed_pct == 0.0

    def test_numeric_fields_both_mgdl(self):
        # 9.9 mmol ~= 178 mg/dL spoken; nearest record 120 mg/dL. Both fields are
        # canonical mg/dL so a future consumer can't mistake mmol for mg/dL.
        (flag,) = find_glucose_citation_flags(
            "You spiked to 9.9 mmol/L.", [120], GlucoseUnit.MMOL
        )
        assert flag.original_value == pytest.approx(9.9 * MGDL_PER_MMOL)
        assert flag.suggested_value == 120.0

    def test_multiple_mismatches_one_line_each_flagged(self):
        flags = find_glucose_citation_flags(
            "your BG went 90 mg/dL to 250 mg/dL", [120], GlucoseUnit.MGDL
        )
        # Two distinct single-value hallucinations on one line -> two flags.
        assert len(flags) == 2


class TestRoundTripSafetyProperty:
    """Round-trip safety property: every integer mg/dL in the safety range,
    displayed in either unit and then verified against its own record, must pass
    the band -- a mis-rounded threshold must never read as a mismatch (and must
    never be scrubbed)."""

    @pytest.mark.parametrize("unit", [GlucoseUnit.MGDL, GlucoseUnit.MMOL])
    @pytest.mark.parametrize("mgdl", range(20, 501))
    def test_displayed_value_verifies_against_its_record(self, mgdl, unit):
        shown = format_glucose_value(mgdl, unit)
        label = "mmol/L" if unit == GlucoseUnit.MMOL else "mg/dL"
        unit_token = "mmol" if unit == GlucoseUnit.MMOL else "mgdl"

        # The single-value verifier accepts it.
        assert verify_glucose_citation(float(shown), unit_token, mgdl)

        # And the full extractor + rewrite + flag path treat it as verified:
        # not scrubbed, not corrected, not flagged.
        text = f"Your glucose is {shown} {label}."
        outcome = verify_glucose_citations(text, [mgdl], unit)
        assert outcome.text == text
        assert outcome.citations_matched == 1
        assert find_glucose_citation_flags(text, [mgdl], unit) == []

    @pytest.mark.parametrize("unit", [GlucoseUnit.MGDL, GlucoseUnit.MMOL])
    @pytest.mark.parametrize("mgdl", range(20, 501))
    def test_off_band_value_is_rejected(self, mgdl, unit):
        # The reject direction swept across the range: a value bumped clearly
        # outside the band (so display rounding can't pull it back in) must never
        # verify -- catches a partial band-widening regression a few fixed points
        # would miss.
        shown = float(format_glucose_value(mgdl, unit))
        unit_token = "mmol" if unit == GlucoseUnit.MMOL else "mgdl"
        bump = 0.5 if unit == GlucoseUnit.MMOL else 2
        bumped = round(shown + bump, 1)

        assert not verify_glucose_citation(bumped, unit_token, mgdl)
        label = "mmol/L" if unit == GlucoseUnit.MMOL else "mg/dL"
        text = f"Your glucose is {bumped} {label}."
        outcome = verify_glucose_citations(text, [mgdl], unit)
        # Single referent -> corrected (not matched); flag path emits one flag.
        assert outcome.citations_matched == 0
        assert outcome.citations_corrected == 1
        assert len(find_glucose_citation_flags(text, [mgdl], unit)) == 1
