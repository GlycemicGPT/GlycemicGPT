"""Content version for the vision carb pass-bar — the vision counterpart of the
text harness's per-surface ``compute_harness_version``.

Same purpose as the text version (make a cached verdict content-invalidatable),
hashed over the vision-appropriate components:

  * the real production vision prompts (``carb_contract.SYSTEM_PROMPT`` /
    ``USER_PROMPT``, re-exported here as ``contract`` — the same constants the
    live estimation pipeline sends, so the version covers exactly what production
    asks the model);
  * the FULL scorer source — ``passbar.py`` + ``metrics.py`` + the production
    ``carb_contract.py``. Whole-file (not per-function) for the same reason the
    text floor is hashed whole-file: the dosing detector ``_DOSING_PATTERNS`` and
    the estimate parser's helpers are module-level, outside any single function
    body, so a per-function hash would miss a weakened regex — a stale-PASS on the
    #1 hard gate (``MAX_DOSING_VIOLATIONS == 0``).
  * the pass-bar thresholds and the absolute carb bounds;
  * a digest of the dataset MANIFEST — the full item entries (ids, labels,
    expected identities, image FILENAMES), **never the image bytes**. The set is
    image-heavy and license-encumbered; the manifest holds only references (the
    pixels live in ``dataset/images/`` and are never read), so the version is
    computable in CI without the images present.

It is deliberately standalone (bare ``contract``/``metrics``/``passbar`` imports)
so it computes in the same lean environment the harness runs in — pointed at a
local Ollama, with no FastAPI/SQLAlchemy. It shares only the tiny content-hashing
primitive with the text harness (one canonicalization, no drift); the two
versions hash disjoint component sets and never need to agree, each being the
single source of truth for its own surface in the shared lock.
"""

from __future__ import annotations

import json
import os as _os
import sys as _sys
from pathlib import Path
from typing import Any

# Put apps/api on the path (the same lightweight shim the carb contract uses)
# BEFORE importing the shared content-hashing primitive, so import order can't
# matter. The harness already requires apps/api on disk for the carb contract, so
# this adds no new dependency.
_API_ROOT = _os.path.abspath(
    _os.path.join(_os.path.dirname(__file__), "..", "..", "apps", "api")
)
if _API_ROOT not in _sys.path:
    _sys.path.insert(0, _API_ROOT)

import contract  # noqa: E402  re-exports the production carb contract (prompts + scan)
import metrics  # noqa: E402
import passbar  # noqa: E402

from src.core.content_digest import content_digest, sha256_hex  # noqa: E402
from src.vision import carb_contract  # noqa: E402  the real module behind `contract`

# The surface key this version is recorded under in the shared lock
# (``apps/api/benchmarks/harness_versions.json``). Distinct from every text
# surface so they can never collide on a key.
SURFACE = "vision_carb"

_HERE = Path(__file__).parent
_DATASET = _HERE / "dataset"
# The canonical scoring manifests (the easy gate set + the adversarial set).
_MANIFESTS = ("manifest.json", "adversarial.json")

# The shared lock the text harness also writes — the single content-addressed
# manifest every trust consumer reads. The vision surface owns only its own entry
# here; a re-record preserves the text surfaces, so neither harness clobbers the
# other.
_LOCK_PATH = (
    _HERE / ".." / ".." / "apps" / "api" / "benchmarks" / "harness_versions.json"
)


def _scorer_source() -> str:
    """The full source of every module that decides a vision verdict."""
    return (
        Path(passbar.__file__).read_text(encoding="utf-8")
        + Path(metrics.__file__).read_text(encoding="utf-8")
        + Path(carb_contract.__file__).read_text(encoding="utf-8")
    )


def _dataset_manifest() -> list[dict[str, Any]]:
    """Every dataset item's FULL manifest entry — references only, never bytes.

    The manifest holds filenames + labels; the image pixels live in
    ``dataset/images/`` and are not read here. Capturing the whole item (rather
    than a hand-maintained field allow-list) means a future scoring field cannot
    silently fail to bump the version — the same whole-input capture the text
    scenario manifest uses."""
    items: list[dict[str, Any]] = []
    found_manifest = False
    for name in _MANIFESTS:
        path = _DATASET / name
        if not path.is_file():
            continue
        found_manifest = True
        data = json.loads(path.read_text(encoding="utf-8"))
        set_name = data.get("set") or path.stem
        for item in data.get("items", []):
            items.append(
                {
                    "manifest": name,
                    "set": item.get("set") or set_name,
                    "item": item,
                }
            )
    if not found_manifest:
        # Fail closed: hashing an empty manifest would let a renamed/missing
        # dataset keep the lock gate green while the dataset dropped out.
        raise FileNotFoundError(
            f"no dataset manifest found under {_DATASET} (expected one of {_MANIFESTS})"
        )
    items.sort(
        key=lambda entry: (entry["manifest"], str(entry["item"].get("id") or ""))
    )
    return items


def compute_harness_version() -> str:
    """The content version for the vision surface: ``sha256:<hex>``."""
    components = {
        "schema": 1,
        "surface": SURFACE,
        "prompts": {"system": contract.SYSTEM_PROMPT, "user": contract.USER_PROMPT},
        "scorers": sha256_hex(_scorer_source()),
        "thresholds": {
            "max_dosing_violations": passbar.MAX_DOSING_VIOLATIONS,
            "max_easy_identity_error_rate": passbar.MAX_EASY_IDENTITY_ERROR_RATE,
            "max_easy_max_cv": passbar.MAX_EASY_MAX_CV,
            "max_easy_mean_cv": passbar.MAX_EASY_MEAN_CV,
            "max_easy_max_spread_g": passbar.MAX_EASY_MAX_SPREAD_G,
            "max_easy_mae_g": passbar.MAX_EASY_MAE_G,
            "min_certification_repeats": passbar.MIN_CERTIFICATION_REPEATS,
            "carb_grams_min": contract.CARB_GRAMS_MIN,
            "carb_grams_max": contract.CARB_GRAMS_MAX,
            "default_illustrative_icr": metrics.DEFAULT_ILLUSTRATIVE_ICR,
        },
        "manifest": _dataset_manifest(),
    }
    return content_digest(components)


def _update_lock() -> None:
    """Record the vision surface's version into the shared lock, preserving the
    text surfaces' entries (the 'bump' after an intentional vision prompt / scorer
    / threshold / dataset change)."""
    lock_path = _LOCK_PATH.resolve()
    lock: dict[str, str] = {}
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock[SURFACE] = compute_harness_version()
    lock_path.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {SURFACE}: {lock[SURFACE]} to {lock_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="vision_carb.harness_version")
    parser.add_argument(
        "--update-lock",
        action="store_true",
        help="record the vision surface version into the shared lock",
    )
    cli_args = parser.parse_args()
    if cli_args.update_lock:
        _update_lock()
    else:
        print(f"{SURFACE}: {compute_harness_version()}")
