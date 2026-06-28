"""``compute_harness_version`` is content-addressed: stable across an unrelated
edit, moving the instant a component changes, and PER-SURFACE for prompt/dataset
edits while shared inputs (thresholds, floor) invalidate every surface.

These assert the versioning *behavior* the lock gate depends on (the gate itself
asserts the committed values); together they are the mutation proof in unit form.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from benchmarks.core import version as version_mod


def test_missing_canonical_surface_dir_fails_closed() -> None:
    # A renamed/deleted scenarios/<surface>/ must raise, never hash an empty set
    # (which would keep the lock gate green while the surface dropped out).
    with pytest.raises(FileNotFoundError):
        version_mod.compute_harness_version("not_a_real_surface")


def test_all_text_surfaces_present_and_distinct() -> None:
    versions = version_mod.compute_text_versions()
    assert set(versions) == set(version_mod.TEXT_SURFACES)
    assert all(v.startswith("sha256:") for v in versions.values())
    # Different surfaces hash distinctly (each carries its own prompts + name).
    assert len(set(versions.values())) == len(versions)


def test_version_is_deterministic() -> None:
    assert version_mod.compute_harness_version(
        "meal_analysis"
    ) == version_mod.compute_harness_version("meal_analysis")


def test_prompt_edit_is_scoped_to_one_surface(monkeypatch) -> None:
    """A rendered-prompt change to one surface must move only that surface's
    version — the per-surface scoping that stops a meal-prompt edit invalidating
    every cached result."""
    real = version_mod._rendered_prompts

    def perturbed_meal_only(surface: str):
        rendered = real(surface)
        if surface == "meal_analysis":
            return [*rendered, {"id": "zzz-edit", "system": "EDITED", "user": "EDITED"}]
        return rendered

    baseline = version_mod.compute_text_versions()
    monkeypatch.setattr(version_mod, "_rendered_prompts", perturbed_meal_only)
    after = version_mod.compute_text_versions()

    assert after["meal_analysis"] != baseline["meal_analysis"]
    for surface in version_mod.TEXT_SURFACES:
        if surface != "meal_analysis":
            assert after[surface] == baseline[surface], (
                f"{surface} must be unaffected by a meal-prompt edit"
            )


def test_threshold_change_invalidates_every_surface(monkeypatch) -> None:
    """A safety-threshold change is a shared input — it must invalidate ALL
    surfaces (a verdict computed under a different bound cannot be trusted)."""
    baseline = version_mod.compute_text_versions()
    monkeypatch.setattr(version_mod, "MGDL_PER_MMOL", 18.0)
    after = version_mod.compute_text_versions()
    for surface in version_mod.TEXT_SURFACES:
        assert after[surface] != baseline[surface]


def test_floor_change_invalidates_every_surface(monkeypatch) -> None:
    """The production floor is hashed WHOLE-module, so a change to a floor constant
    the entry function only *references* (the ±20% over-change threshold, a
    dangerous-content pattern, a dose regex) must move every surface's version.

    This perturbs the REAL floor source text — the exact stale-PASS a per-function
    ``inspect.getsource`` hash would have let slip — rather than monkeypatching the
    revision wholesale, so it verifies the property instead of mere propagation.
    """
    real_source = version_mod._floor_source()
    assert "MAX_CHANGE_PCT" in real_source, (
        "guard assumes the floor's over-change threshold constant exists"
    )
    baseline = version_mod.compute_text_versions()
    monkeypatch.setattr(
        version_mod,
        "_floor_source",
        lambda: real_source.replace("MAX_CHANGE_PCT", "MAX_CHANGE_PCT_EDITED"),
    )
    after = version_mod.compute_text_versions()
    for surface in version_mod.TEXT_SURFACES:
        assert after[surface] != baseline[surface], (
            f"{surface} must invalidate on a floor change"
        )


def test_scorer_source_is_part_of_the_version(monkeypatch, tmp_path) -> None:
    """The deterministic scorer source is hashed in — a scorer edit bumps."""
    baseline = version_mod.compute_harness_version("meal_analysis")
    edited = tmp_path / "scorers_edited.py"
    edited.write_text(
        Path(version_mod.scorers.__file__).read_text(encoding="utf-8") + "\n# edit\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        version_mod, "scorers", types.SimpleNamespace(__file__=str(edited))
    )
    assert version_mod.compute_harness_version("meal_analysis") != baseline
