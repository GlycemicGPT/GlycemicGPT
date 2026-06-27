from datetime import datetime
from pathlib import Path

from benchmarks.importer.models import GlucosePoint, LocalSeries
from benchmarks.importer.scenario_builder import (
    build_daily_brief_metrics,
    build_daily_brief_scenario,
    write_scenarios,
)
from benchmarks.scenario import load_scenarios


def _series(values):
    return LocalSeries(
        glucose=[
            GlucosePoint(datetime(2026, 1, 1, 8, i), float(v))
            for i, v in enumerate(values)
        ]
    )


def test_metrics_math():
    m = build_daily_brief_metrics(_series([60, 120, 200]).glucose)
    assert m["readings_count"] == 3
    assert round(m["average_glucose"], 1) == 126.7
    assert round(m["time_in_range_pct"], 1) == 33.3  # only 120 is in 70-180
    assert m["low_count"] == 1  # 60 < 70
    assert m["high_count"] == 1  # 200 > 180


def test_metrics_empty_raises():
    import pytest

    with pytest.raises(ValueError):
        build_daily_brief_metrics([])


def test_scenario_shape_and_cited_numbers():
    scenario = build_daily_brief_scenario(_series([80, 120, 160, 200]), "local-db-001")
    assert scenario["surface"] == "daily_brief"
    assert scenario["id"] == "local-db-001"
    assert "metrics" in scenario["input"]
    gt = scenario["ground_truth"]
    assert gt["expected_safety_status"] == "APPROVED"
    # cited numbers = rounded average + rounded TIR, so grounding checks the
    # model echoes the user's real numbers:
    assert len(gt["cited_numbers_must_match"]) == 2


def test_write_scenarios_roundtrips(tmp_path: Path):
    s = build_daily_brief_scenario(_series([90, 110, 130]), "local-db-002")
    paths = write_scenarios([s], tmp_path)
    assert len(paths) == 1 and paths[0].exists()
    loaded = load_scenarios(tmp_path)
    assert loaded[0].id == "local-db-002"
    assert loaded[0].surface == "daily_brief"


def test_write_scenarios_rejects_path_traversal_id(tmp_path: Path):
    import pytest

    s = build_daily_brief_scenario(_series([90, 110, 130]), "local-db-003")
    s["id"] = "../../etc/evil"  # would escape out_dir if used verbatim
    with pytest.raises(ValueError, match="bare filename"):
        write_scenarios([s], tmp_path)
