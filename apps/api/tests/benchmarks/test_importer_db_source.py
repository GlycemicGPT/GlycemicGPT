from datetime import datetime
from types import SimpleNamespace

import pytest

from benchmarks.importer.db_source import rows_to_series
from benchmarks.importer.models import GlucosePoint


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


def test_rows_to_series_skips_null_and_out_of_range_glucose():
    glucose_rows = [
        SimpleNamespace(reading_timestamp=datetime(2026, 1, 1, 8, 0), value=None),
        SimpleNamespace(reading_timestamp=datetime(2026, 1, 1, 8, 1), value=9999.0),
        SimpleNamespace(reading_timestamp=datetime(2026, 1, 1, 8, 2), value=120.0),
        SimpleNamespace(reading_timestamp=datetime(2026, 1, 1, 8, 3), value=5.0),
    ]
    series = rows_to_series(glucose_rows, [])
    assert [round(p.value_mgdl) for p in series.glucose] == [120]


def test_glucose_point_rejects_out_of_range_value():
    # The canonical 20-500 mg/dL invariant lives on the model itself.
    with pytest.raises(ValueError, match="20-500 mg/dL"):
        GlucosePoint(timestamp=datetime(2026, 1, 1), value_mgdl=9999.0)
    with pytest.raises(ValueError, match="20-500 mg/dL"):
        GlucosePoint(timestamp=datetime(2026, 1, 1), value_mgdl=5.0)
    # Exact bounds are accepted.
    assert (
        GlucosePoint(timestamp=datetime(2026, 1, 1), value_mgdl=20.0).value_mgdl == 20.0
    )
    assert (
        GlucosePoint(timestamp=datetime(2026, 1, 1), value_mgdl=500.0).value_mgdl
        == 500.0
    )
