"""Pure parsers for local glucose data: CSV and Nightscout entries export.

No PII (names, IDs, device serials, free-text notes) is read or stored -- only
timestamps and glucose values. mmol/L is converted to mg/dL on import.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from benchmarks.importer.models import GlucosePoint, LocalSeries

MMOL_TO_MGDL = 18.018


def parse_csv(text: str, units: str = "mg/dL") -> LocalSeries:
    """Parse a CSV with header `timestamp,value`. Malformed rows are skipped."""
    series = LocalSeries()
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        ts_raw = (row.get("timestamp") or "").strip()
        val_raw = (row.get("value") or "").strip()
        if not ts_raw or not val_raw:
            continue
        try:
            ts = datetime.fromisoformat(ts_raw)
            value = float(val_raw)
        except ValueError:
            continue
        if units == "mmol/L":
            value *= MMOL_TO_MGDL
        series.glucose.append(GlucosePoint(timestamp=ts, value_mgdl=value))
    return series


def parse_nightscout_entries(data: list[dict]) -> LocalSeries:
    """Parse a Nightscout entries.json array (objects with `date` epoch-ms and
    `sgv` mg/dL). Entries lacking sgv/date are skipped."""
    series = LocalSeries()
    for entry in data:
        sgv = entry.get("sgv")
        date_ms = entry.get("date")
        if sgv is None or date_ms is None:
            continue
        try:
            ts = datetime.fromtimestamp(float(date_ms) / 1000.0, tz=UTC)
            value = float(sgv)
        except (ValueError, TypeError):
            continue
        series.glucose.append(GlucosePoint(timestamp=ts, value_mgdl=value))
    return series
