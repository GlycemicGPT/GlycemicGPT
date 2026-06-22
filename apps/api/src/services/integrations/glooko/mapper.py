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

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

from src.models.pump_data import (
    MAX_BASAL_INJECTION_UNITS,
    MAX_INSULIN_DOSE_UNITS,
    PumpEventType,
)

SOURCE = "glooko"

# CGM bounds (mg/dL). Drop anything outside so a corrupt/unit-confused value can't
# poison TIR/alerts/AI context. 20-500 is the platform-wide glucose safety
# invariant: ``core.treatment_safety.models`` (MIN/MAX_GLUCOSE_MGDL = 20/500) and
# the AI-context / TIR / stats read filters in ``routers.integrations`` (all clamp
# to 20..500), plus the ``GlucoseReading`` storage ``ge=20`` floor. A wider
# Glooko-only bound would just admit values those consumers silently drop, so keep
# this source consistent with where the data is actually validated and used.
_SG_MIN_MGDL = 20
_SG_MAX_MGDL = 500

# Sanity bound on basal rate (U/h) -- reject implausible rates a TDD calc would
# multiply into a catastrophic daily total.
_MAX_BASAL_RATE_UH = 35.0

# Sanity bound on a single bolus/pen dose (U). The platform-wide
# ``MAX_INSULIN_DOSE_UNITS`` (NovoPen 6 max actuation = 60 U; pumps cap lower);
# anything above is a corrupt or unit-confused record that would poison IoB
# projection and safety totals (same stance as the basal/CGM bounds). Manual
# Glooko logs share the bound as corrupt-record protection -- logging
# concentrated (U-200/U-500) doses above 60 U is out of scope until the platform
# models insulin concentration. Aliased locally to keep the bounds-checking
# helpers reading in single-letter units.
_MAX_BOLUS_DOSE_U = MAX_INSULIN_DOSE_UNITS

# Sanity bound on a single long-acting (basal) pen INJECTION (U). Aliased from
# the canonical platform bound to keep the bounds-checking helpers reading in
# single-letter units; see ``MAX_BASAL_INJECTION_UNITS`` for the rationale (160 U
# = Tresiba U-200 FlexTouch max single injection). This bounds the discrete
# injected amount, NOT a U/h rate (that is _MAX_BASAL_RATE_UH).
_MAX_BASAL_INJECTION_U = MAX_BASAL_INJECTION_UNITS


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


def _finite_or_none(value: object) -> float | None:
    """A finite real number, else ``None``.

    Rejects non-numerics, ``bool`` (an ``int`` in Python, so ``True`` would
    otherwise ingest as 1.0), and NaN/inf (NaN slips through ``<``/``>`` bounds
    because every comparison on it is False).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def _dose_or_none(
    value: object,
    *,
    allow_zero: bool = False,
    max_units: float = _MAX_BOLUS_DOSE_U,
) -> float | None:
    """A plausible insulin dose in units, else ``None``.

    Bounds a finite number to ``(0, max_units]`` (default the bolus/pen
    actuation bound; long-acting injections pass ``_MAX_BASAL_INJECTION_U``).
    ``allow_zero`` admits exactly 0: a suggested pump bolus fully reduced by IoB
    records 0 delivered while still carrying the meal's carb/BG context worth
    keeping -- a pen record has no such context and its smallest real actuation
    is 0.5 U.
    """
    dose = _finite_or_none(value)
    if dose is None:
        return None
    if 0 < dose <= max_units or (allow_zero and dose == 0):
        return dose
    return None


def map_cgm_points(points: list[dict]) -> list[MappedGlucose]:
    """Map merged graph/data CGM points (``cgmHigh``∪``cgmNormal``∪``cgmLow``).

    Each point: ``{y: mg/dL, value: mg/dL*100, timestamp: UTC-ISO, calculated: bool}``.
    Glucose has no trend in graph/data -> the row gets ``NOT_COMPUTABLE`` at storage.

    Glucose values here are in mg/dL.
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
        rate = _finite_or_none(r.get("rate"))
        if ts is None or rate is None or rate < 0 or rate > _MAX_BASAL_RATE_UH:
            continue
        duration = _finite_or_none(r.get("duration"))
        out.append(
            MappedPumpEvent(
                event_type=PumpEventType.BASAL,
                timestamp=ts,
                ns_id=_str_or_none(r.get("guid")),
                units=rate,
                duration_minutes=int(duration // 60)
                if duration is not None and duration >= 0
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
        # allow_zero: a suggested bolus fully reduced by IoB records 0 delivered
        # while still carrying the meal's carb/BG context (see _dose_or_none).
        dose = _dose_or_none(r.get("insulinDelivered"), allow_zero=True)
        if ts is None or dose is None:
            continue
        bg = _finite_or_none(r.get("bloodGlucoseInput"))
        carbs = _finite_or_none(r.get("carbsInput"))
        iob = _finite_or_none(r.get("insulinOnBoard"))
        out.append(
            MappedPumpEvent(
                event_type=PumpEventType.BOLUS,
                timestamp=ts,
                ns_id=_str_or_none(r.get("guid")),
                units=dose,
                # Omnipod 5 SmartAdjust auto-bolus shows as type "automatic".
                is_automated=str(r.get("type", "")).lower() == "automatic",
                iob_at_event=iob,
                cob_at_event=carbs if carbs is not None and carbs > 0 else None,
                bg_at_event=int(bg) if bg is not None and bg > 0 else None,
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
    """Map ``insulins`` (smart-pen doses + manual logs) -> BOLUS / BASAL_INJECTION.

    Live finding (NovoPen 6 / Echo Plus capture): the record ``timestamp`` is
    genuine UTC -- verified against known dose times on a CEST wall clock --
    unlike the pump streams' local-with-fake-``Z`` footgun, so the strict UTC
    parser applies and there is no offset field to consult.

    Skipped (refuse rather than mis-model a medical record):

    * soft-deleted -- same reasoning as every other stream
    * priming shots (``suspectedPrime`` / ``acceptedPrime``) -- pen actuations
      that never enter the body; ingesting them inflates dose totals and IoB
    * ``incomplete`` -- Glooko marks the dose value unconfirmed
    * an unrecognized ``insulinType`` -- ``bolus`` maps to BOLUS and ``basal``
      (long-acting, e.g. Lantus/Tresiba) to BASAL_INJECTION (the injected
      amount, NOT a U/h rate); any third value is skipped rather than guessed
    * a ``units`` field that is present but not ``"units"`` -- an unknown unit
      of measure would be mis-ingested as insulin units
    * non-positive or implausibly large doses (``_dose_or_none``; the 60 U
      single-actuation bound also applies to manual logs -- see the
      ``_MAX_BOLUS_DOSE_U`` rationale)

    Dose value: ``currentValue`` is preferred whenever PRESENT (falling back to
    ``value`` only when it is absent). The capture only ever showed them equal,
    but Glooko carries override fields (``overrideValue`` / ``overriddenAt``)
    suggesting an edit lands in ``currentValue`` while ``value`` keeps the
    original -- preferring the current reading is correct in both worlds, and a
    present-but-implausible ``currentValue`` refuses the record outright.
    """
    out: list[MappedPumpEvent] = []
    for r in records:
        if not isinstance(r, dict) or _is_soft_deleted(r):
            continue
        if r.get("suspectedPrime") or r.get("acceptedPrime"):
            continue
        if r.get("incomplete"):
            continue
        insulin_type = str(r.get("insulinType", "")).lower()
        if insulin_type == "bolus":
            event_type = PumpEventType.BOLUS
            max_units = _MAX_BOLUS_DOSE_U
        elif insulin_type == "basal":
            event_type = PumpEventType.BASAL_INJECTION
            max_units = _MAX_BASAL_INJECTION_U
        else:
            continue  # unrecognized insulinType -> skip, don't guess
        unit_of_measure = r.get("units")
        if unit_of_measure is not None and str(unit_of_measure).lower() != "units":
            continue
        ts = _parse_utc(r.get("timestamp"))
        # currentValue when present, else value (see docstring).
        current = r.get("currentValue")
        dose = _dose_or_none(
            current if current is not None else r.get("value"), max_units=max_units
        )
        if ts is None or dose is None:
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
                event_type=event_type,
                timestamp=ts,
                ns_id=_str_or_none(r.get("guid")),
                units=dose,
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
