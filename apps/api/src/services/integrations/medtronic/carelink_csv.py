"""Parser for the Medtronic CareLink "Data Export (CSV)" file.

Clean-room: written from our own observation of the export format, not from
any third-party library's source.

The export is a *multi-section* CSV: a metadata preamble (patient/device
header), then one or more data sections. Each section starts with a column
header row beginning ``Index,Date,Time,...`` followed by its data rows
(``Index`` restarts at 0 per section). Columns are mapped **by name**, so the
parser is resilient to column re-ordering or additions across pump
models/firmware.

This module does ONE thing: turn the messy CSV into a clean stream of typed
``CareLinkRow`` records (parsed timestamp + the fields we care about, plus the
full raw row). Classifying rows into our PumpEvent/glucose model is a separate
mapper, kept apart for testability (mirrors the Nightscout parser/mapper split).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime

# --- Canonical CareLink column names (observed in the v15.x export header) ---
COL_INDEX = "Index"
COL_DATE = "Date"
COL_TIME = "Time"
COL_BG_SOURCE = "BG Source"
COL_BG_READING = "BG Reading (mg/dL)"
COL_BASAL_RATE = "Basal Rate (U/h)"
COL_TEMP_BASAL_AMOUNT = "Temp Basal Amount"
COL_TEMP_BASAL_TYPE = "Temp Basal Type"
COL_TEMP_BASAL_DURATION = "Temp Basal Duration (h:mm:ss)"
COL_BOLUS_TYPE = "Bolus Type"
COL_BOLUS_SELECTED = "Bolus Volume Selected (U)"
COL_BOLUS_DELIVERED = "Bolus Volume Delivered (U)"
COL_BOLUS_SOURCE = "Bolus Source"
COL_BWZ_CARB_INPUT = "BWZ Carb Input (grams)"
COL_BWZ_ACTIVE_INSULIN = "BWZ Active Insulin (U)"
COL_SENSOR_GLUCOSE = "Sensor Glucose (mg/dL)"
COL_ISIG = "ISIG Value"
COL_ALERT = "Alert"
COL_SUSPEND = "Suspend"
COL_REWIND = "Rewind"
COL_EVENT_MARKER = "Event Marker"
COL_SENSOR_STATE = "Sensor State"

_HEADER_FIRST_COL = COL_INDEX

# Date formats seen / plausible across locales. The US web export emits the
# data-row date as YYYY/MM/DD with a 24h time; we try the observed format
# first, then defensive fallbacks (EU day-first, dash separators).
_DATE_FORMATS = (
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%m-%d-%Y",
)
_TIME_FORMATS = ("%H:%M:%S", "%H:%M")


@dataclass
class CareLinkRow:
    """One parsed data row from a CareLink export section."""

    timestamp: datetime | None
    index: int | None
    bg_source: str | None = None
    bg_mgdl: int | None = None
    sensor_glucose_mgdl: int | None = None
    isig: float | None = None
    basal_rate_uh: float | None = None
    temp_basal_amount: float | None = None
    temp_basal_type: str | None = None
    temp_basal_duration: str | None = None
    bolus_type: str | None = None
    bolus_selected_u: float | None = None
    bolus_delivered_u: float | None = None
    bolus_source: str | None = None
    carb_input_g: float | None = None
    active_insulin_u: float | None = None
    alert: str | None = None
    suspend: str | None = None
    rewind: str | None = None
    event_marker: str | None = None
    sensor_state: str | None = None
    # Full original row (canonical-name -> raw string) for anything not lifted
    # into a typed field above. Lets the mapper reach rarely-used columns
    # without re-parsing.
    raw: dict[str, str] = field(default_factory=dict)


@dataclass
class CareLinkExport:
    """A parsed CareLink CSV export: device metadata + all data rows."""

    rows: list[CareLinkRow] = field(default_factory=list)
    device: str | None = None
    serial_number: str | None = None
    cgm: str | None = None
    section_count: int = 0


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return v or None


def _parse_float(value: str | None) -> float | None:
    v = _clean(value)
    if v is None:
        return None
    # Tolerate a European decimal comma when it's unambiguously the decimal
    # mark (no dot present), e.g. "1,5" -> 1.5.
    if "," in v and "." not in v:
        v = v.replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    f = _parse_float(value)
    if f is None:
        return None
    try:
        return int(round(f))
    except (ValueError, OverflowError):
        return None


def _parse_timestamp(date_s: str | None, time_s: str | None) -> datetime | None:
    d = _clean(date_s)
    t = _clean(time_s)
    if not d:
        return None
    # Time may be absent on some rows; default to midnight so the row still
    # carries a usable date.
    t = t or "00:00:00"
    for df in _DATE_FORMATS:
        for tf in _TIME_FORMATS:
            try:
                return datetime.strptime(f"{d} {t}", f"{df} {tf}")
            except ValueError:
                continue
    # Date alone (no parseable time)
    for df in _DATE_FORMATS:
        try:
            return datetime.strptime(d, df)
        except ValueError:
            continue
    return None


def _detect_delimiter(text: str) -> str:
    """CareLink US exports are comma-delimited; some locales use semicolons.
    Decide from the header row (the one starting with ``Index``)."""
    for line in text.splitlines():
        if line.startswith(_HEADER_FIRST_COL):
            return ";" if line.count(";") > line.count(",") else ","
    return ","


def parse_carelink_csv(text: str) -> CareLinkExport:
    """Parse a CareLink Data Export (CSV) into a :class:`CareLinkExport`.

    Tolerant by design: unknown/extra columns are ignored, missing fields
    become ``None``, unparseable rows are skipped rather than raising. Rows
    are emitted in file order across all sections.
    """
    export = CareLinkExport()
    if not text:
        return export

    # Strip a UTF-8 BOM if present (the export carries one).
    if text and text[0] == "﻿":
        text = text[1:]

    delimiter = _detect_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)

    header: list[str] | None = None
    col: dict[str, int] = {}

    def get(row: list[str], name: str) -> str | None:
        i = col.get(name)
        if i is None or i >= len(row):
            return None
        return row[i]

    for fields_ in reader:
        if not fields_:
            continue
        first = fields_[0].strip()

        # A new section header row.
        if first == _HEADER_FIRST_COL:
            header = [c.strip() for c in fields_]
            col = {name: i for i, name in enumerate(header)}
            export.section_count += 1
            continue

        # Metadata preamble lines (before the first header). Lift a few useful
        # device facts; ignore the rest.
        if header is None:
            _scan_metadata(fields_, export)
            continue

        # A data row: must have a numeric Index to count as one.
        idx = _parse_int(get(fields_, COL_INDEX))
        ts = _parse_timestamp(get(fields_, COL_DATE), get(fields_, COL_TIME))
        if idx is None and ts is None:
            continue

        raw = {header[i]: fields_[i] for i in range(min(len(header), len(fields_)))}
        export.rows.append(
            CareLinkRow(
                timestamp=ts,
                index=idx,
                bg_source=_clean(get(fields_, COL_BG_SOURCE)),
                bg_mgdl=_parse_int(get(fields_, COL_BG_READING)),
                sensor_glucose_mgdl=_parse_int(get(fields_, COL_SENSOR_GLUCOSE)),
                isig=_parse_float(get(fields_, COL_ISIG)),
                basal_rate_uh=_parse_float(get(fields_, COL_BASAL_RATE)),
                temp_basal_amount=_parse_float(get(fields_, COL_TEMP_BASAL_AMOUNT)),
                temp_basal_type=_clean(get(fields_, COL_TEMP_BASAL_TYPE)),
                temp_basal_duration=_clean(get(fields_, COL_TEMP_BASAL_DURATION)),
                bolus_type=_clean(get(fields_, COL_BOLUS_TYPE)),
                bolus_selected_u=_parse_float(get(fields_, COL_BOLUS_SELECTED)),
                bolus_delivered_u=_parse_float(get(fields_, COL_BOLUS_DELIVERED)),
                bolus_source=_clean(get(fields_, COL_BOLUS_SOURCE)),
                carb_input_g=_parse_float(get(fields_, COL_BWZ_CARB_INPUT)),
                active_insulin_u=_parse_float(get(fields_, COL_BWZ_ACTIVE_INSULIN)),
                alert=_clean(get(fields_, COL_ALERT)),
                suspend=_clean(get(fields_, COL_SUSPEND)),
                rewind=_clean(get(fields_, COL_REWIND)),
                event_marker=_clean(get(fields_, COL_EVENT_MARKER)),
                sensor_state=_clean(get(fields_, COL_SENSOR_STATE)),
                raw=raw,
            )
        )

    return export


def _scan_metadata(fields_: list[str], export: CareLinkExport) -> None:
    """Extract device/serial/CGM from the metadata preamble.

    The preamble is a loose key,value layout, e.g.
    ``...,Device,MiniMed 780G MMT-1884,...`` and ``"Serial Number",NG...``.
    We scan for known labels and take the following cell.
    """
    cells = [c.strip().strip('"') for c in fields_]
    for i, c in enumerate(cells):
        nxt = cells[i + 1] if i + 1 < len(cells) else None
        if c == "Device" and nxt and export.device is None:
            export.device = nxt
        elif c == "Serial Number" and nxt and export.serial_number is None:
            export.serial_number = nxt
        elif c == "CGM" and nxt and export.cgm is None:
            export.cgm = nxt
