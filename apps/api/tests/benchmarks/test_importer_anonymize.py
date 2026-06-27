from datetime import datetime

from benchmarks.importer.anonymize import anonymize
from benchmarks.importer.models import GlucosePoint, InsulinEvent, LocalSeries


def _series():
    return LocalSeries(
        glucose=[
            GlucosePoint(datetime(2026, 1, 1, 8, 30), 120.0),
            GlucosePoint(datetime(2026, 1, 1, 9, 30), 140.0),
        ],
        insulin=[InsulinEvent(datetime(2026, 1, 1, 8, 35), 4.0)],
    )


def test_same_seed_same_shift():
    a = anonymize(_series(), seed=7)
    b = anonymize(_series(), seed=7)
    assert a.glucose[0].timestamp == b.glucose[0].timestamp


def test_time_of_day_preserved():
    out = anonymize(_series(), seed=7)
    assert out.glucose[0].timestamp.hour == 8
    assert out.glucose[0].timestamp.minute == 30
    assert out.glucose[1].timestamp.hour == 9


def test_relative_gaps_preserved():
    src = _series()
    out = anonymize(src, seed=3)
    src_gap = src.glucose[1].timestamp - src.glucose[0].timestamp
    out_gap = out.glucose[1].timestamp - out.glucose[0].timestamp
    assert src_gap == out_gap


def test_does_not_mutate_input():
    src = _series()
    original = src.glucose[0].timestamp
    anonymize(src, seed=1)
    assert src.glucose[0].timestamp == original


def test_explicit_shift_days_honored():
    src = _series()
    out = anonymize(src, date_shift_days=-100)
    assert (src.glucose[0].timestamp - out.glucose[0].timestamp).days == 100
