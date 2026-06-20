"""Integrity tests for the committed eval datasets.

These guard the *data* the harness scores against: a malformed manifest (a
missing truth value, a non-list identity, a dosing phrase that leaked into a
note, an adversarial item missing its look-alike) would silently corrupt every
metric, so the manifest is asserted to be well-formed here.
"""

import ipaddress
import json
from pathlib import Path
from urllib.parse import urlparse

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


def _is_public_https_url(value):
    """True only for an https:// URL with a public, non-local hostname.

    Provenance URLs are committed to a public repo, so this rejects a malformed
    URL or one pointing at localhost / a private or internal host before it can
    leak infrastructure metadata into the manifest.
    """
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.rstrip(".").lower()  # strip the FQDN trailing dot
    # A public host is a dotted domain; reject single-word internal-like names
    # ("intranet", "localhost") and the explicit private suffixes.
    if (
        "." not in host
        or host == "localhost"
        or host.endswith(".local")
        or host.endswith(".internal")
    ):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # a regular public dotted hostname
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)


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
        # (source_url + license) so the image can be re-fetched + attributed. The
        # URL must be a public https:// link (never a private/internal host).
        assert _is_public_https_url(item.get("source_url")), item_id
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


def test_all_source_urls_are_public_https():
    # Every pinned provenance URL across both sets must be a public https:// link
    # -- no private/internal hostnames in committed, public manifests.
    for name in ("manifest.json", "adversarial.json"):
        for item in _load(name)["items"]:
            url = item.get("source_url")
            if url:
                assert _is_public_https_url(url), f"{item['id']}: {url}"


def test_is_public_https_url_rejects_private_and_malformed():
    assert _is_public_https_url("https://commons.wikimedia.org/wiki/File:X.jpg")
    for bad in (
        "http://commons.wikimedia.org/x",  # not https
        "https://localhost/x",
        "https://localhost./x",  # trailing-dot FQDN form
        "https://intranet/x",  # single-word internal host (no dot)
        "https://10.0.0.5/x",
        "https://192.168.1.1/x",
        "https://host.internal/x",
        "not a url",
        "",
        None,
    ):
        assert not _is_public_https_url(bad), bad


def test_datasets_contain_no_dosing_language():
    # AC6: the committed eval data describes food, never a dose. Re-uses the
    # production dosing-language scanner so the bar is identical to model output.
    for name in ("manifest.json", "adversarial.json"):
        text = (_DATASET / name).read_text()
        assert contract.find_dosing_violations(text) == [], f"{name} has dosing words"
