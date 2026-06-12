"""Translate Glooko raw JSON into our normalized glucose + pump-event rows.

Pure functions (no DB) -- they turn captured Glooko payloads into neutral typed
``Mapped*`` records that ``storage.store_glooko_records`` persists into the same
``glucose_readings`` / ``pump_events`` tables every other source uses
(``source = "glooko"``). All shapes/units/timezone semantics come from our own
live capture of the Glooko protocol, not from any third-party source.

Coverage (confirmed in the live capture): CGM glucose (v3 graph ``cgm*`` series), scheduled
basal, normal bolus (carrying IOB/carbs/BG context), pod-lifecycle / suspend
/ resume events, and smart-pen insulin doses (``insulins`` stream -- NovoPen 6 /
Echo Plus + manual logs). Pump modes + alarms are out of scope here (informational only).

Clean-room attribution: the Tidepool ``deviceEvent`` data model (BSD-2-Clause)
informed the pod-change/reservoir modeling; ``nightscout-connect`` and the
``jpollock`` glooko2nightscout bridge (AGPL-3.0) are protocol references only --
no code copied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

from src.models.pump_data import PumpEventType

SOURCE = "glooko"

# Physiologic CGM bounds (mg/dL). Drop anything outside so a corrupt/unit-confused
# value can't poison TIR/alerts/AI context (same defensive stance as Medtronic).
_SG_MIN_MGDL = 10
_SG_MAX_MGDL = 600

# Sanity bound on basal rate (U/h) -- reject implausible rates a TDD calc would
# multiply into a catastrophic daily total.
_MAX_BASAL_RATE_UH = 35.0

# Glooko pump-events ``type`` -> our PumpEventType. Pod/cartridge/prime lifecycle
# events all become DEVICE_EVENT (the specific Glooko type is preserved in
# metadata_json); suspend/resume map to their dedicated types.
_EVENT_TYPE_MAP: dict[str, PumpEventType] = {
    "insulin_suspended": PumpEventType.SUSPEND,
    "insulin_suspended_continued": PumpEventType.SUSPEND,
    "insulin_resumed": PumpEventType.RESUME,
    "pod_activating": PumpEventType.DEVICE_EVENT,
    "pod_deactivated": PumpEventType.DEVICE_EVENT,
    "pod_discarded": PumpEventType.DEVICE_EVENT,
    "reservoir_change": PumpEventType.DEVICE_EVENT,
    "prime_cannula": PumpEventType.DEVICE_EVENT,
    "prime_tubing": PumpEventType.DEVICE_EVENT,
}


@dataclass
class MappedGlucose:
    timestamp: datetime  # tz-aware UTC
    value_mgdl: int
    source: str = SOURCE


@dataclass
class MappedPumpEvent:
    event_type: PumpEventType
    timestamp: datetime  # tz-aware UTC
    ns_id: str | None = None  # Glooko `guid` -- the stable idempotency key
    units: float | None = None
    duration_minutes: int | None = None
    is_automated: bool = False
    iob_at_event: float | None = None
    cob_at_event: float | None = None
    bg_at_event: int | None = None
    metadata_json: dict | None = None
    source: str = SOURCE


@dataclass
class MappedRecords:
    glucose: list[MappedGlucose] = field(default_factory=list)
    pump_events: list[MappedPumpEvent] = field(default_factory=list)


def _parse_utc(value: object) -> datetime | None:
    """Parse a genuine-UTC ISO string (graph/data CGM timestamps end in ``Z``)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo is not None else None


def _parse_pump_ts(timestamp: object, offset: object) -> datetime | None:
    """Resolve a pump-data timestamp to UTC.

    FOOTGUN (observed in the live capture): ``pumpTimestamp`` is LOCAL wall-clock time serialized with a
    misleading trailing ``Z``; the real offset is the separate
    ``pumpTimestampUtcOffset`` (e.g. ``-04:00``). UTC = local-wall-time interpreted
    AT that offset. We refuse a missing/garbage offset rather than misdate a medical
    record by treating local time as UTC.
    """
    if not isinstance(timestamp, str) or not timestamp:
        return None
    try:
        naive = datetime.fromisoformat(timestamp.replace("Z", ""))
    except ValueError:
        return None
    if naive.tzinfo is not None:  # already carries a real offset -> trust it
        return naive.astimezone(UTC)
    if not isinstance(offset, str) or not offset:
        return None
    try:
        sign = 1 if offset[0] != "-" else -1
        hh, mm = offset.lstrip("+-").split(":")
        delta = sign * timedelta(hours=int(hh), minutes=int(mm))
    except (ValueError, IndexError):
        return None
    return naive.replace(tzinfo=timezone(delta)).astimezone(UTC)


def _is_soft_deleted(r: dict) -> bool:
    """A record the user deleted in Glooko. Reverse-eng §9/§11: skip these, or a
    deleted bolus/pod-change would be ingested into TDD/IOB/AI context and -- since
    rows are keyed by stable guid -- never removed on a later re-sync."""
    return bool(r.get("softDeleted") or r.get("soft_deleted"))


def map_cgm_points(points: list[dict]) -> list[MappedGlucose]:
    """Map merged graph/data CGM points (``cgmHigh``∪``cgmNormal``∪``cgmLow``).

    Each point: ``{y: mg/dL, value: mg/dL*100, timestamp: UTC-ISO, calculated: bool}``.
    Glucose has no trend in graph/data -> the row gets ``NOT_COMPUTABLE`` at storage.
    """
    out: list[MappedGlucose] = []
    for p in points:
        if not isinstance(p, dict):
            continue
        ts = _parse_utc(p.get("timestamp"))
        raw = p.get("y")
        if ts is None or not isinstance(raw, (int, float)):
            continue
        value = int(round(raw))
        if not (_SG_MIN_MGDL <= value <= _SG_MAX_MGDL):
            continue
        out.append(MappedGlucose(timestamp=ts, value_mgdl=value))
    return out


def map_scheduled_basals(records: list[dict]) -> list[MappedPumpEvent]:
    """Map ``scheduledBasals`` -> BASAL events (``units`` = rate in U/h)."""
    out: list[MappedPumpEvent] = []
    for r in records:
        if not isinstance(r, dict) or _is_soft_deleted(r):
            continue
        ts = _parse_pump_ts(r.get("pumpTimestamp"), r.get("pumpTimestampUtcOffset"))
        rate = r.get("rate")
        if (
            ts is None
            or not isinstance(rate, (int, float))
            or rate < 0
            or rate > _MAX_BASAL_RATE_UH
        ):
            continue
        duration = r.get("duration")
        out.append(
            MappedPumpEvent(
                event_type=PumpEventType.BASAL,
                timestamp=ts,
                ns_id=_str_or_none(r.get("guid")),
                units=float(rate),
                duration_minutes=int(duration // 60)
                if isinstance(duration, (int, float))
                else None,
            )
        )
    return out


def map_normal_boluses(records: list[dict]) -> list[MappedPumpEvent]:
    """Map ``normalBoluses`` -> BOLUS events with IOB/carbs/BG context."""
    out: list[MappedPumpEvent] = []
    for r in records:
        if not isinstance(r, dict) or _is_soft_deleted(r):
            continue
        ts = _parse_pump_ts(r.get("pumpTimestamp"), r.get("pumpTimestampUtcOffset"))
        delivered = r.get("insulinDelivered")
        # Reject negative delivery the same way basal rejects negative rates --
        # a negative dose is impossible and would corrupt insulin totals.
        if ts is None or not isinstance(delivered, (int, float)) or delivered < 0:
            continue
        bg = r.get("bloodGlucoseInput")
        carbs = r.get("carbsInput")
        iob = r.get("insulinOnBoard")
        out.append(
            MappedPumpEvent(
                event_type=PumpEventType.BOLUS,
                timestamp=ts,
                ns_id=_str_or_none(r.get("guid")),
                units=float(delivered),
                # Omnipod 5 SmartAdjust auto-bolus shows as type "automatic".
                is_automated=str(r.get("type", "")).lower() == "automatic",
                iob_at_event=float(iob) if isinstance(iob, (int, float)) else None,
                cob_at_event=float(carbs)
                if isinstance(carbs, (int, float)) and carbs > 0
                else None,
                bg_at_event=int(bg)
                if isinstance(bg, (int, float)) and bg > 0
                else None,
            )
        )
    return out


def map_events(records: list[dict]) -> list[MappedPumpEvent]:
    """Map ``pumps/events`` -> SUSPEND / RESUME / DEVICE_EVENT.

    Unknown event types are skipped (not guessed) -- the specific Glooko type is
    preserved in ``metadata_json`` so downstream/AI can read the pod-change detail.
    """
    out: list[MappedPumpEvent] = []
    for r in records:
        if not isinstance(r, dict) or _is_soft_deleted(r):
            continue
        gtype = str(r.get("type", ""))
        mapped = _EVENT_TYPE_MAP.get(gtype)
        if mapped is None:
            continue
        ts = _parse_pump_ts(r.get("pumpTimestamp"), r.get("pumpTimestampUtcOffset"))
        if ts is None:
            continue
        out.append(
            MappedPumpEvent(
                event_type=mapped,
                timestamp=ts,
                ns_id=_str_or_none(r.get("guid")),
                metadata_json={"glooko_event": gtype}
                if mapped is PumpEventType.DEVICE_EVENT
                else None,
            )
        )
    return out


def map_insulins(records: list[dict]) -> list[MappedPumpEvent]:
    """Map ``insulins`` (smart-pen doses + manual insulin logs) -> BOLUS events.

    Live finding (NovoPen 6 / Echo Plus capture): the record ``timestamp`` is
    genuine UTC -- verified against known dose times on a CEST wall clock --
    unlike the pump streams' local-with-fake-``Z`` footgun, so the strict UTC
    parser applies and there is no offset field to consult.

    Skipped (refuse rather than mis-model a medical record):

    * soft-deleted -- same reasoning as every other stream
    * priming shots (``suspectedPrime`` / ``acceptedPrime``) -- pen actuations
      that never enter the body; ingesting them inflates dose totals and IoB
    * ``incomplete`` -- Glooko marks the dose value unconfirmed
    * non-``bolus`` ``insulinType`` -- long-acting pen doses don't fit the
      BASAL event's rate (U/h) semantics; deferred like ``extended_boluses``
      (add modeling + mapping together, never one without the other)
    """
    out: list[MappedPumpEvent] = []
    for r in records:
        if not isinstance(r, dict) or _is_soft_deleted(r):
            continue
        if r.get("suspectedPrime") or r.get("acceptedPrime"):
            continue
        if r.get("incomplete"):
            continue
        if str(r.get("insulinType", "")).lower() != "bolus":
            continue
        ts = _parse_utc(r.get("timestamp"))
        value = r.get("value")
        # Negative doses are impossible -- same guard as map_normal_boluses.
        if ts is None or not isinstance(value, (int, float)) or value < 0:
            continue
        metadata: dict = {"glooko_stream": "insulins"}
        medication = _str_or_none(r.get("name")) or _str_or_none(
            r.get("medicationGuid")
        )
        if medication:
            metadata["medication"] = medication
        pen_device = _str_or_none(r.get("deviceShortDisplayName"))
        if pen_device:
            metadata["pen_device"] = pen_device
        # False = the dose was typed into the Glooko app by hand, not read from
        # a pen -- preserved so downstream can weigh device-read vs manual data.
        metadata["device_delivered"] = bool(r.get("deviceDelivered"))
        out.append(
            MappedPumpEvent(
                event_type=PumpEventType.BOLUS,
                timestamp=ts,
                ns_id=_str_or_none(r.get("guid")),
                units=float(value),
                metadata_json=metadata,
            )
        )
    return out


def map_glooko(
    *,
    cgm_points: list[dict] | None = None,
    scheduled_basals: list[dict] | None = None,
    normal_boluses: list[dict] | None = None,
    events: list[dict] | None = None,
    insulins: list[dict] | None = None,
) -> MappedRecords:
    """Map any combination of the captured Glooko series into one MappedRecords."""
    records = MappedRecords()
    if cgm_points:
        records.glucose.extend(map_cgm_points(cgm_points))
    if scheduled_basals:
        records.pump_events.extend(map_scheduled_basals(scheduled_basals))
    if normal_boluses:
        records.pump_events.extend(map_normal_boluses(normal_boluses))
    if events:
        records.pump_events.extend(map_events(events))
    if insulins:
        records.pump_events.extend(map_insulins(insulins))
    return records


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
