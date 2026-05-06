"""Map Nightscout devicestatus records to DeviceStatusSnapshot rows.

Each devicestatus record produces at most one snapshot row. Subtree
JSON blobs (`loop`, `openaps`, `pump`, `uploader`) are preserved
verbatim -- never modified, never parsed further at this layer. The
`reason` free-text strings inside `suggested`/`enacted` carry the
loop's dosing-decision rationale that AI consumes; the translator
keeps them intact.

Per-connection dedupe via `ns_id` (server-assigned `_id`). If the
record has no ns_id (rare; some uploaders POST without one), we skip
rather than invent a key -- snapshots are high-volume, so dropping
one is preferable to creating a duplicate row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.services.integrations.nightscout.models import NightscoutDeviceStatus


def map_devicestatus_to_snapshot(
    ds: NightscoutDeviceStatus,
    *,
    user_id: str,
    nightscout_connection_id: str,
    received_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Map a Nightscout devicestatus to a DeviceStatusSnapshot insert dict.

    Returns None when:
    - `_id` is missing (no per-connection dedupe key)
    - `created_at` parses to None
    """
    if not ds.id:
        return None
    timestamp = _parse_created_at(ds.created_at)
    if timestamp is None:
        return None

    pump_subtree = ds.pump if isinstance(ds.pump, dict) else None
    pump_suspended = None
    if pump_subtree:
        # Loop: pump.suspended is a top-level boolean
        if isinstance(pump_subtree.get("suspended"), bool):
            pump_suspended = pump_subtree["suspended"]
        # AAPS / oref0: pump.status.suspended
        else:
            status = pump_subtree.get("status")
            if isinstance(status, dict) and isinstance(status.get("suspended"), bool):
                pump_suspended = status["suspended"]

    return {
        "user_id": user_id,
        "nightscout_connection_id": nightscout_connection_id,
        "snapshot_timestamp": timestamp,
        "received_at": received_at or datetime.now(UTC),
        "source_uploader": ds.uploader_name,
        "source_device": ds.device,
        "ns_id": ds.id,
        "iob_units": ds.iob_value,
        "cob_grams": _extract_cob(ds),
        "pump_battery_percent": ds.pump_battery_percent,
        "pump_reservoir_units": ds.pump_reservoir,
        "pump_suspended": pump_suspended,
        "loop_failure_reason": ds.loop_failure_reason,
        "loop_subtree_json": ds.loop if isinstance(ds.loop, dict) else None,
        "openaps_subtree_json": ds.openaps if isinstance(ds.openaps, dict) else None,
        "pump_subtree_json": pump_subtree,
        "uploader_subtree_json": ds.uploader if isinstance(ds.uploader, dict) else None,
    }


def _parse_created_at(value: str | None) -> datetime | None:
    if not value:
        return None
    s = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _extract_cob(ds: NightscoutDeviceStatus) -> float | None:
    """Pull COB out of whichever subtree carries it.

    Loop: `loop.cob.cob`
    AAPS / oref0: `openaps.suggested.COB` or `openaps.iob.cob`
    """
    if ds.loop and isinstance(ds.loop.get("cob"), dict):
        v = ds.loop["cob"].get("cob")
        if isinstance(v, int | float) and not isinstance(v, bool):
            return float(v)
    if ds.openaps:
        suggested = ds.openaps.get("suggested")
        if isinstance(suggested, dict):
            v = suggested.get("COB")
            if isinstance(v, int | float) and not isinstance(v, bool):
                return float(v)
        iob_subtree = ds.openaps.get("iob")
        if isinstance(iob_subtree, dict):
            v = iob_subtree.get("cob")
            if isinstance(v, int | float) and not isinstance(v, bool):
                return float(v)
    return None
