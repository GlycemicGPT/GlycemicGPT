"""Glucose-relevant nutrition surfacing -- pure logic + safety (Story 50.N1).

Covers the framing copy, the net-carbs computation, the dosing scrubber
extensions, and the no-coupling guarantee, all without a database. The API/
persistence side (assumptions persisted + exposed; nutrition_facts on the read
response) lives in ``test_food_records.py``.

Safety posture under test:
  * Every *descriptive* macro string is free of dosing language (the scrubber
    finds nothing) and free of a specific peak-timing number.
  * The net-carbs and section disclaimers carry the never-dose prohibition.
  * "dose on net carbs" and fat-protein-unit (FPU/Warsaw) phrasing are hard
    violations the scrubber rejects.
  * Net carbs is descriptive-only: it is computed, never persisted, and never a
    column the dosing math could read.
"""

from pathlib import Path

import pytest

from src.schemas.food_record import (
    NetCarbsEstimate,
    build_comorbidity_nutrition,
    build_nutrition_facts,
)
from src.vision.carb_contract import (
    COMORBIDITY_NUTRITION_DISCLAIMER,
    COMORBIDITY_NUTRITION_NOTES,
    MACRO_GLUCOSE_NOTES,
    NET_CARBS_CAVEAT,
    NEVER_DOSE_PROHIBITION,
    NUTRITION_DOSE_DISCLAIMER,
    SUGAR_FREE_NOTE,
    find_dosing_violations,
)


# --------------------------------------------------------------------------- #
# AC2: descriptive macro framing -- no dosing language, no timing numbers
# --------------------------------------------------------------------------- #
class TestMacroFraming:
    def test_every_macro_note_is_free_of_dosing_language(self):
        for key, note in MACRO_GLUCOSE_NOTES.items():
            assert find_dosing_violations(note) == [], f"{key} note reads as dosing"

    def test_no_macro_note_states_a_timing_number(self):
        # The "protein peaks ~5h" claim was overstated, so protein/fat say
        # "later, in the hours after a meal" with NO figure; no note has a digit.
        for key, note in MACRO_GLUCOSE_NOTES.items():
            assert not any(c.isdigit() for c in note), f"{key} note has a number"

    def test_protein_and_fat_frame_a_later_rise(self):
        assert "later" in MACRO_GLUCOSE_NOTES["protein_grams"].lower()
        assert "later" in MACRO_GLUCOSE_NOTES["fat_grams"].lower()

    def test_fiber_frames_a_blunted_rise(self):
        note = MACRO_GLUCOSE_NOTES["fiber_grams"].lower()
        assert "blunt" in note or "slow" in note

    def test_the_four_glucose_relevant_macros_are_framed(self):
        assert set(MACRO_GLUCOSE_NOTES) == {
            "protein_grams",
            "fat_grams",
            "fiber_grams",
            "calories",
        }


# --------------------------------------------------------------------------- #
# AC4/AC6: net-carbs + section disclaimer carry the never-dose prohibition
# --------------------------------------------------------------------------- #
class TestSafetyCopy:
    def test_net_carbs_caveat_names_the_prohibition_and_points_to_total_carbs(self):
        assert NEVER_DOSE_PROHIBITION in NET_CARBS_CAVEAT
        assert "ada" in NET_CARBS_CAVEAT.lower()
        assert "total carbs" in NET_CARBS_CAVEAT.lower()
        assert "not exact" in NET_CARBS_CAVEAT.lower()

    def test_section_disclaimer_carries_the_prohibition(self):
        assert NEVER_DOSE_PROHIBITION in NUTRITION_DOSE_DISCLAIMER


# --------------------------------------------------------------------------- #
# AC5: the scrubber rejects dosing-creep phrasing (dose-on-net-carbs, FPU)
# --------------------------------------------------------------------------- #
class TestScrubberDosingCreep:
    @pytest.mark.parametrize(
        "phrase",
        [
            "dose on net carbs",
            "dose for carbs",
            "dose net carbs",
            "dosing off the net carbs",
            "you can dose using net carbohydrate",
            "convert this to 2 FPU",
            "count the fat-protein units",
            "use FPUs for the extended portion",
        ],
    )
    def test_dosing_creep_phrases_are_flagged(self, phrase):
        assert find_dosing_violations(phrase), f"not flagged: {phrase!r}"

    @pytest.mark.parametrize(
        "phrase",
        [
            "Net carbs are total carbs minus fiber.",
            "The ADA recommends counting total carbs.",
            "Fiber slows and blunts the rise in glucose.",
            "a bowl of pasta with a side of carbs",
            "assumed one cup of cooked rice",
        ],
    )
    def test_descriptive_food_phrases_are_not_flagged(self, phrase):
        assert find_dosing_violations(phrase) == [], f"false positive: {phrase!r}"


# --------------------------------------------------------------------------- #
# AC1/AC4: build_nutrition_facts -- macros + portion + net carbs
# --------------------------------------------------------------------------- #
class TestBuildNutritionFacts:
    def test_surfaces_the_four_known_macros_with_framing(self):
        facts = build_nutrition_facts(
            nutrition={
                "protein_grams": 12,
                "fat_grams": 8,
                "fiber_grams": 6,
                "calories": 520,
            },
            carbs_low=40,
            carbs_high=55,
            portion="one large bowl",
        )
        assert facts is not None
        labels = [m.label for m in facts.macros]
        assert labels == ["Protein", "Fat", "Fiber", "Calories"]
        # Calories carries its own unit; grams for the rest.
        units = {m.label: m.unit for m in facts.macros}
        assert units["Calories"] == "kcal" and units["Protein"] == "g"
        # Each surfaced macro carries its descriptive glucose note.
        for macro in facts.macros:
            assert macro.glucose_note == MACRO_GLUCOSE_NOTES[macro.key]
        assert facts.portion == "one large bowl"
        assert facts.disclaimer == NUTRITION_DOSE_DISCLAIMER

    def test_net_carbs_is_total_minus_fiber_clamped_and_caveated(self):
        facts = build_nutrition_facts(
            nutrition={"fiber_grams": 6},
            carbs_low=40,
            carbs_high=55,
            portion=None,
        )
        assert facts is not None and facts.net_carbs is not None
        assert facts.net_carbs.low == 34
        assert facts.net_carbs.high == 49
        assert facts.net_carbs.caveat == NET_CARBS_CAVEAT

    def test_net_carbs_low_bound_clamps_at_zero(self):
        facts = build_nutrition_facts(
            nutrition={"fiber_grams": 45},
            carbs_low=40,
            carbs_high=55,
            portion=None,
        )
        assert facts is not None and facts.net_carbs is not None
        assert facts.net_carbs.low == 0
        assert facts.net_carbs.high == 10

    def test_net_carbs_skipped_when_no_fiber(self):
        facts = build_nutrition_facts(
            nutrition={"protein_grams": 10},
            carbs_low=40,
            carbs_high=55,
            portion=None,
        )
        assert facts is not None
        assert facts.net_carbs is None

    def test_net_carbs_skipped_when_fiber_exceeds_carbs(self):
        # Fiber wiping out the whole band yields a zero/negative net value -- not
        # worth surfacing.
        facts = build_nutrition_facts(
            nutrition={"fiber_grams": 100},
            carbs_low=40,
            carbs_high=55,
            portion=None,
        )
        assert facts is not None
        assert facts.net_carbs is None

    def test_unknown_keys_are_not_echoed_as_framed_macros(self):
        # Arbitrary keys (e.g. from a free-form correction) are not surfaced as
        # "nutrition facts"; only the four known macros are framed.
        facts = build_nutrition_facts(
            nutrition={"sodium_mg": 900, "insulin_units": 5},
            carbs_low=40,
            carbs_high=55,
            portion=None,
        )
        assert facts is None

    def test_invalid_macro_values_are_dropped(self):
        facts = build_nutrition_facts(
            nutrition={
                "protein_grams": -3,  # negative -> dropped
                "fat_grams": "lots",  # non-numeric -> dropped
                "fiber_grams": True,  # bool -> dropped (and so no net carbs)
                "calories": 600,
            },
            carbs_low=40,
            carbs_high=55,
            portion=None,
        )
        assert facts is not None
        assert [m.label for m in facts.macros] == ["Calories"]
        assert facts.net_carbs is None

    def test_absurd_macro_values_are_dropped(self):
        # A single off-contract garbage field must not render an absurd card:
        # over-ceiling macros are dropped reject-not-clamp, like negatives.
        facts = build_nutrition_facts(
            nutrition={
                "protein_grams": 5,
                "calories": 9_999_999,  # absurd -> dropped
                "fiber_grams": 999_999,  # absurd -> dropped (so no net carbs)
            },
            carbs_low=40,
            carbs_high=55,
            portion=None,
        )
        assert facts is not None
        assert [m.label for m in facts.macros] == ["Protein"]
        assert facts.net_carbs is None

    def test_returns_none_when_nothing_to_show(self):
        assert (
            build_nutrition_facts(
                nutrition=None, carbs_low=40, carbs_high=55, portion="   "
            )
            is None
        )

    def test_portion_only_still_builds(self):
        facts = build_nutrition_facts(
            nutrition=None, carbs_low=40, carbs_high=55, portion="half a plate"
        )
        assert facts is not None
        assert facts.portion == "half a plate"
        assert facts.macros == []
        assert facts.net_carbs is None


# --------------------------------------------------------------------------- #
# AC4/AC6: net carbs is descriptive-only -- never a column, never in dosing math
# --------------------------------------------------------------------------- #
class TestNetCarbsNeverCouples:
    def test_net_carbs_is_not_a_food_record_column(self):
        from src.models.food_record import FoodRecord

        cols = set(FoodRecord.__table__.columns.keys())
        assert not any("net_carb" in c for c in cols)
        assert not hasattr(FoodRecord, "net_carbs")

    def test_net_carbs_estimate_is_display_only_default_caveat(self):
        # Constructing one always carries the prohibition caveat by default, so a
        # net-carbs figure can never travel without it.
        nc = NetCarbsEstimate(low=10, high=20)
        assert NEVER_DOSE_PROHIBITION in nc.caveat

    def test_net_carbs_estimate_rejects_an_inverted_band(self):
        # Mirrors the other carb-band models: low must not exceed high.
        with pytest.raises(ValueError):
            NetCarbsEstimate(low=20, high=10)

    def test_dosing_math_modules_do_not_reference_nutrition_surfacing(self):
        """Static guard: the dosing-math modules never read net carbs / macros.

        Independent of the food-record guard in test_food_records.py (a deliberate
        belt-and-braces): this one covers the whole ``treatment_safety`` package
        plus the IoB and treatment-validation services, asserting none reference
        the new N1 surfacing symbols.
        """
        api_root = Path(__file__).resolve().parents[1]
        treatment_safety = api_root / "src" / "core" / "treatment_safety"
        dosing_sources = [
            api_root / "src" / "services" / "iob_projection.py",
            api_root / "src" / "services" / "safety_validation.py",
            *sorted(treatment_safety.glob("*.py")),
        ]
        for path in dosing_sources:
            text = path.read_text().lower()
            assert "net_carb" not in text, f"{path} references net carbs"
            assert "nutrition_facts" not in text, f"{path} references nutrition_facts"
            assert "macrofact" not in text, f"{path} references MacroFact"
            # Grounded comorbidity nutrition is descriptive-only too.
            assert "comorbidity" not in text, f"{path} references comorbidity"
            assert "grounding_nutrition" not in text, (
                f"{path} references grounding nutrition"
            )


# --------------------------------------------------------------------------- #
# Grounding-backed comorbidity nutrition -- framing + build + safety
# --------------------------------------------------------------------------- #
class TestComorbidityFraming:
    def test_the_four_comorbidity_fields_are_framed(self):
        assert set(COMORBIDITY_NUTRITION_NOTES) == {
            "saturated_fat_grams",
            "sugars_grams",
            "added_sugars_grams",
            "sodium_mg",
        }

    def test_every_comorbidity_note_is_free_of_dosing_language(self):
        # AC3: the awareness framing must pass the scrubber (it describes the food,
        # never a dose).
        for key, note in COMORBIDITY_NUTRITION_NOTES.items():
            assert find_dosing_violations(note) == [], f"{key} note reads as dosing"

    def test_sodium_and_sat_fat_frame_bp_cardiovascular_awareness(self):
        # AC3: sodium -> blood pressure; saturated fat -> cardiovascular.
        assert "blood pressure" in COMORBIDITY_NUTRITION_NOTES["sodium_mg"].lower()
        assert (
            "cardiovascular"
            in COMORBIDITY_NUTRITION_NOTES["saturated_fat_grams"].lower()
        )

    def test_sugars_frame_an_earlier_spike(self):
        # AC3: sugars -> "tends to spike sooner".
        for key in ("sugars_grams", "added_sugars_grams"):
            note = COMORBIDITY_NUTRITION_NOTES[key].lower()
            assert "spike" in note and "sooner" in note, key

    def test_sugar_free_note_is_descriptive_and_points_to_total_carbs(self):
        # AC3: the "sugar-free is not carb-free" note passes the scrubber and points
        # the user back to total carbs (never a dose).
        assert find_dosing_violations(SUGAR_FREE_NOTE) == []
        lowered = SUGAR_FREE_NOTE.lower()
        assert "sugar-free" in lowered and "carb-free" in lowered
        assert "total carb" in lowered

    def test_section_disclaimer_carries_the_prohibition_not_ai_framing(self):
        # The figures are published reference data, so the disclaimer carries the
        # never-dose prohibition but must NOT mislabel them as an "AI estimate".
        assert NEVER_DOSE_PROHIBITION in COMORBIDITY_NUTRITION_DISCLAIMER
        assert "ai estimate" not in COMORBIDITY_NUTRITION_DISCLAIMER.lower()


class TestBuildComorbidityNutrition:
    _GROUNDED = {
        "saturated_fat_grams": 12.0,
        "sugars_grams": 8.0,
        "added_sugars_grams": 5.0,
        "sodium_mg": 1100.0,
    }

    def test_builds_attributed_facts_from_grounded_values(self):
        block = build_comorbidity_nutrition(
            grounding_nutrition=self._GROUNDED,
            source="USDA FoodData Central",
            source_url="https://fdc.nal.usda.gov/x",
            trust_tier="AUTHORITATIVE",
        )
        assert block is not None
        labels = [f.label for f in block.facts]
        assert labels == ["Saturated fat", "Sugars", "Added sugars", "Sodium"]
        units = {f.key: f.unit for f in block.facts}
        assert units["sodium_mg"] == "mg" and units["saturated_fat_grams"] == "g"
        # Each fact carries its descriptive awareness note.
        for fact in block.facts:
            assert fact.note == COMORBIDITY_NUTRITION_NOTES[fact.key]
        # Attribution is distinct from the vision estimate.
        assert block.source == "USDA FoodData Central"
        assert block.source_url == "https://fdc.nal.usda.gov/x"
        assert block.trust_tier == "AUTHORITATIVE"
        assert block.disclaimer == COMORBIDITY_NUTRITION_DISCLAIMER

    def test_sugar_note_only_when_a_sugars_field_is_present(self):
        with_sugar = build_comorbidity_nutrition(
            grounding_nutrition={"sugars_grams": 9.0},
            source="x",
            source_url=None,
            trust_tier=None,
        )
        assert with_sugar is not None and with_sugar.sugar_note == SUGAR_FREE_NOTE
        without_sugar = build_comorbidity_nutrition(
            grounding_nutrition={"sodium_mg": 500.0},
            source="x",
            source_url=None,
            trust_tier=None,
        )
        assert without_sugar is not None and without_sugar.sugar_note is None

    def test_returns_none_without_grounded_values(self):
        assert (
            build_comorbidity_nutrition(
                grounding_nutrition=None, source=None, source_url=None, trust_tier=None
            )
            is None
        )
        assert (
            build_comorbidity_nutrition(
                grounding_nutrition={}, source="x", source_url=None, trust_tier=None
            )
            is None
        )

    def test_absurd_and_invalid_values_are_dropped_reject_not_clamp(self):
        block = build_comorbidity_nutrition(
            grounding_nutrition={
                "sodium_mg": 10**9,  # over ceiling -> dropped
                "sugars_grams": -3,  # negative -> dropped
                "saturated_fat_grams": "lots",  # non-numeric -> dropped
                "added_sugars_grams": 4.0,  # kept
            },
            source="x",
            source_url=None,
            trust_tier=None,
        )
        assert block is not None
        assert [f.key for f in block.facts] == ["added_sugars_grams"]

    def test_non_object_grounding_payload_returns_none(self):
        # JSONB can hold any JSON value; a non-object (corrupted / hand-edited row)
        # must not raise on .get and 500 the record read -- it yields no block.
        for payload in ("just a string", 42, ["a", "list"], True):
            assert (
                build_comorbidity_nutrition(
                    grounding_nutrition=payload,
                    source="x",
                    source_url=None,
                    trust_tier=None,
                )
                is None
            )


class TestComorbidityExcludesOutOfScopeFields:
    def test_vision_contract_never_asks_for_comorbidity_fields(self):
        # AC1: the comorbidity fields are grounding-only -- the photo is never asked
        # for them, so they can't be asserted from a plated-food image.
        from src.vision.carb_contract import ESTIMATE_JSON_SHAPE, SYSTEM_PROMPT

        nutrition_spec = ESTIMATE_JSON_SHAPE["nutrition"].lower()
        for term in ("saturated", "sugar", "sodium", "salt"):
            assert term not in nutrition_spec, f"vision contract solicits {term}"
        prompt = SYSTEM_PROMPT.lower()
        for term in ("saturated fat", "sodium", "added sugar"):
            assert term not in prompt, f"system prompt solicits {term}"

    def test_no_gi_gl_or_fpu_field_is_surfaced(self):
        # AC5: GI / GL / FPU stay out of scope -- a block fed those keys surfaces
        # only the four allowed comorbidity fields (here: none), never them.
        block = build_comorbidity_nutrition(
            grounding_nutrition={
                "glycemic_index": 70,
                "glycemic_load": 25,
                "fat_protein_units": 2,
            },
            source="x",
            source_url=None,
            trust_tier=None,
        )
        assert block is None

    def test_comorbidity_is_not_a_food_record_dosing_column(self):
        # The grounded comorbidity values live in their own JSONB column, never a
        # carb/dose column the therapy math could read.
        from src.models.food_record import FoodRecord

        cols = set(FoodRecord.__table__.columns.keys())
        assert "grounding_nutrition_json" in cols
        for forbidden in ("dose", "insulin", "bolus", "sodium", "saturated"):
            assert not any(forbidden in c for c in cols), forbidden
