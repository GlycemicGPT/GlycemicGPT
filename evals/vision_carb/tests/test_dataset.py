"""Integrity tests for the committed eval datasets.

These guard the *data* the harness scores against: a malformed manifest (a
missing truth value, a non-list identity, a dosing phrase that leaked into a
note, an adversarial item missing its look-alike) would silently corrupt every
metric, so the manifest is asserted to be well-formed here.
"""

import json
from pathlib import Path

import contract

_DATASET = Path(__file__).resolve().parent.parent / "dataset"
_ALLOWED_FAILURE_MODES = {
    "identity_lookalike",
    "systematic_underestimate",
    "high_variance",
    "portion_ambiguity",
}


def _load(name):
    return json.loads((_DATASET / name).read_text())


def _is_synonym_list(value):
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(s, str) and s.strip() for s in value)
    )


def test_v1_manifest_is_well_formed():
    manifest = _load("manifest.json")
    assert manifest["set"] == "easy"
    seen = set()
    for item in manifest["items"]:
        assert item["id"] not in seen, f"duplicate id {item['id']}"
        seen.add(item["id"])
        assert isinstance(item["known_carbs_grams"], (int, float))
        assert item["known_carbs_grams"] >= 0
        assert _is_synonym_list(item["expected_identity"]), item["id"]
        assert item.get("image"), item["id"]
    assert len(manifest["items"]) == 9


def test_adversarial_manifest_is_well_formed():
    manifest = _load("adversarial.json")
    assert manifest["set"] == "adversarial"
    seen = set()
    for item in manifest["items"]:
        item_id = item["id"]
        assert item_id not in seen, f"duplicate id {item_id}"
        seen.add(item_id)
        # The correct identity, as a synonym list.
        assert _is_synonym_list(item["expected_identity"]), item_id
        # The look-alike / wrong answer it is confused with.
        assert isinstance(item["confused_with"], str) and item["confused_with"].strip()
        # A recognized failure mode.
        assert item["failure_mode"] in _ALLOWED_FAILURE_MODES, item_id
        # A truth carb value unless the item is explicitly ambiguous.
        if item.get("ambiguous"):
            assert "known_carbs_grams" not in item, item_id
        else:
            assert isinstance(item["known_carbs_grams"], (int, float)), item_id
            assert item["known_carbs_grams"] >= 0, item_id
        # Images are NOT committed (licensing/PHI); provenance is pinned per item
        # (source_url + license) so the image can be re-fetched + attributed.
        assert item.get("source_url"), item_id
        assert item.get("license"), item_id


def test_adversarial_covers_the_required_cases_and_failure_modes():
    manifest = _load("adversarial.json")
    ids = {item["id"] for item in manifest["items"]}
    # The named cases from the research amendment.
    assert ids >= {"cheese-sandwich", "bakewell-tart", "crema-catalana"}
    modes = {item["failure_mode"] for item in manifest["items"]}
    assert modes >= _ALLOWED_FAILURE_MODES  # every failure mode is represented


def test_all_image_fields_are_bare_filenames():
    # Path-safety at the data layer: an image must be a bare filename so a
    # crafted manifest cannot traverse out of the images directory.
    for name in ("manifest.json", "adversarial.json"):
        for item in _load(name)["items"]:
            image = item.get("image")
            if image:
                assert Path(image).name == image, f"{item['id']} image not bare"


def test_datasets_contain_no_dosing_language():
    # AC6: the committed eval data describes food, never a dose. Re-uses the
    # production dosing-language scanner so the bar is identical to model output.
    for name in ("manifest.json", "adversarial.json"):
        text = (_DATASET / name).read_text()
        assert contract.find_dosing_violations(text) == [], f"{name} has dosing words"
