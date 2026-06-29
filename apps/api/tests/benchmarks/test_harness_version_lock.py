"""CI regression gate (text surfaces): the committed lock must match the
recomputed per-surface version.

This is the load-bearing half of the trust kernel. If a production prompt,
scorer, safety threshold, floor revision, or canonical scenario changes without
re-recording the lock, the recomputed version diverges and this test FAILS —
catching a change that would otherwise let a cached verdict drift from what
production does. The fix (after an *intentional* change) is to re-record: the
"bump". The vision surface is gated by the sibling test in
``evals/vision_carb/tests``; both read this one shared lock.
"""

from __future__ import annotations

import pytest

from benchmarks.core.version import (
    TEXT_SURFACES,
    compute_harness_version,
    load_lock,
)

_BUMP = "uv run python -m benchmarks.core.version --update-lock"


def test_lock_covers_every_text_surface() -> None:
    lock = load_lock()
    missing = [s for s in TEXT_SURFACES if s not in lock]
    assert not missing, (
        f"surfaces missing from the committed lock: {missing}. Run `{_BUMP}` and "
        f"commit apps/api/benchmarks/harness_versions.json."
    )


@pytest.mark.parametrize("surface", TEXT_SURFACES)
def test_text_surface_version_matches_lock(surface: str) -> None:
    lock = load_lock()
    expected = lock.get(surface)
    actual = compute_harness_version(surface)
    assert actual == expected, (
        f"harness version for {surface!r} drifted from the committed lock\n"
        f"  expected (lock): {expected}\n"
        f"  actual (now):    {actual}\n"
        f"A production prompt, scorer, threshold, floor revision, or canonical "
        f"scenario for this surface changed without re-recording. If that change "
        f"was intentional, run `{_BUMP}` and commit the updated lock."
    )
