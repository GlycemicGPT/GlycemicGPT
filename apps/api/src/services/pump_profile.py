"""Pump profile service."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.pump_profile import PumpProfile
from src.schemas.nightscout import OnboardingDerivation, OnboardingScheduleSegment

# Stable name for profiles imported from a Nightscout connection.
# Distinct from the "Tandem" name used by `tandem_sync.py` so the two
# integrations cannot collide on `uq_pump_profile_user_name` and so a
# user with both connections sees both rows in their profile history.
# The active-profile reader (`get_active_profile`) tie-breaks across
# names by `synced_at desc`, so the most recently synced source wins.
NIGHTSCOUT_PROFILE_NAME = "Nightscout"


async def get_active_profile(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> PumpProfile | None:
    """Get the user's most recently synced active pump profile."""
    result = await db.execute(
        select(PumpProfile)
        .where(PumpProfile.user_id == user_id, PumpProfile.is_active.is_(True))
        .order_by(PumpProfile.synced_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _format_time_label(start_minutes: int) -> str:
    """Render `start_minutes` as a 12-hour clock label, e.g. "6:30 AM"."""
    hours = start_minutes // 60
    minutes = start_minutes % 60
    period = "AM" if hours < 12 else "PM"
    display_hour = hours % 12 or 12
    return f"{display_hour}:{minutes:02d} {period}"


def _segments_by_start(
    segments: list[OnboardingScheduleSegment] | None,
) -> dict[int, float]:
    """Index a derivation's segment list by `start_minutes`.

    Returns an empty map when no segments were proposed (None or
    empty list) so callers can treat "missing schedule" and "no
    schedule segments" identically.
    """
    if not segments:
        return {}
    return {seg.start_minutes: seg.value for seg in segments}


def _merge_segments(
    *,
    basal_by_start: dict[int, float],
    carb_ratio_by_start: dict[int, float],
    isf_by_start: dict[int, float],
) -> list[dict]:
    """Merge per-domain schedule maps into the canonical segment list.

    The pump_profiles JSONB shape co-locates basal_rate /
    correction_factor / carb_ratio / target_bg per time slot, but
    Nightscout exposes them as independent schedules with
    independent breakpoints. We take the UNION of breakpoints
    across whichever schedules the caller opted to import; any
    domain without a value at a given breakpoint is left at 0.0.

    Zero is a sentinel for "this domain wasn't imported at this
    slot" rather than a real basal/ICR/ISF/target_bg value (those
    are all `gt=0` in the derivation schema). Downstream readers
    must not treat 0.0 as a valid pump setting -- the active
    profile is a UI/AI surface, not a delivery target on this
    monitoring-only project. This matches the convention already
    used by the Tandem writer in `tandem_sync.py`.

    `correction_factor` (ISF) is stored as a float to preserve
    fractional values from Nightscout (e.g. mmol-converted ISFs
    that round to non-integer mg/dL/U). Mobile readers must accept
    either int or float -- the JSONB column is untyped per-field
    by design.
    """
    breakpoints = sorted(
        set(basal_by_start) | set(carb_ratio_by_start) | set(isf_by_start)
    )
    out: list[dict] = []
    for start in breakpoints:
        out.append(
            {
                "time": _format_time_label(start),
                "start_minutes": start,
                "basal_rate": float(basal_by_start.get(start, 0.0)),
                "correction_factor": float(isf_by_start.get(start, 0.0)),
                "carb_ratio": float(carb_ratio_by_start.get(start, 0.0)),
                "target_bg": 0,
            }
        )
    return out


async def upsert_from_onboarding(
    user_id: uuid.UUID,
    derivation: OnboardingDerivation,
    *,
    apply_basal: bool,
    apply_carb_ratio: bool,
    apply_isf: bool,
    apply_dia: bool,
    db: AsyncSession,
) -> PumpProfile | None:
    """Persist a Nightscout-imported pump profile for the user.

    Returns the upserted row, or None when nothing was actually
    applied (all flags false, or all opted-in schedules empty AND
    DIA not opted in / unavailable). The connection's confirmed
    DIA writes to `insulin_configs` separately by the caller; the
    DIA value here is mirrored onto `insulin_duration_min` only so
    the active-profile reader surfaces a coherent value to mobile
    clients alongside the schedule segments.

    Idempotent: re-running with the same derivation yields the
    same row state. UPSERTs by `(user_id, profile_name)` so a user
    re-running the wizard refreshes their existing Nightscout
    profile in place rather than accumulating duplicates.

    `is_active=True` on every write: the cross-source tie-break
    is `synced_at desc` (see `get_active_profile`), so a fresh
    Tandem sync after a Nightscout import will retake priority
    naturally without needing to flip flags here.
    """
    basal_map = (
        _segments_by_start(derivation.basal_schedule.proposed_segments)
        if apply_basal
        else {}
    )
    carb_map = (
        _segments_by_start(derivation.carb_ratio_schedule.proposed_segments)
        if apply_carb_ratio
        else {}
    )
    isf_map = (
        _segments_by_start(derivation.isf_schedule.proposed_segments)
        if apply_isf
        else {}
    )

    dia_value = derivation.dia_hours.proposed_value if apply_dia else None
    dia_minutes: int | None = (
        int(round(dia_value * 60)) if dia_value is not None and dia_value > 0 else None
    )

    if not basal_map and not carb_map and not isf_map and dia_minutes is None:
        return None

    segments = _merge_segments(
        basal_by_start=basal_map,
        carb_ratio_by_start=carb_map,
        isf_by_start=isf_map,
    )

    now = datetime.now(UTC)

    stmt = (
        insert(PumpProfile)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            profile_name=NIGHTSCOUT_PROFILE_NAME,
            is_active=True,
            segments=segments,
            insulin_duration_min=dia_minutes,
            carb_entry_enabled=True,
            max_bolus_units=None,
            cgm_high_alert_mgdl=None,
            cgm_low_alert_mgdl=None,
            synced_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_pump_profile_user_name",
            set_={
                "is_active": True,
                "segments": segments,
                "insulin_duration_min": dia_minutes,
                "carb_entry_enabled": True,
                "synced_at": now,
            },
        )
    )
    await db.execute(stmt)
    await db.flush()

    result = await db.execute(
        select(PumpProfile).where(
            PumpProfile.user_id == user_id,
            PumpProfile.profile_name == NIGHTSCOUT_PROFILE_NAME,
        )
    )
    return result.scalar_one()
