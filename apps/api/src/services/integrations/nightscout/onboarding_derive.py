"""Story 43.7b -- pure-function derivation: NS profile -> wizard proposals.

Given a `NightscoutProfileSnapshot` row and the user's current
canonical settings, produce a typed `OnboardingDerivation` describing
what the smart-onboarding wizard should propose for each setting.

This module is intentionally pure: no DB writes, no I/O, no network.
The orchestrator (43.7c apply endpoint) reads the snapshot + current
settings, calls this module, then writes confirmed proposals to the
canonical tables. Keeping the derive logic side-effect-free keeps
table-driven tests simple and lets future code (mobile, brief
generation, audit logs) reuse the same logic without spinning up an
ORM session.

Entry point: `derive_onboarding_proposals(snapshot, *, current_*)`.

**AC4 default_checked semantics:** the wizard's initial checkbox
state per row is True iff the user's CURRENT canonical value matches
the platform default -- i.e. they have not customized this setting.
That gates the "auto-import" UX: a fresh-signup user gets every
checkbox auto-checked (one click finalizes); a long-time user with
custom basal patterns gets ALL checkboxes UNCHECKED so the wizard
can't silently overwrite their dialed-in config.

**AC11 / sparse-profile handling:** when the snapshot is None or
has no parseable schedules, the per-field derivations carry
`proposed_value=None` / `proposed_segments=None`. `has_profile`
is False. The wizard's settings-import step renders a "no profile
data -- we'll just sync data" banner and hides the diff table.

**Unit conversion:** Nightscout profiles can be in `mg/dl` OR
`mmol`. Our canonical settings are mg/dL across the board. When NS
is mmol, glucose-domain values (target_low, target_high, ISF) are
multiplied by `MMOL_TO_MGDL` and rounded to one decimal. Basal
rates (U/hr) and carb ratios (g/U) are unit-agnostic. DIA (hours)
is unit-agnostic. The derivation surfaces `units_converted=True`
so the wizard can show "values converted from mmol to mg/dL" copy.
"""

from __future__ import annotations

from collections.abc import Callable

from src.core.units import MGDL_PER_MMOL
from src.models.insulin_config import InsulinConfig
from src.models.nightscout_profile_snapshot import NightscoutProfileSnapshot
from src.models.pump_profile import PumpProfile
from src.models.target_glucose_range import TargetGlucoseRange
from src.schemas.nightscout import (
    OnboardingDerivation,
    OnboardingNumericFieldDerivation,
    OnboardingScheduleFieldDerivation,
    OnboardingScheduleSegment,
)

# Backwards-compatible alias for Nightscout onboarding tests and call sites.
MMOL_TO_MGDL: float = MGDL_PER_MMOL

# Allowed glucose unit strings on a Nightscout profile. Anything OUTSIDE
# this set is flagged on the derivation as `units_unknown=True` -- the
# wizard MUST surface that to the user, since silently treating a
# weird unit as mg/dL would write wrong glucose targets / ISFs to the
# canonical settings. See `_classify_units` below for the logic.
_KNOWN_MGDL_UNITS = frozenset({"mg/dl", "mgdl", "mg-dl"})
_KNOWN_MMOL_UNITS = frozenset({"mmol", "mmol/l", "mmol/litre", "mmoll"})

# Platform defaults (must mirror the SQLAlchemy column defaults on the
# canonical models). If a user's stored value matches the default, the
# wizard treats them as "not customized" and pre-checks the import row
# (AC4). Drift between this constant and the model default would silently
# break the AC; the test suite asserts the coupling.
DEFAULT_TARGET_LOW_MGDL: float = 70.0
DEFAULT_TARGET_HIGH_MGDL: float = 180.0
DEFAULT_DIA_HOURS: float = 4.0


def derive_onboarding_proposals(
    snapshot: NightscoutProfileSnapshot | None,
    *,
    current_target_range: TargetGlucoseRange | None,
    current_insulin_config: InsulinConfig | None,
    current_pump_profile: PumpProfile | None,
) -> OnboardingDerivation:
    """Map a Nightscout profile snapshot to wizard step-3 proposals.

    Pure function -- no DB writes, no I/O. The caller fetches the
    current canonical settings (one-row-per-user shape for target
    range and insulin config; the active row for pump profile) and
    threads them through.

    The derivation always carries every derivable field, so the
    wizard's row layout is deterministic. Fields where NS has
    nothing to propose carry `proposed_value=None` /
    `proposed_segments=None`; the wizard hides those rows.
    """
    if snapshot is None:
        return _empty_derivation(
            current_target_range=current_target_range,
            current_insulin_config=current_insulin_config,
            current_pump_profile=current_pump_profile,
        )

    # Strict unit classification (CR fix H1): explicitly distinguish
    # mg/dL, mmol/L, and unknown. An unrecognized unit string flips
    # `units_unknown=True` on the derivation; the wizard MUST refuse
    # to auto-import glucose-domain values until the user confirms.
    is_mmol, is_mgdl = _classify_units(snapshot.source_units)
    units_unknown = not is_mmol and not is_mgdl

    # ---- target_low / target_high (single-value fields) -----------------
    target_low = _derive_target_field(
        field="target_low",
        snapshot_segments=snapshot.target_low_segments,
        current_value=(
            current_target_range.low_target if current_target_range else None
        ),
        platform_default=DEFAULT_TARGET_LOW_MGDL,
        is_mmol=is_mmol,
        aggregator=min,
    )
    target_high = _derive_target_field(
        field="target_high",
        snapshot_segments=snapshot.target_high_segments,
        current_value=(
            current_target_range.high_target if current_target_range else None
        ),
        platform_default=DEFAULT_TARGET_HIGH_MGDL,
        is_mmol=is_mmol,
        aggregator=max,
    )

    # ---- dia_hours (single value) --------------------------------------
    # Sanitize before model construction: the schema's `gt=0` guard on
    # current_value/proposed_value would RAISE ValidationError on a
    # zero / negative input rather than fail-safing -- which would 500
    # the whole evaluate path on a single malformed NS profile. Coerce
    # non-positive values to None so the wizard sees "no proposal" and
    # the user retains their existing setting.
    proposed_dia = _coerce_positive(snapshot.source_dia_hours)
    current_dia = _coerce_positive(
        current_insulin_config.dia_hours if current_insulin_config else None
    )
    dia_hours = OnboardingNumericFieldDerivation(
        field="dia_hours",
        current_value=current_dia,
        proposed_value=proposed_dia,
        # Pre-check iff the user is at platform default OR the
        # proposal happens to match what they already have (the
        # latter is a no-op if applied -- safe to import; CR M1).
        default_checked=proposed_dia is not None
        and (
            _is_default(current_dia, DEFAULT_DIA_HOURS)
            or _values_match(current_dia, proposed_dia)
        ),
    )

    # ---- schedules ------------------------------------------------------
    # `current_pump_profile` carries a list of merged segments
    # (basal_rate / carb_ratio / correction_factor / target_bg per
    # time slot). We split it back out per-axis so the wizard can
    # show "Currently 1.0 U/hr basal" alongside "From NS 0.65 U/hr".
    # No pump_profile row at all = treat the schedule as default
    # (checked-by-default) since the user has no custom config.
    has_custom_pump_profile = current_pump_profile is not None and bool(
        current_pump_profile.segments
    )
    current_basal = _extract_axis_from_pump_profile(current_pump_profile, "basal_rate")
    current_isf = _extract_axis_from_pump_profile(
        current_pump_profile, "correction_factor"
    )
    current_icr = _extract_axis_from_pump_profile(current_pump_profile, "carb_ratio")

    basal_schedule = OnboardingScheduleFieldDerivation(
        field="basal_schedule",
        current_segments=current_basal,
        proposed_segments=_segments_to_canonical(snapshot.basal_segments),
        default_checked=(
            not has_custom_pump_profile
            and snapshot.basal_segments is not None
            and len(snapshot.basal_segments) > 0
        ),
    )
    carb_ratio_schedule = OnboardingScheduleFieldDerivation(
        field="carb_ratio_schedule",
        current_segments=current_icr,
        proposed_segments=_segments_to_canonical(snapshot.carb_ratio_segments),
        default_checked=(
            not has_custom_pump_profile
            and snapshot.carb_ratio_segments is not None
            and len(snapshot.carb_ratio_segments) > 0
        ),
    )
    isf_schedule = OnboardingScheduleFieldDerivation(
        field="isf_schedule",
        current_segments=current_isf,
        proposed_segments=_segments_to_canonical(
            snapshot.sensitivity_segments,
            value_transform=(_mmol_to_mgdl_per_unit if is_mmol else None),
        ),
        default_checked=(
            not has_custom_pump_profile
            and snapshot.sensitivity_segments is not None
            and len(snapshot.sensitivity_segments) > 0
        ),
    )

    return OnboardingDerivation(
        has_profile=True,
        units_converted=is_mmol,
        units_unknown=units_unknown,
        target_low=target_low,
        target_high=target_high,
        dia_hours=dia_hours,
        carb_ratio_schedule=carb_ratio_schedule,
        isf_schedule=isf_schedule,
        basal_schedule=basal_schedule,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_derivation(
    *,
    current_target_range: TargetGlucoseRange | None,
    current_insulin_config: InsulinConfig | None,
    current_pump_profile: PumpProfile | None,
) -> OnboardingDerivation:
    """Build a no-snapshot derivation: every field carries the user's
    current value but `proposed_value=None`. AC11 path (Tandem-only-
    via-tconnectsync etc) -- wizard skips the import step entirely.
    """
    current_basal = _extract_axis_from_pump_profile(current_pump_profile, "basal_rate")
    current_isf = _extract_axis_from_pump_profile(
        current_pump_profile, "correction_factor"
    )
    current_icr = _extract_axis_from_pump_profile(current_pump_profile, "carb_ratio")
    return OnboardingDerivation(
        has_profile=False,
        units_converted=False,
        units_unknown=False,
        target_low=OnboardingNumericFieldDerivation(
            field="target_low",
            current_value=(
                current_target_range.low_target if current_target_range else None
            ),
            proposed_value=None,
            default_checked=False,
        ),
        target_high=OnboardingNumericFieldDerivation(
            field="target_high",
            current_value=(
                current_target_range.high_target if current_target_range else None
            ),
            proposed_value=None,
            default_checked=False,
        ),
        dia_hours=OnboardingNumericFieldDerivation(
            field="dia_hours",
            current_value=(
                current_insulin_config.dia_hours if current_insulin_config else None
            ),
            proposed_value=None,
            default_checked=False,
        ),
        carb_ratio_schedule=OnboardingScheduleFieldDerivation(
            field="carb_ratio_schedule",
            current_segments=current_icr,
            proposed_segments=None,
            default_checked=False,
        ),
        isf_schedule=OnboardingScheduleFieldDerivation(
            field="isf_schedule",
            current_segments=current_isf,
            proposed_segments=None,
            default_checked=False,
        ),
        basal_schedule=OnboardingScheduleFieldDerivation(
            field="basal_schedule",
            current_segments=current_basal,
            proposed_segments=None,
            default_checked=False,
        ),
    )


def _derive_target_field(
    *,
    field: str,
    snapshot_segments: list[dict] | None,
    current_value: float | None,
    platform_default: float,
    is_mmol: bool,
    aggregator: Callable[[list[float]], float],
) -> OnboardingNumericFieldDerivation:
    """Single-value target derivation.

    For time-varying targets (the segmented case), we collapse to
    one number using `aggregator` (`min` for low, `max` for high).
    The wizard renders one row per target, so the worst-case bound
    across the schedule is the safest summary -- matches the
    discovery report's profile_summary semantics.
    """
    proposed = _aggregate_segment_value(snapshot_segments, aggregator)
    if proposed is not None and is_mmol:
        proposed = round(proposed * MMOL_TO_MGDL, 1)
    # Sanitize before model construction: the schema's gt=0 guard
    # would RAISE ValidationError on non-positive values rather than
    # fail-safing. Coerce to None so the wizard sees "no proposal"
    # cleanly. Also defensively coerce current_value -- a corrupted
    # canonical row with a stored 0 would otherwise crash here too.
    proposed = _coerce_positive(proposed)
    current_value = _coerce_positive(current_value)
    return OnboardingNumericFieldDerivation(
        field=field,
        current_value=current_value,
        proposed_value=proposed,
        # Pre-check iff user is at platform default OR the import
        # would be a no-op (current matches proposal).
        default_checked=proposed is not None
        and (
            _is_default(current_value, platform_default)
            or _values_match(current_value, proposed)
        ),
    )


def _aggregate_segment_value(
    segments: list[dict] | None,
    aggregator: Callable[[list[float]], float],
) -> float | None:
    """Apply `aggregator` (min/max) over the `value` field of each
    segment, dropping non-numeric. None when no usable values."""
    if not segments:
        return None
    values: list[float] = []
    for entry in segments:
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        try:
            values.append(float(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return aggregator(values) if values else None


def _segments_to_canonical(
    raw: list[dict] | None,
    *,
    value_transform: Callable[[float], float] | None = None,
) -> list[OnboardingScheduleSegment] | None:
    """NS `[{time, value, timeAsSeconds?}, ...]` -> our canonical
    `[{start_minutes, value}, ...]`.

    - `time` is parsed from "HH:MM" when present; falls back to
      `timeAsSeconds // 60`. Segments missing both are dropped.
    - Sorted by `start_minutes` (NS doesn't guarantee order). Sort
      is stable; equal-start_minutes segments would keep insertion
      order, but NS profiles never emit duplicate keys in practice.
    - `value_transform`, when provided, runs over each segment's
      `value` -- used for mmol->mg/dL on the ISF schedule.
    - Returns None when the input is empty/None or no segment
      survives parsing -- the wizard's "schedule absent" branch
      fires cleanly.

    **Midnight-wrap (CR H2):** if the first segment isn't at
    `start_minutes=0` (e.g. a basal pattern starting at `06:00`),
    THIS function does NOT prepend a wrap segment. The 43.7c
    apply orchestrator owns full-24h coverage on the canonical
    `pump_profiles.segments` write -- it's responsible for
    detecting the gap and either (a) prepending the last segment
    to cover `00:00 -> first_start` (matches Loop / AAPS
    convention) or (b) raising a "schedule has unconvered hours"
    error to surface in the wizard. Keeping the responsibility
    at the apply step lets the derive module stay pure.
    """
    if not raw:
        return None
    parsed: list[OnboardingScheduleSegment] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        start_minutes = _segment_start_minutes(entry)
        if start_minutes is None:
            continue
        value = entry.get("value")
        try:
            float_value = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if value_transform is not None:
            float_value = value_transform(float_value)
        # Drop non-positive segments rather than crashing the whole
        # derive call on the schema's gt=0 guard. NS profiles in the
        # wild sometimes carry 0-valued basal segments (suspend
        # patterns encoded as 0, malformed Loop overrides, AAPS edge
        # cases). The wizard sees the surviving segments only --
        # safer than 500ing the endpoint.
        if float_value <= 0:
            continue
        parsed.append(
            OnboardingScheduleSegment(
                start_minutes=start_minutes,
                value=float_value,
            )
        )
    if not parsed:
        return None
    parsed.sort(key=lambda seg: seg.start_minutes)
    return parsed


def _segment_start_minutes(entry: dict) -> int | None:
    """Resolve a segment's start-of-day minute count.

    Prefers the explicit `time` "HH:MM" string (NS canonical); falls
    back to `timeAsSeconds` for profiles that omit `time` (some Loop
    versions do this on derived schedules). Returns None when both
    are absent / unparseable -- caller drops the segment.
    """
    time_str = entry.get("time")
    if isinstance(time_str, str):
        parts = time_str.split(":")
        if len(parts) >= 2:
            try:
                hours = int(parts[0])
                minutes = int(parts[1])
            except ValueError:
                pass
            else:
                if 0 <= hours < 24 and 0 <= minutes < 60:
                    return hours * 60 + minutes
    seconds = entry.get("timeAsSeconds")
    if isinstance(seconds, int | float):
        try:
            mins = int(seconds) // 60
        except (TypeError, ValueError):
            return None
        if 0 <= mins < 24 * 60:
            return mins
    return None


def _extract_axis_from_pump_profile(
    profile: PumpProfile | None, axis: str
) -> list[OnboardingScheduleSegment] | None:
    """Pull a single axis (basal_rate / carb_ratio / correction_factor)
    out of the merged `pump_profiles.segments` list.

    Our canonical pump_profile stores ONE list of merged segments
    where each entry carries `start_minutes` + per-axis values
    (`basal_rate`, `carb_ratio`, `correction_factor`, `target_bg`).
    For the wizard's diff table we want each axis as its own
    schedule. Drops segments where the axis value is missing/null.
    Returns None when no profile or no segments carry the axis.
    """
    if profile is None or not profile.segments:
        return None
    out: list[OnboardingScheduleSegment] = []
    for seg in profile.segments:
        if not isinstance(seg, dict):
            continue
        # CR M3: JSONB round-trips can produce floats where ints were
        # written; coerce numerics rather than dropping the segment.
        # Booleans are int subclasses in Python -- explicitly reject
        # them so a stray `True` doesn't masquerade as start_minutes=1.
        raw_start = seg.get("start_minutes")
        if isinstance(raw_start, bool) or not isinstance(raw_start, int | float):
            continue
        try:
            start_minutes = int(raw_start)
        except (TypeError, ValueError):
            continue
        if not (0 <= start_minutes < 24 * 60):
            continue
        value = seg.get(axis)
        if value is None:
            continue
        try:
            float_value = float(value)
        except (TypeError, ValueError):
            continue
        # Drop non-positive entries -- a corrupted JSONB row with a
        # stored 0 basal_rate / carb_ratio / correction_factor would
        # otherwise crash on the schema's gt=0 guard. Same treatment
        # as `_segments_to_canonical` for symmetry.
        if float_value <= 0:
            continue
        out.append(
            OnboardingScheduleSegment(
                start_minutes=start_minutes,
                value=float_value,
            )
        )
    if not out:
        return None
    out.sort(key=lambda s: s.start_minutes)
    return out


def _is_default(value: float | None, platform_default: float) -> bool:
    """AC4: True iff the stored value matches the platform default
    within float tolerance.

    `value=None` (no canonical row at all) is treated as "default" --
    a fresh-signup user has no row, so checking-by-default is the
    right UX (nothing to overwrite). CR M4 note: this conflates "no
    row" with "user explicitly at default"; if the platform later
    treats absent rows as "explicitly opted out," update Story 43.7c
    apply orchestrator + this comparison together so AC4 stays
    correct.

    Tolerance is generous (1e-3) because canonical defaults are
    integer-ish (70.0, 180.0, 4.0) and stored as floats; round-trip
    drift is well below 1e-3.
    """
    if value is None:
        return True
    return abs(value - platform_default) < 1e-3


def _coerce_positive(value: float | None) -> float | None:
    """Boundary sanitizer for the `Field(gt=0)` schema constraints.

    Returns the input unchanged when it's already a positive float,
    None when it's None, and None when it's <= 0 (instead of letting
    the model construction raise ValidationError).

    NS profiles in the wild occasionally carry 0 / negative values
    (malformed uploads, suspend-encoded-as-zero, edge cases in older
    Loop / AAPS versions). The medical-safety guard at the schema
    layer is correct -- we don't WANT to write zeros to canonical
    settings -- but we also don't want to 500 the whole evaluate
    path on a single bad field. Coercing to None at the boundary
    means the wizard sees "no proposal for this field" cleanly and
    the user keeps their existing setting. CR feedback on PR #595.
    """
    if value is None:
        return None
    if value <= 0:
        return None
    return value


def _values_match(a: float | None, b: float | None) -> bool:
    """True iff two values are close enough that importing one over
    the other would be a no-op. CR M1: the wizard pre-checks when
    proposal == current so a user who happens to have dialed in the
    EXACT same setting NS proposes doesn't see a misleading
    unchecked row.

    Both None counts as a match (no-op import). One-sided None
    counts as a mismatch (we have something to import or remove).
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) < 1e-3


def _classify_units(raw: str | None) -> tuple[bool, bool]:
    """Classify a Nightscout `source_units` string.

    Returns `(is_mmol, is_mgdl)`. Both False -> unknown unit; the
    caller flips `units_unknown=True` on the derivation so the
    wizard refuses to auto-import glucose-domain values until the
    user confirms (CR H1).

    Accepted variants:
      - mg/dL: "mg/dl", "mgdl", "mg-dl" (case-insensitive)
      - mmol/L: "mmol", "mmol/l", "mmol/litre", "mmoll"
    """
    if not isinstance(raw, str):
        return False, False
    normalized = raw.lower().strip()
    if normalized in _KNOWN_MGDL_UNITS:
        return False, True
    if normalized in _KNOWN_MMOL_UNITS:
        return True, False
    return False, False


def _mmol_to_mgdl_per_unit(value: float) -> float:
    """ISF (mmol/L per U) -> mg/dL per U. Multiplies by MMOL_TO_MGDL,
    rounds to 1 decimal."""
    return round(value * MMOL_TO_MGDL, 1)
