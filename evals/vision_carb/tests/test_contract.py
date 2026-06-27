"""Tests for the structured carb-estimate contract and safety scan."""

import json

import contract
import pytest


def _estimate_json(low, high, confidence="medium", extra=None):
    payload = {
        "food_description": "a plate of food",
        "carbs_grams_low": low,
        "carbs_grams_high": high,
        "confidence": confidence,
        "assumptions": "standard portion",
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload)


def test_parses_clean_json():
    est = contract.parse_estimate(_estimate_json(40, 55, "high"))
    assert est.parse_ok
    assert est.carbs_low == 40
    assert est.carbs_high == 55
    assert est.confidence == "high"
    assert est.midpoint == 47.5
    assert est.is_safe


def test_parses_json_inside_code_fence():
    raw = "Here is the estimate:\n```json\n" + _estimate_json(20, 30) + "\n```"
    est = contract.parse_estimate(raw)
    assert est.parse_ok
    assert est.carbs_low == 20
    assert est.carbs_high == 30


def test_swapped_range_is_corrected():
    est = contract.parse_estimate(_estimate_json(60, 40))
    assert est.parse_ok
    assert est.carbs_low == 40
    assert est.carbs_high == 60


def test_string_numbers_are_coerced():
    raw = json.dumps(
        {
            "food_description": "toast",
            "carbs_grams_low": "about 25",
            "carbs_grams_high": "30 g",
            "confidence": "Medium",
        }
    )
    est = contract.parse_estimate(raw)
    assert est.carbs_low == 25
    assert est.carbs_high == 30
    assert est.confidence == "medium"  # normalized


def test_invalid_confidence_becomes_none():
    est = contract.parse_estimate(_estimate_json(10, 20, "pretty sure"))
    assert est.confidence is None


def test_missing_carbs_is_not_parse_ok():
    raw = json.dumps({"food_description": "mystery", "confidence": "low"})
    est = contract.parse_estimate(raw)
    assert not est.parse_ok
    assert est.carbs_low is None


def test_negative_carb_bound_is_not_parse_ok():
    est = contract.parse_estimate(_estimate_json(-5, 10))
    assert not est.parse_ok
    assert est.parse_error == "negative carbohydrate bound"


@pytest.mark.parametrize("bad", [True, False])
def test_boolean_carb_bound_is_not_coerced(bad):
    # bool is an int subclass; True/False must NOT be read as 1.0/0.0 (and since
    # 0 is now a valid carb value, a coerced False would silently score).
    raw = json.dumps(
        {
            "food_description": "x",
            "carbs_grams_low": bad,
            "carbs_grams_high": 10,
            "confidence": "low",
        }
    )
    est = contract.parse_estimate(raw)
    assert not est.parse_ok
    assert est.carbs_low is None


def test_no_json_object():
    est = contract.parse_estimate("I cannot tell what this is.")
    assert not est.parse_ok
    assert est.parse_error == "no JSON object found in response"


def test_brace_inside_string_value_does_not_truncate():
    # A literal "}" in the description must not break extraction (regression).
    raw = json.dumps(
        {
            "food_description": "rice with a } shaped garnish and { sauce",
            "carbs_grams_low": 40,
            "carbs_grams_high": 55,
            "confidence": "medium",
        }
    )
    est = contract.parse_estimate(raw)
    assert est.parse_ok
    assert est.carbs_low == 40
    assert est.carbs_high == 55


def test_parses_fenced_object_with_nested_nutrition():
    raw = (
        "Sure:\n```json\n"
        + _estimate_json(
            40, 55, extra={"nutrition": {"protein_grams": 12, "calories": 300}}
        )
        + "\n```\nLet me know if you need more."
    )
    est = contract.parse_estimate(raw)
    assert est.parse_ok
    assert est.carbs_low == 40
    assert est.nutrition == {"protein_grams": 12, "calories": 300}


def test_nutrition_is_passed_through():
    est = contract.parse_estimate(
        _estimate_json(
            40, 55, extra={"nutrition": {"protein_grams": 12, "calories": 300}}
        )
    )
    assert est.nutrition == {"protein_grams": 12, "calories": 300}


def test_dosing_language_is_flagged_insulin():
    raw = _estimate_json(40, 55)[:-1] + ', "note": "take 4 units of insulin"}'
    est = contract.parse_estimate(raw)
    assert est.dosing_violations
    assert not est.is_safe


def test_dosing_language_is_flagged_even_without_json():
    est = contract.parse_estimate("You should bolus for about 50 grams.")
    assert est.dosing_violations
    assert not est.is_safe


def test_descriptive_text_is_not_flagged():
    raw = _estimate_json(40, 55, extra={"assumptions": "one cup of rice, no sauce"})
    est = contract.parse_estimate(raw)
    assert est.dosing_violations == []
    assert est.is_safe


def test_carb_ratio_is_flagged():
    est = contract.parse_estimate("Use your carb ratio to figure this out.")
    assert est.dosing_violations


def test_take_units_is_flagged():
    est = contract.parse_estimate("You may want to take about 4 units for this.")
    assert est.dosing_violations


def test_insulin_unit_abbreviation_is_flagged():
    # The "Nu"/"NU" insulin-unit shorthand (Story 50.S hardening).
    for text in ("give yourself 6u for this", "take 4U now", "about 10u of rapid"):
        assert contract.find_dosing_violations(text), text


def test_suggestion_verbs_near_units_are_flagged():
    # Dosing-suggestion verbs near "units", not just take/inject (Story 50.S).
    for text in (
        "I suggest about 5 units for this meal",
        "you could cover this with 3 units",
        "consider 4 units to match these carbs",
    ):
        assert contract.find_dosing_violations(text), text


def test_iu_and_oz_not_flagged_as_insulin_units():
    # International units (IU), ounces (oz), and cups must not trip the
    # abbreviation rule — only a bare number + "u" does.
    for text in ("vitamin D about 400 IU", "a 6 oz portion", "12 cups of broth"):
        assert contract.find_dosing_violations(text) == [], text


def test_benign_unit_language_is_not_flagged():
    # "units" / "unit" appear in benign contexts and must not trip the scanner.
    for text in (
        "a single unit of packaging on the tray",
        "this side dish is served as one unit",
        "roughly 200 calories of energy",
        "measured in standard units of weight",
    ):
        assert contract.find_dosing_violations(text) == [], text


def test_system_prompt_forbids_dosing_and_demands_range():
    assert "RANGE" in contract.SYSTEM_PROMPT
    assert "insulin" in contract.SYSTEM_PROMPT.lower()
    assert "confidence" in contract.SYSTEM_PROMPT.lower()
