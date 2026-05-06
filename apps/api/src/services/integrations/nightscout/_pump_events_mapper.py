"""Map Nightscout treatments to PumpEvent rows.

Routes by the input model's `semantic_kind` (which already decided
how to interpret the record's field-presence). The mapper produces
zero, one, or two PumpEvent insert dicts:

- Zero: dropped (unknown eventType, soft-delete, cancel-temp signal,
  fingerstick BG Check (handled by glucose mapper), unrecognized
  device events).
- One: most common -- a single event row.
- Two: meal-bolus pair (carbs + insulin in one record split into a
  bolus row + a carb_entry row, linked by `meal_event_id`).

Type-specific extras that don't fit the typed columns land in
`metadata_json`. Source attribution lives in `source` (top-level
"nightscout:<connection_id>") plus inside `metadata_json` for the
sub-attribution (uploader, raw device string, raw enteredBy string).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from src.models.pump_data import PumpEventType
from src.services.integrations.nightscout.models import NightscoutTreatment


def _build_metadata(
    treatment: NightscoutTreatment,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the metadata_json blob carrying source sub-attribution.

    Always includes:
    - source_uploader (detected from device + entered_by)
    - source_device + source_entered_by (raw strings, preserved)
    - source_relayed (true if the entered_by ends in @ns / @ns loader)
    - notes (free-text, redacted at the model layer via repr=False but
      preserved as data here)

    Per-event-type extras get merged in via the `extra` dict.
    """
    eb = treatment.entered_by or ""
    relayed = eb.endswith("@ns") or eb.endswith("@ns loader")
    base: dict[str, Any] = {
        "source_uploader": treatment.uploader,
        "source_device": treatment.device,
        "source_entered_by": treatment.entered_by,
        "source_relayed": relayed,
    }
    if treatment.notes:
        base["notes"] = treatment.notes
    if extra:
        base.update(extra)
    return base


def _base_event(
    treatment: NightscoutTreatment,
    *,
    user_id: str,
    source: str,
    event_type: PumpEventType,
    received_at: datetime | None,
) -> dict[str, Any] | None:
    """Build the common columns shared by every PumpEvent insert.

    Returns None if the treatment lacks a resolvable timestamp -- a
    record without a timestamp can't be ordered or rendered, so
    dropping it is preferable to inventing one.
    """
    ts = treatment.canonical_timestamp
    if ts is None:
        return None
    return {
        "user_id": user_id,
        "event_type": event_type,
        "event_timestamp": ts,
        "received_at": received_at or datetime.now(UTC),
        "source": source,
        "ns_id": treatment.id,
    }


def _map_bolus(treatment: NightscoutTreatment, base: dict[str, Any]) -> dict[str, Any]:
    """Bolus / SMB / Square / External Insulin -- all land as BOLUS."""
    extras: dict[str, Any] = {}
    if treatment.is_smb:
        extras["bolus_subtype"] = "smb"
    elif treatment.is_external_insulin:
        extras["bolus_subtype"] = "external"
    elif treatment.bolus_type and treatment.bolus_type.lower().strip() == "square":
        # Loop classifies any bolus with delivery duration >= 30 min
        # as Square; not a true split bolus, just a long-duration
        # regular bolus.
        extras["bolus_subtype"] = "square"
    else:
        extras["bolus_subtype"] = "normal"

    if treatment.programmed is not None:
        extras["programmed_units"] = treatment.programmed
    if treatment.insulin_type:
        extras["insulin_type"] = treatment.insulin_type
    # AAPS pump composite dedup triple
    if treatment.pump_id is not None:
        extras["pump_id"] = treatment.pump_id
    if treatment.pump_type:
        extras["pump_type"] = treatment.pump_type
    if treatment.pump_serial:
        extras["pump_serial"] = treatment.pump_serial
    # Loop syncIdentifier (separate from server-assigned _id; useful
    # for round-tripping back to Loop's HealthKit cache).
    if treatment.sync_identifier:
        extras["sync_identifier"] = treatment.sync_identifier
    # AAPS Bolus Wizard inputs (carbs, BG, target, ISF, CR, IOB) --
    # preserved verbatim for AI analysis context.
    if treatment.bolus_calculator_result:
        extras["bolus_calculator_result"] = treatment.bolus_calculator_result

    # An SMB is by definition an automated micro-bolus, even when the
    # uploader didn't set `automatic=true` (older AAPS versions, Trio's
    # bare `eventType: "SMB"` shape). Conflating with `is_automated`
    # keeps dashboard "automated bolus" filters honest.
    base.update(
        {
            "units": treatment.insulin,
            "is_automated": treatment.automatic is True or treatment.is_smb,
            "metadata_json": _build_metadata(treatment, extra=extras),
        }
    )
    return base


def _map_carb_entry(
    treatment: NightscoutTreatment, base: dict[str, Any]
) -> dict[str, Any]:
    extras: dict[str, Any] = {"carbs_grams": treatment.carbs}
    # AAPS extended-meal nutrition (high-fat / high-protein meals)
    if treatment.protein is not None:
        extras["protein_grams"] = treatment.protein
    if treatment.fat is not None:
        extras["fat_grams"] = treatment.fat
    if treatment.duration is not None:
        # Loop emits absorptionTime for carbs (in seconds); other
        # uploaders emit duration (minutes). The input-model layer
        # doesn't normalize the unit; we record what's there and leave
        # Loop-vs-other-uploader unit handling to the wizard / AI.
        extras["duration_field_value"] = treatment.duration
    if treatment.uploader == "loop":
        extras["loop_carbs_uses_seconds"] = True

    base.update(
        {
            "units": None,  # carb-only, no insulin
            "duration_minutes": round(treatment.duration)
            if treatment.duration is not None and treatment.uploader != "loop"
            else None,
            "metadata_json": _build_metadata(treatment, extra=extras),
        }
    )
    return base


def _map_temp_basal(
    treatment: NightscoutTreatment, base: dict[str, Any]
) -> dict[str, Any]:
    """Temp Basal -- absolute or percent-mode."""
    extras: dict[str, Any] = {}
    if treatment.rate is not None:
        extras["rate_u_per_hr"] = treatment.rate
    if treatment.absolute is not None:
        extras["absolute_u_per_hr"] = treatment.absolute
    if treatment.percent is not None:
        # NS percent encoding: delta from 100 (e.g. -50 = 50% basal)
        extras["percent_delta"] = treatment.percent
    if treatment.reason:
        # Loop sets reason="suspend" for pump suspends; preserve it
        # for downstream classification.
        extras["reason"] = treatment.reason
    # AAPS Type subtype if present: NORMAL / EMULATED_PUMP_SUSPEND /
    # PUMP_SUSPEND / SUPERBOLUS / FAKE_EXTENDED.
    if treatment.type:
        extras["aaps_type"] = treatment.type

    base.update(
        {
            "units": None,
            "duration_minutes": round(treatment.duration)
            if treatment.duration is not None
            else None,
            "metadata_json": _build_metadata(treatment, extra=extras),
        }
    )
    return base


def _map_temp_basal_suspend(
    treatment: NightscoutTreatment, base: dict[str, Any]
) -> dict[str, Any]:
    """Pump suspend signaled via a zero-rate Temp Basal (with duration)."""
    base = _map_temp_basal(treatment, base)
    # Override the event_type set by base_event (which was TEMP_BASAL)
    # to the dedicated SUSPEND value.
    base["event_type"] = PumpEventType.SUSPEND
    return base


def _map_combo_bolus(
    treatment: NightscoutTreatment, base: dict[str, Any]
) -> dict[str, Any]:
    """Combo Bolus or AAPS extended-emulating-TBR shape."""
    extras: dict[str, Any] = {}
    if treatment.split_now is not None:
        extras["split_now_pct"] = treatment.split_now
    if treatment.split_ext is not None:
        extras["split_ext_pct"] = treatment.split_ext
    if treatment.combo_split_valid is False and (
        treatment.split_now is not None or treatment.split_ext is not None
    ):
        # Lock against malformed real-world splits -- record the
        # constraint violation so the AI / analytics layer can flag it
        # rather than silently miscompute.
        extras["split_invalid"] = True
    if treatment.extended_emulated:
        # AAPS extended bolus emulating TBR: preserve the nested
        # subtree for downstream analysis.
        extras["extended_emulated"] = treatment.extended_emulated
    base.update(
        {
            "units": treatment.insulin,
            "duration_minutes": round(treatment.duration)
            if treatment.duration is not None
            else None,
            "metadata_json": _build_metadata(treatment, extra=extras),
        }
    )
    return base


def _map_override(
    treatment: NightscoutTreatment, base: dict[str, Any]
) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    if treatment.correction_range:
        extras["correction_range"] = treatment.correction_range
    if treatment.insulin_needs_scale_factor is not None:
        extras["multiplier"] = treatment.insulin_needs_scale_factor
    elif treatment.multiplier is not None:
        extras["multiplier"] = treatment.multiplier
    elif treatment.percentage is not None:
        # AAPS percentage as multiplier (e.g. 110% = 1.1)
        extras["multiplier"] = treatment.percentage / 100.0
    if treatment.remote_address:
        extras["remote_address"] = treatment.remote_address
    if treatment.duration_type:
        extras["duration_type"] = treatment.duration_type
    if treatment.is_indefinite_trio_override:
        extras["indefinite"] = True

    base.update(
        {
            "units": None,
            "duration_minutes": round(treatment.duration)
            if treatment.duration is not None
            else None,
            "metadata_json": _build_metadata(treatment, extra=extras),
        }
    )
    return base


def _map_temp_target(
    treatment: NightscoutTreatment, base: dict[str, Any]
) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    if treatment.target_top is not None:
        extras["target_top_mgdl"] = treatment.target_top
    if treatment.target_bottom is not None:
        extras["target_bottom_mgdl"] = treatment.target_bottom
    if treatment.reason:
        extras["reason"] = treatment.reason
    base.update(
        {
            "units": None,
            "duration_minutes": round(treatment.duration)
            if treatment.duration is not None
            else None,
            "metadata_json": _build_metadata(treatment, extra=extras),
        }
    )
    return base


def _map_profile_switch(
    treatment: NightscoutTreatment, base: dict[str, Any]
) -> dict[str, Any]:
    """Real Profile Switch OR AAPS Effective-Profile-Switch-as-Note."""
    extras: dict[str, Any] = {
        "profile": treatment.profile,
        "original_profile_name": treatment.original_profile_name,
        "percentage": treatment.percentage,
        "timeshift": treatment.timeshift,
        "original_duration": treatment.original_duration,
        "original_end": treatment.original_end,
    }
    if treatment.profile_json:
        extras["profile_json"] = treatment.profile_json
    if treatment.is_effective_profile_switch_note:
        extras["effective_profile_switch_via_note"] = True
    base.update(
        {
            "units": None,
            "duration_minutes": round(treatment.duration)
            if treatment.duration is not None
            else None,
            "metadata_json": _build_metadata(treatment, extra=extras),
        }
    )
    return base


def _map_device_event(
    treatment: NightscoutTreatment, base: dict[str, Any]
) -> dict[str, Any]:
    """Site / Sensor / Insulin / Battery change events."""
    extras: dict[str, Any] = {"device_event_type": treatment.event_type}
    base.update(
        {
            "units": None,
            "metadata_json": _build_metadata(treatment, extra=extras),
        }
    )
    return base


def _map_simple_note(
    treatment: NightscoutTreatment, base: dict[str, Any]
) -> dict[str, Any]:
    """Note / Announcement / OpenAPS Offline -- low-data event types."""
    extras: dict[str, Any] = {"raw_event_type": treatment.event_type}
    base.update(
        {
            "units": None,
            "duration_minutes": round(treatment.duration)
            if treatment.duration is not None
            else None,
            "metadata_json": _build_metadata(treatment, extra=extras),
        }
    )
    return base


def map_treatment_to_pump_events(
    treatment: NightscoutTreatment,
    *,
    user_id: str,
    source: str,
    received_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Translate a Nightscout treatment into 0, 1, or 2 PumpEvent inserts.

    Returns:
        - Empty list: dropped (soft-delete, cancel-temp, unknown
          eventType the translator can't classify, fingerstick that
          belongs in glucose_readings).
        - One insert: most common case.
        - Two inserts: meal-bolus pair (carbs + insulin) split into a
          BOLUS row + CARBS row, linked via shared `meal_event_id`.
    """
    kind = treatment.semantic_kind

    # --- Hard-drop cases ------------------------------------------------
    if kind in ("temp_basal_cancel", "fingerstick_bg_check", "unknown"):
        return []
    # `unknown` covers the soft-delete case (isValid=False) by design.

    # --- Type-specific routing -----------------------------------------

    # Map semantic_kind to (PumpEventType, mapper_fn). meal_bolus_pair
    # is special-cased below because it produces TWO rows.
    routing = {
        "bolus": (PumpEventType.BOLUS, _map_bolus),
        "carb_entry": (PumpEventType.CARBS, _map_carb_entry),
        "temp_basal": (PumpEventType.BASAL, _map_temp_basal),
        "temp_basal_suspend": (PumpEventType.SUSPEND, _map_temp_basal_suspend),
        "combo_bolus": (PumpEventType.COMBO_BOLUS, _map_combo_bolus),
        "override": (PumpEventType.OVERRIDE, _map_override),
        "temp_target": (PumpEventType.TEMP_TARGET, _map_temp_target),
        "profile_switch": (PumpEventType.PROFILE_SWITCH, _map_profile_switch),
        "effective_profile_switch": (
            PumpEventType.PROFILE_SWITCH,
            _map_profile_switch,
        ),
        "device_event": (PumpEventType.DEVICE_EVENT, _map_device_event),
        "aps_offline": (PumpEventType.APS_OFFLINE, _map_simple_note),
        "note": (PumpEventType.NOTE, _map_simple_note),
        "announcement": (PumpEventType.NOTE, _map_simple_note),
        "exercise_log": (PumpEventType.NOTE, _map_simple_note),
    }

    if kind == "meal_bolus_pair":
        # Split into bolus + carbs rows, linked via meal_event_id.
        # Both meal_event_id and the role suffixes on ns_id MUST be
        # deterministic functions of the source treatment id -- otherwise
        # re-fetching the same record on a later sync produces fresh
        # UUIDs, the (source, ns_id) dedupe never matches, and we
        # silently double-insert the bolus + carbs rows on every cycle.
        bolus_base = _base_event(
            treatment,
            user_id=user_id,
            source=source,
            event_type=PumpEventType.BOLUS,
            received_at=received_at,
        )
        carb_base = _base_event(
            treatment,
            user_id=user_id,
            source=source,
            event_type=PumpEventType.CARBS,
            received_at=received_at,
        )
        if bolus_base is None or carb_base is None:
            return []
        bolus_row = _map_bolus(treatment, bolus_base)
        carb_row = _map_carb_entry(treatment, carb_base)

        # Derive a deterministic UUID from the source ns_id so the
        # sibling-link is stable across re-fetches. If the upstream
        # has no ns_id at all (rare; some uploaders POST without
        # `_id`), fall back to a uuid4 -- there's nothing stable to
        # derive from, so the dedupe-via-ns_id path won't fire either
        # way for that record.
        meal_event_id = (
            uuid.uuid5(uuid.NAMESPACE_OID, treatment.id)
            if treatment.id
            else uuid.uuid4()
        )
        bolus_row["meal_event_id"] = meal_event_id
        carb_row["meal_event_id"] = meal_event_id

        # ns_id suffixes use `#` as a delimiter that real NS `_id`
        # values cannot contain (24-hex ObjectIds and UUID/hex
        # identifiers don't carry `#`). The role tag alone is enough
        # to disambiguate the two rows from a single source record;
        # we don't need meal_event_id in the suffix.
        if bolus_row.get("ns_id"):
            bolus_row["ns_id"] = f"{bolus_row['ns_id']}#role=bolus"
        if carb_row.get("ns_id"):
            carb_row["ns_id"] = f"{carb_row['ns_id']}#role=carbs"
        return [bolus_row, carb_row]

    if kind not in routing:
        # Defensive fallback for any kind we forgot to handle.
        return []

    event_type, mapper = routing[kind]
    base = _base_event(
        treatment,
        user_id=user_id,
        source=source,
        event_type=event_type,
        received_at=received_at,
    )
    if base is None:
        return []
    return [mapper(treatment, base)]
