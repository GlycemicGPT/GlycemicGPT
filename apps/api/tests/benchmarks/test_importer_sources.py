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


def test_parse_csv_accepts_exact_bounds_and_drops_just_outside():
    # Exactly 20 and 500 mg/dL are accepted; 19 and 501 are dropped.
    text = (
        "timestamp,value\n"
        "2026-01-01T00:00:00,20\n"
        "2026-01-01T00:01:00,500\n"
        "2026-01-01T00:02:00,19\n"
        "2026-01-01T00:03:00,501\n"
    )
    series = parse_csv(text, units="mg/dL")
    assert [round(p.value_mgdl) for p in series.glucose] == [20, 500]


def test_parse_csv_mmol_bounds_apply_after_conversion():
    # 1.0 mmol/L -> 18.0 mg/dL (<20, dropped); 1.2 -> ~21.6 (kept);
    # 27.7 -> ~499 (kept); 28.0 -> ~504 (>500, dropped). The ~1.1 and ~27.8
    # mmol/L edges straddle the canonical 20-500 mg/dL bound.
    text = (
        "timestamp,value\n"
        "2026-01-01T00:00:00,1.0\n"
        "2026-01-01T00:01:00,1.2\n"
        "2026-01-01T00:02:00,27.7\n"
        "2026-01-01T00:03:00,28.0\n"
    )
    series = parse_csv(text, units="mmol/L")
    kept = [round(p.value_mgdl) for p in series.glucose]
    assert kept == [round(1.2 * MGDL_PER_MMOL), round(27.7 * MGDL_PER_MMOL)]


def test_parse_csv_rejects_unknown_units():
    with pytest.raises(ValueError, match="unsupported glucose units"):
        parse_csv("timestamp,value\n2026-01-01T00:00:00,100\n", units="mmol")
