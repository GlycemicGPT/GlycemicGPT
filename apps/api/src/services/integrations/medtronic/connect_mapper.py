"""Map a CareLink CarePartner "display/message" RecentData payload into our
normalized model (glucose + pump events) for the autonomous follower sync.

Reuses the shared Mapped* model + conventions from ``carelink_mapper`` (the
manual CSV import), so Connect follower data lands in the same
``glucose_readings`` / ``pump_events`` tables identically to every other source
(BG_READING / BOLUS / CARBS; ``source = "medtronic"``).

Clean-room attribution: the CarePartner ``display/message`` JSON shape, the
marker-type semantics, and the clock-skew time-correction algorithm were learned
from xDrip (github.com/NightscoutFoundation/xDrip, ``cgm/carelinkfollow``), which
is GPL-3.0 -- license-compatible with this GPL-3.0 project. Re-implemented
independently in Python; credit to the xDrip / CareLink-follower authors.

SCOPE (v1, conservative): CGM sensor glucose + INSULIN (bolus), MEAL (carbs),
and finger BG markers -- the AI-critical data, mapped only where the meaning is
unambiguous. Deliberately NOT mapped yet (need a real active-pump payload to
classify correctly rather than guess -- the manual-import lesson):
  - auto-correction vs manual split (marker ``bolusType``/``autoModeOn`` values
    unconfirmed) -> all INSULIN markers map to BOLUS (not CORRECTION) for now;
  - AUTO_BASAL_DELIVERY markers (xDrip ignores them too), scheduled basal rate,
    reservoir, battery, suspend/resume.
These are follow-ups gated on a live active-Medtronic-pump validator.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.models.pump_data import PumpEventType

from .carelink_mapper import SOURCE, MappedGlucose, MappedPumpEvent, MappedRecords

# Marker types (xDrip Marker.MARKER_TYPE_*).
_MARKER_INSULIN = "INSULIN"
_MARKER_MEAL = "MEAL"
_MARKER_BG_TYPES = {"BG_READING", "BG", "CALIBRATION"}

# Bound on the clock-skew shift; beyond this the diff is treated as garbage and
# not applied. xDrip uses a one-sided `diffInHour < 26`; we bound it symmetrically
# so a wildly wrong device clock (far ahead OR behind) can't silently shift an
# entire sync by days -- this path can't be validated live, so we fail safe.
_MAX_SKEW_HOURS = 26

# Physiologic sensor-glucose bounds (mg/dL). Medtronic CGM clamps to 40-400;
# we accept a slightly wider band and DROP anything outside it so a corrupt or
# unit-confused follower value can't poison TIR/alerts/AI context. (We can't
# validate this feed against a live pump, so be strict at the boundary.)
_SG_MIN_MGDL = 10
_SG_MAX_MGDL = 600

# Sanity bound on the scheduled basal RATE (U/h). A real basal rate is a few
# U/h; reject an implausible value rather than store a U/h rate the rate-based
# TDD calc would multiply out into a catastrophic daily total.
_MAX_BASAL_RATE_UH = 35.0


def _parse_dt(value: Any) -> datetime | None:
    """Parse a CarePartner zoned ISO datetime string to an aware datetime.

    CarePartner datetimes carry a timezone offset; a naive value is refused
    (returning it would risk misdating, and storage requires tz-aware times)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None


def _skew_hours(recent: dict) -> int:
    """Device-vs-server clock skew in whole hours (xDrip's diffInHour).

    ``lastConduitUpdateServerDateTime`` (server) and ``lastConduitDateTime``
    (device) are *intended* to be epoch-millisecond numbers; the data's
    wall-clock times are shifted by this to correct a wrong pump clock.

    Real-world note: on at least one account we observed
    ``lastConduitDateTime`` returned as a NAIVE ISO string (no offset), not as
    an epoch-ms number. In that case we **intentionally** return 0 (no shift):
    the sg/marker datetimes themselves are already timezone-aware (carry an
    offset), so they're correctly placed in UTC without any shift, and
    fabricating a shift from a naive string risks misdating them by hours.
    """
    server = recent.get("lastConduitUpdateServerDateTime")
    conduit = recent.get("lastConduitDateTime")
    if not isinstance(server, (int, float)) or not isinstance(conduit, (int, float)):
        return 0
    if server <= 1 or conduit <= 1:
        return 0
    diff = round((server - conduit) / 3_600_000)
    return diff if diff != 0 and -_MAX_SKEW_HOURS < diff < _MAX_SKEW_HOURS else 0


def _shift(dt: datetime | None, hours: int) -> datetime | None:
    if dt is None or hours == 0:
        return dt
    return dt + timedelta(hours=hours)


def _marker_dt(m: dict) -> datetime | None:
    # xDrip getDate(): displayTime || timestamp || dateTime.
    return _parse_dt(m.get("displayTime")) or _parse_dt(m.get("dateTime"))


def _data_values(m: dict) -> dict:
    return (m.get("data") or {}).get("dataValues") or {}


def _to_float(value: Any) -> float | None:
    """Coerce an external (untrusted) value to float, or None if non-numeric.

    CarePartner is third-party data; a field could be a non-numeric string
    (e.g. "N/A"), so every conversion must fail soft rather than raise."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _insulin_amount(m: dict) -> float | None:
    """xDrip getInsulinAmount(): delivered fast + extended bolus units.

    A normal bolus carries only ``deliveredFastAmount``; an extended/dual-wave
    bolus also carries ``deliveredExtendedAmount``. Either component may be
    present alone, so sum whichever are present (a missing component counts as
    0). Only when BOTH top-level amounts are absent do we fall back to the
    nested ``dataValues`` (older payload shape). Requiring both to be present
    before using the top-level fields would silently drop ordinary
    fast-only boluses."""
    de = _to_float(m.get("deliveredExtendedAmount"))
    df = _to_float(m.get("deliveredFastAmount"))
    if de is not None or df is not None:
        return (de or 0.0) + (df or 0.0)
    dv = _data_values(m)
    if dv.get("deliveredFastAmount") is not None:
        return _to_float(dv["deliveredFastAmount"])
    if dv.get("insulinUnits") is not None:
        return _to_float(dv["insulinUnits"])
    return None


def _carb_amount(m: dict) -> float | None:
    """xDrip getCarbAmount()."""
    if m.get("amount") is not None:
        return _to_float(m["amount"])
    dv = _data_values(m)
    return _to_float(dv["amount"]) if dv.get("amount") is not None else None


def _bg_value(m: dict) -> int | None:
    """xDrip getBloodGlucose()."""
    v = m.get("value")
    if v is None:
        v = _data_values(m).get("unitValue")
    if v is None:
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def map_recent_data(recent: dict) -> MappedRecords:
    """Map a ``RecentData`` (display/message ``patientData``) dict to records."""
    records = MappedRecords()
    if not isinstance(recent, dict):
        return records
    skew = _skew_hours(recent)

    # Continuous sensor glucose.
    for sg in recent.get("sgs") or []:
        if not isinstance(sg, dict):
            continue
        value = sg.get("sg")
        dt = _shift(_parse_dt(sg.get("datetime")), skew)
        # Drop physiologically implausible readings rather than feed them to
        # TIR/alerts/AI -- a corrupt/unit-confused follower value is worse than
        # a gap, and this feed can't be validated live.
        if (
            dt is not None
            and isinstance(value, (int, float))
            and _SG_MIN_MGDL <= value <= _SG_MAX_MGDL
        ):
            records.glucose.append(
                MappedGlucose(timestamp=dt, value_mgdl=int(value), source=SOURCE)
            )

    # Markers (boluses, meals, finger BGs).
    for m in recent.get("markers") or []:
        if not isinstance(m, dict):
            continue
        mtype = (m.get("type") or "").upper()
        dt = _shift(_marker_dt(m), skew)
        if dt is None:
            continue
        if mtype in _MARKER_BG_TYPES:
            bg = _bg_value(m)
            # Apply the same physiologic clamp as sensor glucose -- a finger BG
            # is a glucose value too, and a corrupt/unit-confused one would
            # poison TIR/alerts/AI context just the same.
            if bg and _SG_MIN_MGDL <= bg <= _SG_MAX_MGDL:
                records.pump_events.append(
                    MappedPumpEvent(PumpEventType.BG_READING, dt, bg_at_event=bg)
                )
        elif mtype == _MARKER_INSULIN:
            units = _insulin_amount(m)
            if units and units > 0:
                # NOTE: all INSULIN -> BOLUS for now; the automated-correction
                # split needs a real active-pump payload to classify reliably.
                records.pump_events.append(
                    MappedPumpEvent(PumpEventType.BOLUS, dt, units=float(units))
                )
        elif mtype == _MARKER_MEAL:
            carbs = _carb_amount(m)
            if carbs and carbs > 0:
                records.pump_events.append(
                    MappedPumpEvent(PumpEventType.CARBS, dt, cob_at_event=float(carbs))
                )

    # Current scheduled basal RATE (U/h) as a single point at the snapshot time.
    # This is the validatable-shaped basal signal; the SmartGuard auto-basal
    # micro-bolus component (AUTO_BASAL_DELIVERY markers) is deliberately NOT
    # mapped -- its amount semantics can't be confirmed without a live pump, and
    # mis-mapping it would corrupt insulin totals (the manual-import lesson). So
    # Medtronic Connect basal is scheduled-rate-only for now (a known gap).
    basal = recent.get("basal")
    snapshot = _snapshot_dt(recent)
    if isinstance(basal, dict) and snapshot is not None:
        rate = basal.get("basalRate")
        if isinstance(rate, (int, float)) and 0 <= rate <= _MAX_BASAL_RATE_UH:
            records.pump_events.append(
                MappedPumpEvent(PumpEventType.BASAL, snapshot, units=float(rate))
            )

    return records


def _snapshot_dt(recent: dict) -> datetime | None:
    """The server 'as-of' instant for this snapshot (tz-aware), from the
    conduit-update epoch. Used to timestamp the current basal-rate point."""
    server = recent.get("lastConduitUpdateServerDateTime")
    if not isinstance(server, (int, float)) or server <= 1:
        return None
    try:
        return datetime.fromtimestamp(server / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
