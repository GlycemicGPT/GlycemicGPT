"""Pure parsers for local glucose data: CSV and Nightscout entries export.

No PII (names, IDs, device serials, free-text notes) is read or stored -- only
timestamps and glucose values. mmol/L is converted to mg/dL on import.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from benchmarks.importer.models import GlucosePoint, LocalSeries
from src.core.treatment_safety.models import MAX_GLUCOSE_MGDL, MIN_GLUCOSE_MGDL
from src.core.units import MGDL_PER_MMOL


def _in_canonical_range(value_mgdl: float) -> bool:
    """Whether a glucose value is within the platform-wide 20-500 mg/dL bound.

    Every persisted/compared glucose value must be canonical mg/dL inside this
    range; an out-of-range point (a malformed export, a mis-declared mmol/L
    file, a sensor error code like 0 or 9999) is dropped at the parse boundary
    so it can never seed an invalid benchmark scenario."""
    return MIN_GLUCOSE_MGDL <= value_mgdl <= MAX_GLUCOSE_MGDL


def parse_csv(text: str, units: str = "mg/dL") -> LocalSeries:
    """Parse a CSV with header `timestamp,value`. Malformed and out-of-range
    (20-500 mg/dL) rows are skipped. mmol/L is converted through the single
    canonical factor before the bound is applied."""
    # Fail fast on an unknown unit label: silently treating a typo as mg/dL would
    # store mmol/L data unconverted (corrupt canonical values).
    if units not in {"mg/dL", "mmol/L"}:
        raise ValueError(
            f"unsupported glucose units: {units!r} (expected mg/dL or mmol/L)"
        )
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
            value *= MGDL_PER_MMOL
        if not _in_canonical_range(value):
            continue
        series.glucose.append(GlucosePoint(timestamp=ts, value_mgdl=value))
    return series


def parse_nightscout_entries(data: list[dict]) -> LocalSeries:
    """Parse a Nightscout entries.json array (objects with `date` epoch-ms and
    `sgv` mg/dL). Entries lacking sgv/date, or with an out-of-range (20-500
    mg/dL) sgv, are skipped."""
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
        if not _in_canonical_range(value):
            continue
        series.glucose.append(GlucosePoint(timestamp=ts, value_mgdl=value))
    return series
