from datetime import datetime

from benchmarks.importer.models import LocalSeries
from benchmarks.importer.sources import parse_csv, parse_nightscout_entries


def test_parse_csv_mgdl():
    text = "timestamp,value\n2026-01-01T08:00:00,120\n2026-01-01T08:05:00,135\n"
    series = parse_csv(text, units="mg/dL")
    assert isinstance(series, LocalSeries)
    assert [round(p.value_mgdl) for p in series.glucose] == [120, 135]
    assert series.glucose[0].timestamp == datetime.fromisoformat("2026-01-01T08:00:00")


def test_parse_csv_mmol_converts_to_mgdl():
    text = "timestamp,value\n2026-01-01T08:00:00,6.0\n"
    series = parse_csv(text, units="mmol/L")
    # 6.0 mmol/L * 18.018 ~= 108
    assert 107 <= series.glucose[0].value_mgdl <= 109


def test_parse_csv_skips_malformed_rows():
    text = "timestamp,value\n2026-01-01T08:00:00,120\nbad,row\n,\n2026-01-01T08:10:00,not_a_number\n"
    series = parse_csv(text, units="mg/dL")
    assert len(series.glucose) == 1


def test_parse_nightscout_entries():
    data = [
        {"date": 1767254400000, "sgv": 142},  # epoch ms
        {"date": 1767254700000, "sgv": 150},
        {"dateString": "x"},                    # no sgv/date -> skipped
    ]
    series = parse_nightscout_entries(data)
    assert [round(p.value_mgdl) for p in series.glucose] == [142, 150]
