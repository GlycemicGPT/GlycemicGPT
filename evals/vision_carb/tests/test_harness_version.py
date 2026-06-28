"""The vision content version is stable, matches the committed shared lock, hashes
the full scorer source (so a weakened dosing regex bumps it), and digests the
dataset MANIFEST (labels + filenames) — never image bytes, so it is computable in
CI without the licensed images present.

This is the vision half of the CI regression gate; the text surfaces are gated by
``apps/api/tests/benchmarks/test_harness_version_lock.py`` against the same lock.
"""

import json
from pathlib import Path

import harness_version
import pytest

_LOCK = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "api"
    / "benchmarks"
    / "harness_versions.json"
)

_BUMP = "python evals/vision_carb/harness_version.py --update-lock"


def test_version_is_stable_and_prefixed() -> None:
    version = harness_version.compute_harness_version()
    assert version.startswith("sha256:")
    assert version == harness_version.compute_harness_version()


def test_version_matches_lock() -> None:
    lock = json.loads(_LOCK.read_text(encoding="utf-8"))
    assert harness_version.compute_harness_version() == lock.get("vision_carb"), (
        "vision harness version drifted from the committed lock. If a vision "
        f"prompt, scorer, threshold, or dataset change was intentional, run "
        f"`{_BUMP}` and commit apps/api/benchmarks/harness_versions.json."
    )


def test_dataset_digest_uses_refs_not_bytes() -> None:
    """The digest captures item references (filenames + labels), never pixels — so
    it is computable without the images on disk."""
    manifest = harness_version._dataset_manifest()
    assert manifest, "expected dataset items"
    for entry in manifest:
        assert set(entry) == {"manifest", "set", "item"}
        image = entry["item"].get("image")
        # A bare filename reference, never a path, a data URL, or raw bytes.
        assert image is None or (
            isinstance(image, str) and "/" not in image and "base64" not in image
        )
        assert not _contains_bytes(entry["item"])


def test_scorer_source_change_moves_the_version(monkeypatch) -> None:
    """The FULL scorer source is hashed (passbar + metrics + carb_contract), so a
    change to a module-level detector the entry function only references — e.g. the
    dosing regex behind the ``MAX_DOSING_VIOLATIONS == 0`` hard gate — bumps the
    version. Perturbs the real source text, the stale-PASS a per-function hash
    would have allowed."""
    real_source = harness_version._scorer_source()
    assert "_DOSING_PATTERNS" in real_source, (
        "guard assumes the dosing detector constant exists in the hashed source"
    )
    baseline = harness_version.compute_harness_version()
    monkeypatch.setattr(
        harness_version,
        "_scorer_source",
        lambda: real_source.replace("_DOSING_PATTERNS", "_DOSING_PATTERNS_EDITED"),
    )
    assert harness_version.compute_harness_version() != baseline


def test_manifest_change_moves_the_version(monkeypatch) -> None:
    real = harness_version._dataset_manifest
    baseline = harness_version.compute_harness_version()
    monkeypatch.setattr(
        harness_version,
        "_dataset_manifest",
        lambda: [
            *real(),
            {"manifest": "manifest.json", "set": "easy", "item": {"id": "synthetic"}},
        ],
    )
    assert harness_version.compute_harness_version() != baseline


def test_missing_dataset_manifest_fails_closed(monkeypatch, tmp_path) -> None:
    # A renamed/missing dataset must raise, never hash an empty manifest (which
    # would keep the lock gate green while the dataset dropped out).
    monkeypatch.setattr(harness_version, "_DATASET", tmp_path)
    with pytest.raises(FileNotFoundError):
        harness_version.compute_harness_version()


def _contains_bytes(node: object) -> bool:
    if isinstance(node, bytes):
        return True
    if isinstance(node, dict):
        return any(_contains_bytes(v) for v in node.values())
    if isinstance(node, list):
        return any(_contains_bytes(v) for v in node)
    return False
