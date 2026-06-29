"""``run_suite`` stamps the per-surface harness version onto a canonical run, and
``None`` onto a custom-data run — the provenance rule that keeps a stamped verdict
traceable to exactly the prompts + dataset that produced it.
"""

from __future__ import annotations

import shutil

from benchmarks.clients import MockClient
from benchmarks.core.version import canonical_surface_dir, compute_harness_version
from benchmarks.suites import run_suite


async def test_canonical_run_stamps_the_surface_version() -> None:
    report = await run_suite(
        canonical_surface_dir("meal_analysis"),
        MockClient("Breakfast looked steady this week; discuss timing with your team."),
    )
    assert report["harness_version"] == compute_harness_version("meal_analysis")


async def test_custom_scenarios_dir_run_stamps_none(tmp_path) -> None:
    # A run over a non-canonical directory (e.g. anonymized local data) must NOT
    # be stamped with the canonical version, which describes other prompts/data.
    source = next(canonical_surface_dir("meal_analysis").glob("*.yaml"))
    shutil.copy(source, tmp_path / source.name)
    report = await run_suite(tmp_path, MockClient("Looks steady."))
    assert report["harness_version"] is None
