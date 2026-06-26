from datetime import datetime
from types import SimpleNamespace

from benchmarks.importer.db_source import rows_to_series


def test_rows_to_series_maps_and_skips_none_units():
    glucose_rows = [
        SimpleNamespace(reading_timestamp=datetime(2026, 1, 1, 8, 0), value=120.0),
        SimpleNamespace(reading_timestamp=datetime(2026, 1, 1, 8, 5), value=140.0),
    ]
    pump_rows = [
        SimpleNamespace(
            event_timestamp=datetime(2026, 1, 1, 8, 2), units=4.0, is_automated=False
        ),
        SimpleNamespace(
            event_timestamp=datetime(2026, 1, 1, 8, 3), units=None, is_automated=True
        ),
    ]
    series = rows_to_series(glucose_rows, pump_rows)
    assert [round(p.value_mgdl) for p in series.glucose] == [120, 140]
    assert len(series.insulin) == 1  # None-units row skipped
    assert series.insulin[0].units == 4.0
