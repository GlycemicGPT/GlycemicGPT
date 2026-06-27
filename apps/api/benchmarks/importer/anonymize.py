"""Anonymize a LocalSeries by shifting all timestamps by a whole number of days.

A whole-day shift preserves time-of-day and every inter-event interval, so
meal-period and dawn patterns survive while the absolute calendar dates (a
re-identification vector) are obscured. No PII lives on LocalSeries, so this is
the remaining anonymization step. Deterministic when a seed is supplied.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import timedelta

from benchmarks.importer.models import LocalSeries


def anonymize(
    series: LocalSeries,
    *,
    date_shift_days: int | None = None,
    seed: int | None = None,
) -> LocalSeries:
    """Return a NEW LocalSeries with all timestamps shifted by whole days."""
    if date_shift_days is None:
        rng = random.Random(seed)
        date_shift_days = rng.randint(-400, -30)
    delta = timedelta(days=date_shift_days)
    return LocalSeries(
        glucose=[replace(p, timestamp=p.timestamp + delta) for p in series.glucose],
        insulin=[replace(e, timestamp=e.timestamp + delta) for e in series.insulin],
    )
