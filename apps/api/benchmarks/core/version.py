"""Per-surface content version for the text safety harness — the hash that makes
a cached trust verdict invalidatable.

A verdict you cannot content-invalidate is a stale-PASS waiting to harm a
patient: edit a production prompt and a scenario can silently flip FAIL→PASS with
nothing to catch it. ``compute_harness_version(surface)`` closes that hole by
hashing *exactly* what determines the verdict for one surface:

  * the RENDERED real production prompts for that surface (via the same
    ``runner._build_prompt`` the live benchmark uses, over the canonical
    scenarios) — so the version moves the instant a prod prompt builder changes;
  * the deterministic scorer source (``scorers.py``);
  * the production safety-floor revision (the source of the exact floor functions
    the scorers call, captured by ``inspect``) — so a floor change invalidates
    every surface, as it must;
  * the safety thresholds (the mg/dL↔mmol/L factor and the 20–500 mg/dL bound);
  * the scoring-relevant scenario manifest (ids + inputs + ground truth), so a
    dataset edit invalidates the affected surface.

It is PER-SURFACE on purpose: a meal-prompt edit must invalidate only
``meal_analysis``, not every cached result platform-wide. Shared inputs (the
scorers, the floor, the thresholds) legitimately invalidate *all* surfaces,
because they determine every surface's verdict.

The committed lock (``harness_versions.json``) records the expected version per
surface; the CI regression gate recomputes and compares, failing the PR if a
prompt/scorer/floor/threshold/dataset change lands without a re-record. The
re-record (the "bump") is ``python -m benchmarks.core.version --update-lock``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.core import scorers
from benchmarks.core.runner import _build_prompt
from benchmarks.scenario import load_scenarios
from src.core.content_digest import content_digest, sha256_hex
from src.core.treatment_safety.models import MAX_GLUCOSE_MGDL, MIN_GLUCOSE_MGDL
from src.core.units import MGDL_PER_MMOL
from src.services import safety_validation

# The text surfaces the harness scores. Each has a canonical scenario directory
# under ``benchmarks/scenarios/<surface>/``; the version is computed from those,
# never from a specific run's (possibly PHI-derived) scenarios. The surface name
# is itself part of the hash, so a text surface and the vision surface (recorded
# as "vision_carb") can never collide on a lock key.
TEXT_SURFACES: tuple[str, ...] = (
    "meal_analysis",
    "daily_brief",
    "correction",
    "chat",
    "chat_rag",
    "adversarial",
)

_SCENARIO_ROOT = Path(__file__).resolve().parents[1] / "scenarios"
_LOCK_PATH = Path(__file__).resolve().parents[1] / "harness_versions.json"


def canonical_surface_dir(surface: str) -> Path:
    """The canonical scenario directory a surface's version is computed from."""
    return _SCENARIO_ROOT / surface


def _floor_source() -> str:
    """The full source of the production safety floor the scorers run.

    The benchmark's ``score_safety`` delegates the REJECTED/FLAGGED decision to
    ``validate_ai_suggestion``, which depends on module-level constants and
    helpers (``DANGEROUS_PATTERNS``, the ±20% over-change threshold, the carb-
    ratio / ISF / prescriptive-dose regexes, ``_check_dangerous_content``, …).
    Those live *outside* any single function body, so hashing individual function
    sources would miss a weakened regex or threshold — a silent stale-PASS, the
    exact failure this kernel exists to prevent. So we hash the WHOLE floor module
    (the same whole-file approach used for the scorers). An unrelated edit to that
    module over-bumps every surface, which for a safety gate is the correct trade:
    an occasional spurious re-record is harmless; a missed floor edit is not.
    """
    return Path(safety_validation.__file__).read_text(encoding="utf-8")


def _floor_revision() -> str:
    """A content hash of the whole production safety-floor module."""
    return sha256_hex(_floor_source())


def _require_surface_dir(surface: str) -> Path:
    """The canonical scenario directory for a surface, or raise.

    Fail closed: an empty hash over a missing directory would let a renamed or
    deleted ``scenarios/<surface>/`` keep the lock gate green while the surface
    silently dropped out of the regression kernel — the exact stale-PASS this
    kernel exists to prevent."""
    surface_dir = canonical_surface_dir(surface)
    if not surface_dir.is_dir():
        raise FileNotFoundError(
            f"canonical scenario directory missing for surface {surface!r}: "
            f"{surface_dir}"
        )
    return surface_dir


def _rendered_prompts(surface: str) -> list[dict[str, str]]:
    """The real production (system, user) prompts for every canonical scenario of
    a surface, rendered through the live ``_build_prompt`` — the moat: the version
    covers exactly the prompts production sends, so the verdict cannot drift from
    what production does."""
    surface_dir = _require_surface_dir(surface)
    rendered: list[dict[str, str]] = []
    for scenario in load_scenarios(surface_dir):
        system_prompt, user_prompt = _build_prompt(scenario)
        rendered.append(
            {"id": scenario.id, "system": system_prompt, "user": user_prompt}
        )
    # Stable order so the hash does not depend on filesystem iteration order.
    rendered.sort(key=lambda r: r["id"])
    return rendered


def _scenario_manifest(surface: str) -> list[dict[str, Any]]:
    """Scoring-relevant refs for every canonical scenario of a surface.

    Captures what affects the verdict beyond the rendered prompt — the ground
    truth (expected status, cited numbers, dose expectation), the display unit,
    and the adversarial attack type — so a dataset edit that changes scoring (not
    just prose) invalidates the surface."""
    surface_dir = _require_surface_dir(surface)
    manifest: list[dict[str, Any]] = []
    for scenario in load_scenarios(surface_dir):
        manifest.append(
            {
                "id": scenario.id,
                "surface": scenario.surface,
                "units": scenario.units,
                "input": scenario.input,
                "ground_truth": scenario.ground_truth.model_dump(),
                "attack_type": scenario.attack_type,
                "expected_behavior": scenario.expected_behavior,
            }
        )
    manifest.sort(key=lambda s: s["id"])
    return manifest


def compute_harness_version(surface: str) -> str:
    """The content version for one text surface: ``sha256:<hex>``.

    Stable across an unrelated edit, and changes the instant the rendered prod
    prompts, the scorer source, the floor revision, a safety threshold, or the
    scoring-relevant scenario manifest for that surface changes.
    """
    components = {
        "schema": 1,
        "surface": surface,
        "prompts": _rendered_prompts(surface),
        "scorers": sha256_hex(Path(scorers.__file__).read_text(encoding="utf-8")),
        "floor": _floor_revision(),
        # The glucose thresholds defined OUTSIDE the floor module (the unit factor
        # and the canonical reading bound). The floor's own thresholds (e.g. the
        # ±20% over-change limit) live in safety_validation.py and are already
        # covered by the whole-module floor hash above, so they are not repeated
        # here.
        "thresholds": {
            "mgdl_per_mmol": MGDL_PER_MMOL,
            "min_glucose_mgdl": MIN_GLUCOSE_MGDL,
            "max_glucose_mgdl": MAX_GLUCOSE_MGDL,
        },
        "manifest": _scenario_manifest(surface),
    }
    return content_digest(components)


def compute_text_versions() -> dict[str, str]:
    """Every text surface's current version, by surface name."""
    return {surface: compute_harness_version(surface) for surface in TEXT_SURFACES}


def load_lock(path: Path | None = None) -> dict[str, str]:
    """The committed expected versions (all surfaces). Empty if absent."""
    lock_path = path or _LOCK_PATH
    if not lock_path.is_file():
        return {}
    return json.loads(lock_path.read_text(encoding="utf-8"))


def _update_lock() -> int:
    """Recompute the text surfaces and write them into the committed lock,
    preserving any non-text (e.g. vision) entries the vision harness owns.

    The vision surface's version is recorded by its own tooling
    (``evals/vision_carb``); merging here means the text bump never clobbers it.
    """
    versions = compute_text_versions()
    lock = load_lock()
    lock.update(versions)
    # Sorted keys + trailing newline so the committed file has a stable,
    # diff-friendly shape across re-records.
    _LOCK_PATH.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(versions)} text surface version(s) to {_LOCK_PATH}")
    for surface, version in sorted(versions.items()):
        print(f"  {surface}: {version}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="benchmarks.core.version")
    parser.add_argument(
        "--update-lock",
        action="store_true",
        help="recompute the text-surface versions and write the committed lock "
        "(the 'bump' after an intentional prompt/scorer/floor/threshold change)",
    )
    args = parser.parse_args()
    if args.update_lock:
        return _update_lock()
    for surface, version in compute_text_versions().items():
        print(f"{surface}: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
