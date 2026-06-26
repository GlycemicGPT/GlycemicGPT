from datetime import datetime

import pytest

from benchmarks.importer.models import LocalSeries
from benchmarks.importer.sources import parse_csv, parse_nightscout_entries
from src.core.units import MGDL_PER_MMOL


def test_parse_csv_mgdl():
    text = "timestamp,value\n2026-01-01T08:00:00,120\n2026-01-01T08:05:00,135\n"
    series = parse_csv(text, units="mg/dL")
    assert isinstance(series, LocalSeries)
    assert [round(p.value_mgdl) for p in series.glucose] == [120, 135]
    assert series.glucose[0].timestamp == datetime.fromisoformat("2026-01-01T08:00:00")


def test_parse_csv_mmol_converts_with_canonical_factor():
    text = "timestamp,value\n2026-01-01T08:00:00,6.0\n"
    series = parse_csv(text, units="mmol/L")
    # 6.0 mmol/L converts through the single canonical factor 18.0156 (not 18.018);
    # asserted exactly so any drift from the platform factor is caught.
    assert series.glucose[0].value_mgdl == pytest.approx(6.0 * MGDL_PER_MMOL)


def test_parse_csv_skips_malformed_rows():
    text = "timestamp,value\n2026-01-01T08:00:00,120\nbad,row\n,\n2026-01-01T08:10:00,not_a_number\n"
    series = parse_csv(text, units="mg/dL")
    assert len(series.glucose) == 1


def test_parse_nightscout_entries():
    data = [
        {"date": 1767254400000, "sgv": 142},  # epoch ms
        {"date": 1767254700000, "sgv": 150},
        {"dateString": "x"},  # no sgv/date -> skipped
    ]
    series = parse_nightscout_entries(data)
    assert [round(p.value_mgdl) for p in series.glucose] == [142, 150]


def test_parse_csv_drops_out_of_range_glucose():
    # 10 (< 20), 9999 (> 500) and -5 must be dropped at the parse boundary so a
    # malformed export can't seed an out-of-range scenario; only 120 survives.
    text = (
        "timestamp,value\n"
        "2026-01-01T08:00:00,10\n"
        "2026-01-01T08:05:00,9999\n"
        "2026-01-01T08:10:00,120\n"
        "2026-01-01T08:15:00,-5\n"
    )
    series = parse_csv(text, units="mg/dL")
    assert [round(p.value_mgdl) for p in series.glucose] == [120]


def test_parse_nightscout_drops_out_of_range_sgv():
    data = [
        {"date": 1767254400000, "sgv": 0},  # sensor error code, < 20 -> dropped
        {"date": 1767254700000, "sgv": 142},
        {"date": 1767255000000, "sgv": 700},  # > 500 -> dropped
    ]
    series = parse_nightscout_entries(data)
    assert [round(p.value_mgdl) for p in series.glucose] == [142]
