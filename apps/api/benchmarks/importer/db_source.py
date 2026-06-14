"""Import a LocalSeries from the GlycemicGPT Postgres DB.

`rows_to_series` is a pure mapping (testable without a DB); `load_series_from_db`
is the thin query wrapper.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from benchmarks.importer.models import GlucosePoint, InsulinEvent, LocalSeries


def rows_to_series(glucose_rows: list[Any], pump_rows: list[Any]) -> LocalSeries:
    """Map ORM rows to a LocalSeries. Pump rows with units=None are skipped."""
    glucose = [
        GlucosePoint(timestamp=r.reading_timestamp, value_mgdl=float(r.value))
        for r in glucose_rows
    ]
    insulin = [
        InsulinEvent(
            timestamp=r.event_timestamp,
            units=float(r.units),
            is_automated=bool(getattr(r, "is_automated", False)),
        )
        for r in pump_rows
        if getattr(r, "units", None) is not None
    ]
    return LocalSeries(glucose=glucose, insulin=insulin)


async def load_series_from_db(
    db: Any, user_id: Any, start: datetime, end: datetime
) -> LocalSeries:
    """Query glucose + pump events in [start, end] for a user and map them."""
    from sqlalchemy import select

    from src.models.glucose import GlucoseReading
    from src.models.pump_data import PumpEvent

    g = await db.execute(
        select(GlucoseReading).where(
            GlucoseReading.user_id == user_id,
            GlucoseReading.reading_timestamp >= start,
            GlucoseReading.reading_timestamp < end,
        )
    )
    p = await db.execute(
        select(PumpEvent).where(
            PumpEvent.user_id == user_id,
            PumpEvent.event_timestamp >= start,
            PumpEvent.event_timestamp < end,
        )
    )
    return rows_to_series(list(g.scalars().all()), list(p.scalars().all()))
