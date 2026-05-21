"""Map parsed CareLink rows into our normalized model.

Pure function (no DB): turns a :class:`CareLinkExport` into neutral typed
records (CGM glucose + pump events). A separate storage layer assigns
``user_id``/``received_at`` and upserts. Kept apart from the parser and from
persistence for testability (mirrors the Nightscout parser/mapper split).

Mapping mirrors the Tandem conventions so the two integrations populate the
same model the same way:
- SmartGuard auto-bolus (``Bolus Source = CLOSED_LOOP_AUTO_BOLUS``) ->
  CORRECTION + ``is_automated`` (analogous to Tandem Control-IQ corrections).
- A manual/wizard bolus -> BOLUS.
- Fingerstick meter reading -> BG_READING pump event (as Tandem does).
- Continuous Sensor Glucose -> a glucose reading (Medtronic provides CGM
  inline, unlike Tandem where glucose comes from Dexcom).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.models.pump_data import PumpEventType

from .carelink_csv import CareLinkExport, CareLinkRow

#: Source tag written on every persisted Medtronic row.
SOURCE = "medtronic"

#: ``Bolus Source`` value Medtronic uses for a SmartGuard auto-correction bolus.
_AUTO_BOLUS_SOURCE = "CLOSED_LOOP_AUTO_BOLUS"


@dataclass
class MappedGlucose:
    """A CGM sensor-glucose reading, ready for the glucose_readings table."""

    timestamp: datetime
    value_mgdl: int
    source: str = SOURCE


@dataclass
class MappedPumpEvent:
    """A normalized pump event, ready for the pump_events table."""

    event_type: PumpEventType
    timestamp: datetime
    units: float | None = None
    duration_minutes: int | None = None
    is_automated: bool = False
    control_iq_reason: str | None = None
    iob_at_event: float | None = None
    cob_at_event: float | None = None
    bg_at_event: int | None = None
    source: str = SOURCE


@dataclass
class MappedRecords:
    glucose: list[MappedGlucose] = field(default_factory=list)
    pump_events: list[MappedPumpEvent] = field(default_factory=list)


def _duration_to_minutes(hms: str | None) -> int | None:
    """Parse a CareLink ``h:mm:ss`` duration into whole minutes."""
    if not hms:
        return None
    parts = hms.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 3:
        h, m, s = nums
    elif len(nums) == 2:
        h, m, s = 0, nums[0], nums[1]
    else:
        return None
    return h * 60 + m + (1 if s >= 30 else 0)


def _map_row(row: CareLinkRow) -> tuple[list[MappedGlucose], list[MappedPumpEvent]]:
    """Map a single CareLink row to 0+ glucose readings and pump events.

    One CSV row generally carries one fact, but a wizard bolus row also carries
    carb/IOB context that we attach to the bolus event.
    """
    ts = row.timestamp
    glucose: list[MappedGlucose] = []
    events: list[MappedPumpEvent] = []
    if ts is None:
        return glucose, events

    # Continuous sensor glucose -> CGM reading.
    if row.sensor_glucose_mgdl is not None:
        glucose.append(MappedGlucose(timestamp=ts, value_mgdl=row.sensor_glucose_mgdl))

    # Fingerstick / meter BG -> BG_READING pump event (matches Tandem).
    if row.bg_mgdl is not None:
        events.append(
            MappedPumpEvent(
                event_type=PumpEventType.BG_READING,
                timestamp=ts,
                bg_at_event=row.bg_mgdl,
            )
        )

    # Bolus delivery.
    if row.bolus_delivered_u is not None and row.bolus_delivered_u > 0:
        auto = (row.bolus_source or "").upper() == _AUTO_BOLUS_SOURCE
        events.append(
            MappedPumpEvent(
                event_type=PumpEventType.CORRECTION if auto else PumpEventType.BOLUS,
                timestamp=ts,
                units=row.bolus_delivered_u,
                is_automated=auto,
                control_iq_reason="auto_correction" if auto else None,
                cob_at_event=row.carb_input_g,
                iob_at_event=row.active_insulin_u,
            )
        )
    # Carb-only entry (carbs logged without a bolus on this row).
    elif row.carb_input_g is not None and row.carb_input_g > 0:
        events.append(
            MappedPumpEvent(
                event_type=PumpEventType.CARBS,
                timestamp=ts,
                cob_at_event=row.carb_input_g,
                iob_at_event=row.active_insulin_u,
            )
        )

    # Temp basal (SmartGuard auto-adjusts basal -> mark automated) takes
    # precedence over a scheduled basal-rate change on the same row.
    if row.temp_basal_amount is not None:
        events.append(
            MappedPumpEvent(
                event_type=PumpEventType.BASAL,
                timestamp=ts,
                units=row.temp_basal_amount,
                duration_minutes=_duration_to_minutes(row.temp_basal_duration),
                is_automated=True,
                control_iq_reason="temp_basal",
            )
        )
    elif row.basal_rate_uh is not None:
        events.append(
            MappedPumpEvent(
                event_type=PumpEventType.BASAL,
                timestamp=ts,
                units=row.basal_rate_uh,
            )
        )

    # Suspend / resume.
    suspend = (row.suspend or "").upper()
    if suspend:
        if "NORMAL" in suspend:  # NORMAL_PUMPING -> resumed
            events.append(
                MappedPumpEvent(event_type=PumpEventType.RESUME, timestamp=ts)
            )
        elif "SUSPEND" in suspend:
            events.append(
                MappedPumpEvent(event_type=PumpEventType.SUSPEND, timestamp=ts)
            )

    return glucose, events


def map_carelink_export(export: CareLinkExport) -> MappedRecords:
    """Map a parsed CareLink export to normalized glucose + pump-event records.

    Storage dedupes on the natural keys (``user_id, reading_timestamp`` for
    glucose; ``user_id, event_timestamp, event_type`` for pump events), so this
    mapper does not need to dedupe -- it just maps in file order.
    """
    records = MappedRecords()
    for row in export.rows:
        glucose, events = _map_row(row)
        records.glucose.extend(glucose)
        records.pump_events.extend(events)
    return records
