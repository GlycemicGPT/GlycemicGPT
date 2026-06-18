"""Story 43.7b -- tests for the pure-function derive module.

Pure unit tests over `derive_onboarding_proposals()` -- no DB, no
HTTP, no fixtures. Each test stands up a transient
`NightscoutProfileSnapshot` + transient canonical-settings rows and
asserts the resulting `OnboardingDerivation`. Table-driven coverage
across Loop / AAPS / Trio / mmol / sparse / no-profile shapes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from src.models.insulin_config import InsulinConfig
from src.models.nightscout_profile_snapshot import NightscoutProfileSnapshot
from src.models.pump_profile import PumpProfile
from src.models.target_glucose_range import TargetGlucoseRange
from src.services.integrations.nightscout.onboarding_derive import (
    DEFAULT_DIA_HOURS,
    DEFAULT_TARGET_HIGH_MGDL,
    DEFAULT_TARGET_LOW_MGDL,
    derive_onboarding_proposals,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


# Sentinel so test fixtures can distinguish "use default schedule"
# from "explicit empty list" (the latter is a meaningful test input;
# `or default` would conflate them since `[] or X == X`).
_DEFAULT_SENTINEL: Any = object()


def _mk_snapshot(
    *,
    units: str = "mg/dl",
    dia_hours: float | None = 5.0,
    timezone: str = "UTC",
    basal_segments: Any = _DEFAULT_SENTINEL,
    carb_ratio_segments: Any = _DEFAULT_SENTINEL,
    sensitivity_segments: Any = _DEFAULT_SENTINEL,
    target_low_segments: Any = _DEFAULT_SENTINEL,
    target_high_segments: Any = _DEFAULT_SENTINEL,
) -> NightscoutProfileSnapshot:
    """Build a transient snapshot row (not persisted).

    Pass an explicit `[]` for any segment field to test the empty-
    schedule branch; pass `None` to test the missing-schedule
    branch; omit the kwarg to use a sensible default fixture.
    """
    return NightscoutProfileSnapshot(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        nightscout_connection_id=uuid.uuid4(),
        fetched_at=datetime.now(UTC),
        source_default_profile_name="Default",
        source_units=units,
        source_timezone=timezone,
        source_dia_hours=dia_hours,
        basal_segments=(
            [{"time": "00:00", "value": 0.65}]
            if basal_segments is _DEFAULT_SENTINEL
            else basal_segments
        ),
        carb_ratio_segments=(
            [{"time": "00:00", "value": 12.0}]
            if carb_ratio_segments is _DEFAULT_SENTINEL
            else carb_ratio_segments
        ),
        sensitivity_segments=(
            [{"time": "00:00", "value": 50.0}]
            if sensitivity_segments is _DEFAULT_SENTINEL
            else sensitivity_segments
        ),
        target_low_segments=(
            [{"time": "00:00", "value": 90.0}]
            if target_low_segments is _DEFAULT_SENTINEL
            else target_low_segments
        ),
        target_high_segments=(
            [{"time": "00:00", "value": 120.0}]
            if target_high_segments is _DEFAULT_SENTINEL
            else target_high_segments
        ),
        profile_json_full={},
    )


def _mk_target_range(
    *,
    low: float = DEFAULT_TARGET_LOW_MGDL,
    high: float = DEFAULT_TARGET_HIGH_MGDL,
) -> TargetGlucoseRange:
    """Default low=70, high=180 ('user not customized'). Override
    to simulate a user with custom target."""
    return TargetGlucoseRange(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        urgent_low=55.0,
        low_target=low,
        high_target=high,
        urgent_high=250.0,
    )


def _mk_insulin_config(
    *,
    dia_hours: float = DEFAULT_DIA_HOURS,
) -> InsulinConfig:
    return InsulinConfig(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        insulin_type="humalog",
        dia_hours=dia_hours,
        onset_minutes=15.0,
    )


def _mk_pump_profile(
    *,
    segments: list[dict] | None = None,
) -> PumpProfile:
    """When `segments=None`, returns a profile with NO segments
    (treated as 'no custom config'). Pass an explicit list to
    simulate a user with customized pump settings."""
    return PumpProfile(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        profile_name="Tandem-imported",
        is_active=True,
        segments=segments or [],
        insulin_duration_min=300,
        carb_entry_enabled=True,
        synced_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Loop happy path
# ---------------------------------------------------------------------------


class TestLoopHappyPath:
    """Loop profile, mg/dL, default canonical settings -> all
    proposals checked-by-default per AC4."""

    def test_basic_loop_profile_pre_checks_everything(self):
        snapshot = _mk_snapshot()  # mg/dl defaults

        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),  # platform default
            current_insulin_config=_mk_insulin_config(),  # platform default
            current_pump_profile=None,  # no custom pump
        )

        assert result.has_profile is True
        assert result.units_converted is False

        # Numeric fields all checked-by-default (user is at platform default).
        assert result.target_low.proposed_value == 90.0
        assert result.target_low.current_value == DEFAULT_TARGET_LOW_MGDL
        assert result.target_low.default_checked is True

        assert result.target_high.proposed_value == 120.0
        assert result.target_high.current_value == DEFAULT_TARGET_HIGH_MGDL
        assert result.target_high.default_checked is True

        assert result.dia_hours.proposed_value == 5.0
        assert result.dia_hours.current_value == DEFAULT_DIA_HOURS
        assert result.dia_hours.default_checked is True

        # Schedules: no pump_profile -> default-checked.
        assert result.basal_schedule.proposed_segments is not None
        assert result.basal_schedule.proposed_segments[0].start_minutes == 0
        assert result.basal_schedule.proposed_segments[0].value == 0.65
        assert result.basal_schedule.default_checked is True
        assert result.basal_schedule.current_segments is None  # no pump profile

        assert result.carb_ratio_schedule.proposed_segments[0].value == 12.0
        assert result.carb_ratio_schedule.default_checked is True

        assert result.isf_schedule.proposed_segments[0].value == 50.0
        assert result.isf_schedule.default_checked is True


# ---------------------------------------------------------------------------
# AC4 default_checked: customized user -> all UNchecked
# ---------------------------------------------------------------------------


class TestAC4DefaultChecked:
    """AC4: 'defaults to checked if the user has no current value
    (or platform default), unchecked if the user already has a
    non-default value'. The latter is the most important guard --
    a long-time user with custom settings must NOT have their
    config silently overwritten."""

    def test_customized_target_unchecks_target_rows(self):
        snapshot = _mk_snapshot()
        # User has dialed in a tighter target.
        custom_range = _mk_target_range(low=80.0, high=140.0)

        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=custom_range,
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )

        # Targets: customized -> UNchecked.
        assert result.target_low.default_checked is False
        assert result.target_high.default_checked is False
        # Other fields untouched by target customization.
        assert result.dia_hours.default_checked is True

    def test_customized_dia_unchecks_dia_row(self):
        snapshot = _mk_snapshot(dia_hours=6.0)
        # User has DIA at 5h (not the 4h default).
        custom_insulin = _mk_insulin_config(dia_hours=5.0)

        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=custom_insulin,
            current_pump_profile=None,
        )

        assert result.dia_hours.proposed_value == 6.0
        assert result.dia_hours.current_value == 5.0
        assert result.dia_hours.default_checked is False
        assert result.target_low.default_checked is True

    def test_existing_pump_profile_unchecks_all_schedules(self):
        snapshot = _mk_snapshot()
        # User has Tandem-synced pump segments already.
        custom_pump = _mk_pump_profile(
            segments=[
                {
                    "time": "00:00",
                    "start_minutes": 0,
                    "basal_rate": 1.0,
                    "carb_ratio": 10.0,
                    "correction_factor": 60.0,
                    "target_bg": 110,
                },
            ]
        )

        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=custom_pump,
        )

        # All three schedules: customized -> UNchecked.
        assert result.basal_schedule.default_checked is False
        assert result.carb_ratio_schedule.default_checked is False
        assert result.isf_schedule.default_checked is False
        # Numeric fields still default-checked (independent axes).
        assert result.target_low.default_checked is True
        assert result.dia_hours.default_checked is True
        # current_segments populated from the pump profile.
        assert result.basal_schedule.current_segments is not None
        assert result.basal_schedule.current_segments[0].value == 1.0
        assert result.carb_ratio_schedule.current_segments[0].value == 10.0
        assert result.isf_schedule.current_segments[0].value == 60.0


# ---------------------------------------------------------------------------
# Unit conversion (mmol -> mg/dL)
# ---------------------------------------------------------------------------


class TestUnitConversion:
    def test_mmol_target_converts_to_mgdl(self):
        snapshot = _mk_snapshot(
            units="mmol",
            target_low_segments=[{"time": "00:00", "value": 4.4}],
            target_high_segments=[{"time": "00:00", "value": 7.8}],
        )

        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )

        assert result.units_converted is True
        # Hardcoded goldens (not derived from the constant) so the test
        # fails if the shared 18.0182 factor ever drifts:
        #   4.4 mmol/L * 18.0182 = 79.28 -> 79.3
        #   7.8 mmol/L * 18.0182 = 140.54 -> 140.5
        assert result.target_low.proposed_value == 79.3
        assert result.target_high.proposed_value == 140.5

    def test_mmol_isf_converts_to_mgdl_per_unit(self):
        """ISF in mmol/L per U converts to mg/dL per U at segment level."""
        snapshot = _mk_snapshot(
            units="mmol",
            sensitivity_segments=[{"time": "00:00", "value": 2.5}],
        )

        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )

        assert result.units_converted is True
        # 2.5 mmol/L per U * 18.0182 = 45.0455 -> 45.0 (hardcoded golden).
        assert result.isf_schedule.proposed_segments[0].value == 45.0

    def test_mmol_basal_and_carb_ratio_not_converted(self):
        """Rate (U/hr) and carb ratio (g/U) are unit-agnostic."""
        snapshot = _mk_snapshot(
            units="mmol",
            basal_segments=[{"time": "00:00", "value": 0.7}],
            carb_ratio_segments=[{"time": "00:00", "value": 11.0}],
        )

        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )

        # Pass-through.
        assert result.basal_schedule.proposed_segments[0].value == 0.7
        assert result.carb_ratio_schedule.proposed_segments[0].value == 11.0

    def test_mgdl_no_conversion(self):
        snapshot = _mk_snapshot(units="mg/dl")
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )
        assert result.units_converted is False
        assert result.units_unknown is False
        assert result.target_low.proposed_value == 90.0

    def test_long_form_mmol_l_recognized(self):
        """CR H1: 'mmol/L' (long form, mixed case) must be recognized,
        not silently fall through as mg/dL."""
        snapshot = _mk_snapshot(
            units="mmol/L",
            target_low_segments=[{"time": "00:00", "value": 4.4}],
            target_high_segments=[{"time": "00:00", "value": 7.8}],
        )
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )
        assert result.units_converted is True
        assert result.units_unknown is False
        # 4.4 * 18.0182 = 79.28 -> 79.3 (hardcoded golden).
        assert result.target_low.proposed_value == 79.3

    def test_unknown_units_flagged(self):
        """CR H1: an unknown unit string must NOT silently default to
        mg/dL. The wizard should refuse to auto-import glucose-domain
        values."""
        snapshot = _mk_snapshot(units="some-future-unit-string")
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )
        assert result.units_converted is False
        assert result.units_unknown is True

    def test_units_none_flagged(self):
        """A profile with `source_units=None` is also unknown."""
        snapshot = _mk_snapshot(units=None)
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )
        assert result.units_unknown is True


class TestIdenticalValuePreCheck:
    """CR M1: when the user's current value is non-default but
    happens to match the proposed value, importing is a no-op
    and the wizard should pre-check the row."""

    def test_dia_match_pre_checks_even_when_customized(self):
        snapshot = _mk_snapshot(dia_hours=5.0)
        # User's customized DIA happens to match what NS proposes.
        custom_insulin = _mk_insulin_config(dia_hours=5.0)
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=custom_insulin,
            current_pump_profile=None,
        )
        # Customized BUT identical to proposal -> still pre-checked
        # (importing is a no-op).
        assert result.dia_hours.default_checked is True

    def test_target_match_pre_checks_even_when_customized(self):
        snapshot = _mk_snapshot(
            target_low_segments=[{"time": "00:00", "value": 80.0}],
            target_high_segments=[{"time": "00:00", "value": 140.0}],
        )
        custom_range = _mk_target_range(low=80.0, high=140.0)
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=custom_range,
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )
        assert result.target_low.default_checked is True
        assert result.target_high.default_checked is True


class TestPumpProfileFloatCoerce:
    """CR M3: JSONB round-trips can produce floats where ints were
    written. Coerce numerics rather than dropping the segment."""

    def test_float_start_minutes_coerced(self):
        snapshot = _mk_snapshot()
        # Plant float start_minutes (as a JSONB round-trip would).
        custom_pump = _mk_pump_profile(
            segments=[
                {
                    "time": "00:00",
                    "start_minutes": 0.0,  # float
                    "basal_rate": 1.2,
                    "carb_ratio": 10.0,
                    "correction_factor": 60.0,
                },
            ]
        )
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=custom_pump,
        )
        # Coerced -- segment survived.
        assert result.basal_schedule.current_segments is not None
        assert result.basal_schedule.current_segments[0].start_minutes == 0
        assert result.basal_schedule.current_segments[0].value == 1.2

    def test_bool_start_minutes_rejected(self):
        """Python's `bool` is an int subclass; reject explicitly so a
        stray `True` doesn't become start_minutes=1."""
        snapshot = _mk_snapshot()
        custom_pump = _mk_pump_profile(
            segments=[
                {
                    "start_minutes": True,  # bool, not int
                    "basal_rate": 1.2,
                },
            ]
        )
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=custom_pump,
        )
        # The segment was dropped -> no current_segments.
        assert result.basal_schedule.current_segments is None

    def test_out_of_range_start_minutes_rejected(self):
        snapshot = _mk_snapshot()
        custom_pump = _mk_pump_profile(
            segments=[
                {"start_minutes": 0, "basal_rate": 1.0},
                {"start_minutes": 1500, "basal_rate": 1.5},  # > 24h
                {"start_minutes": -60, "basal_rate": 0.5},  # negative
            ]
        )
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=custom_pump,
        )
        segs = result.basal_schedule.current_segments
        assert segs is not None
        # Only the in-range segment survived.
        assert len(segs) == 1
        assert segs[0].start_minutes == 0


# ---------------------------------------------------------------------------
# Time-segment parsing
# ---------------------------------------------------------------------------


class TestSegmentParsing:
    def test_hh_mm_parsing(self):
        snapshot = _mk_snapshot(
            basal_segments=[
                {"time": "00:00", "value": 0.5},
                {"time": "06:00", "value": 0.7},
                {"time": "22:30", "value": 0.6},
            ]
        )

        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )

        segs = result.basal_schedule.proposed_segments
        assert segs is not None
        assert [s.start_minutes for s in segs] == [0, 360, 1350]
        assert [s.value for s in segs] == [0.5, 0.7, 0.6]

    def test_time_as_seconds_fallback(self):
        """When `time` is missing/invalid, fall back to timeAsSeconds."""
        snapshot = _mk_snapshot(
            basal_segments=[
                {"timeAsSeconds": 0, "value": 0.5},
                {"timeAsSeconds": 28800, "value": 0.7},  # 8h
            ]
        )

        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )

        segs = result.basal_schedule.proposed_segments
        assert segs is not None
        assert [s.start_minutes for s in segs] == [0, 480]

    def test_segments_sorted_by_start_minutes(self):
        """NS doesn't guarantee order; we sort."""
        snapshot = _mk_snapshot(
            basal_segments=[
                {"time": "12:00", "value": 1.2},
                {"time": "00:00", "value": 0.5},
                {"time": "06:00", "value": 0.7},
            ]
        )

        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )

        segs = result.basal_schedule.proposed_segments
        assert [s.start_minutes for s in segs] == [0, 360, 720]
        assert [s.value for s in segs] == [0.5, 0.7, 1.2]

    def test_segments_with_invalid_entries_dropped(self):
        snapshot = _mk_snapshot(
            basal_segments=[
                {"time": "00:00", "value": 0.5},
                {"time": "garbage", "value": 0.7},  # bad time
                {"time": "06:00", "value": "not a number"},  # bad value
                "not a dict",  # bad shape
                {"time": "12:00", "value": 1.2},
            ]
        )

        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )

        segs = result.basal_schedule.proposed_segments
        # Only the two valid segments survive.
        assert len(segs) == 2
        assert [s.start_minutes for s in segs] == [0, 720]


# ---------------------------------------------------------------------------
# Time-varying targets -> min/max aggregation
# ---------------------------------------------------------------------------


class TestSegmentedTargets:
    """Time-varying targets collapse to one number using min(low) /
    max(high) -- the safest summary the wizard can render in one row."""

    def test_segmented_target_low_uses_min(self):
        snapshot = _mk_snapshot(
            target_low_segments=[
                {"time": "00:00", "value": 90.0},
                {"time": "08:00", "value": 80.0},  # lower
                {"time": "22:00", "value": 100.0},
            ]
        )

        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )

        assert result.target_low.proposed_value == 80.0

    def test_segmented_target_high_uses_max(self):
        snapshot = _mk_snapshot(
            target_high_segments=[
                {"time": "00:00", "value": 130.0},
                {"time": "08:00", "value": 150.0},  # higher
                {"time": "22:00", "value": 110.0},
            ]
        )

        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )

        assert result.target_high.proposed_value == 150.0


# ---------------------------------------------------------------------------
# AC11 / sparse profile: no snapshot OR empty schedules
# ---------------------------------------------------------------------------


class TestAC11Sparse:
    def test_no_snapshot_returns_empty_derivation(self):
        """Tandem-via-tconnectsync path: pump posts treatments
        but never authors a profile -> snapshot is None ->
        wizard skips the settings-import step."""
        result = derive_onboarding_proposals(
            None,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )

        assert result.has_profile is False
        # All fields present but with no proposed values.
        assert result.target_low.proposed_value is None
        assert result.target_high.proposed_value is None
        assert result.dia_hours.proposed_value is None
        assert result.basal_schedule.proposed_segments is None
        assert result.carb_ratio_schedule.proposed_segments is None
        assert result.isf_schedule.proposed_segments is None
        # No proposals -> nothing to import -> all unchecked.
        assert result.target_low.default_checked is False
        assert result.dia_hours.default_checked is False
        assert result.basal_schedule.default_checked is False

    def test_no_snapshot_preserves_current_values(self):
        """Even on a no-snapshot path, the wizard's diff table
        should still show the user's current settings (so they
        understand what they have)."""
        custom_range = _mk_target_range(low=85.0, high=140.0)
        custom_insulin = _mk_insulin_config(dia_hours=5.5)

        result = derive_onboarding_proposals(
            None,
            current_target_range=custom_range,
            current_insulin_config=custom_insulin,
            current_pump_profile=None,
        )

        assert result.target_low.current_value == 85.0
        assert result.target_high.current_value == 140.0
        assert result.dia_hours.current_value == 5.5

    def test_snapshot_with_empty_schedules(self):
        """Snapshot exists but every schedule list is empty
        (degenerate but legal NS shape). Numeric fields with
        single values still propose; schedules don't."""
        snapshot = _mk_snapshot(
            dia_hours=4.5,
            basal_segments=[],
            carb_ratio_segments=[],
            sensitivity_segments=[],
            target_low_segments=[],
            target_high_segments=[],
        )

        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )

        assert result.has_profile is True
        # No targets to aggregate -> proposed=None.
        assert result.target_low.proposed_value is None
        assert result.target_high.proposed_value is None
        # No schedules -> proposed_segments None, default unchecked
        # (no proposal to apply).
        assert result.basal_schedule.proposed_segments is None
        assert result.basal_schedule.default_checked is False
        # DIA still derives from the single source_dia_hours field.
        assert result.dia_hours.proposed_value == 4.5

    def test_dia_missing_not_checked(self):
        """`source_dia_hours=None` -> proposed=None -> not checked
        even if user is at the default."""
        snapshot = _mk_snapshot(dia_hours=None)

        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )

        assert result.dia_hours.proposed_value is None
        assert result.dia_hours.default_checked is False


# ---------------------------------------------------------------------------
# No canonical-settings rows yet (fresh signup)
# ---------------------------------------------------------------------------


class TestFreshSignup:
    def test_all_canonical_none_treats_user_as_default(self):
        """Brand-new user with no target_glucose_range,
        insulin_config, or pump_profile rows yet -- all checked
        because there's nothing to overwrite."""
        snapshot = _mk_snapshot()
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=None,
            current_insulin_config=None,
            current_pump_profile=None,
        )

        assert result.target_low.current_value is None
        assert result.target_high.current_value is None
        assert result.dia_hours.current_value is None
        # All checked because "no row" counts as default per AC4.
        assert result.target_low.default_checked is True
        assert result.target_high.default_checked is True
        assert result.dia_hours.default_checked is True
        assert result.basal_schedule.default_checked is True
        assert result.carb_ratio_schedule.default_checked is True
        assert result.isf_schedule.default_checked is True


# ---------------------------------------------------------------------------
# Coupling: defaults must mirror the SQLAlchemy column defaults
# ---------------------------------------------------------------------------


class TestNonPositiveInputCoercion:
    """Regression tests for the four sites where a non-positive
    input (NS-supplied 0/negative dia, target, basal/ICR/ISF
    segment, or a corrupted canonical row) previously raised
    Pydantic ValidationError on the schema's gt=0 guard. Each
    site now coerces to None / drops the segment, so a single
    bad field doesn't 500 the whole derive call.
    """

    def test_zero_dia_coerced_to_none_no_crash(self):
        """NS profile with `source_dia_hours=0` (malformed upload)
        must not 500 the call -- proposed_dia becomes None."""
        snapshot = _mk_snapshot(dia_hours=0.0)
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )
        assert result.dia_hours.proposed_value is None
        assert result.dia_hours.default_checked is False

    def test_negative_dia_coerced_to_none_no_crash(self):
        snapshot = _mk_snapshot(dia_hours=-1.5)
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )
        assert result.dia_hours.proposed_value is None

    def test_zero_target_low_coerced_to_none_no_crash(self):
        """An NS target_low of 0 (impossible but seen on malformed
        uploads) must not crash -- target_low.proposed_value=None.
        """
        snapshot = _mk_snapshot(target_low_segments=[{"time": "00:00", "value": 0.0}])
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )
        assert result.target_low.proposed_value is None

    def test_negative_target_high_coerced_to_none_no_crash(self):
        snapshot = _mk_snapshot(target_high_segments=[{"time": "00:00", "value": -5.0}])
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )
        assert result.target_high.proposed_value is None

    def test_zero_basal_segment_dropped_no_crash(self):
        """NS profile with a 0-valued basal segment (suspend-encoded-
        as-zero pattern, malformed upload). The 0 segment is
        dropped; surviving segments still flow through.
        """
        snapshot = _mk_snapshot(
            basal_segments=[
                {"time": "00:00", "value": 0.5},
                {"time": "06:00", "value": 0.0},  # bad -- dropped
                {"time": "12:00", "value": 0.7},
            ]
        )
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )
        segs = result.basal_schedule.proposed_segments
        assert segs is not None
        # Only the two positive segments survived.
        assert [s.start_minutes for s in segs] == [0, 720]
        assert [s.value for s in segs] == [0.5, 0.7]

    def test_all_basal_segments_zero_returns_none_schedule(self):
        """If every segment is non-positive, the schedule disappears
        entirely (proposed_segments=None) -- wizard skips the row."""
        snapshot = _mk_snapshot(
            basal_segments=[
                {"time": "00:00", "value": 0.0},
                {"time": "12:00", "value": -0.5},
            ]
        )
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )
        assert result.basal_schedule.proposed_segments is None

    def test_pump_profile_zero_basal_rate_segment_dropped(self):
        """A corrupted canonical pump_profile row with a 0
        basal_rate must not crash on read -- the segment is
        dropped from current_segments."""
        snapshot = _mk_snapshot()
        custom_pump = _mk_pump_profile(
            segments=[
                {"start_minutes": 0, "basal_rate": 1.0},
                {"start_minutes": 360, "basal_rate": 0.0},  # bad
                {"start_minutes": 720, "basal_rate": 1.5},
            ]
        )
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=_mk_target_range(),
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=custom_pump,
        )
        segs = result.basal_schedule.current_segments
        assert segs is not None
        assert [s.start_minutes for s in segs] == [0, 720]

    def test_corrupted_current_target_zero_coerced_to_none(self):
        """Defensively: if a canonical TargetGlucoseRange row got
        corrupted with a stored 0 (would never happen via normal
        writes, but defense-in-depth), the derive must not crash.
        """
        snapshot = _mk_snapshot()
        # Build a corrupted-state range row and bypass the
        # SQLAlchemy default by setting low_target=0 directly. (In
        # production this would never happen; this is paranoia.)
        bad_range = _mk_target_range(low=0.0, high=0.0)
        result = derive_onboarding_proposals(
            snapshot,
            current_target_range=bad_range,
            current_insulin_config=_mk_insulin_config(),
            current_pump_profile=None,
        )
        # current_value coerced to None; proposal still flows.
        assert result.target_low.current_value is None
        assert result.target_low.proposed_value == 90.0
        assert result.target_high.current_value is None
        assert result.target_high.proposed_value == 120.0


def _scalar_default(column) -> float:
    """Pull the scalar value out of a SQLAlchemy column's default,
    failing loudly with a clear message if the default is a
    callable / server_default / sequence. CR L4: previous
    `.default.arg` access produced confusing AttributeErrors when
    the default form changed.
    """
    default = column.default
    assert default is not None, (
        f"column {column.name} has no default; AC4 coupling test needs one"
    )
    assert default.is_scalar, (
        f"column {column.name} default is not scalar "
        f"(got {type(default).__name__}); update the test helper to "
        "handle the new default form before assuming `.arg` is the value"
    )
    return float(default.arg)


def test_default_constants_match_canonical_model_defaults():
    """If a future migration changes a model default, this test
    fires so the AC4 constant stays coupled."""
    assert (
        _scalar_default(TargetGlucoseRange.__table__.c.low_target)
        == DEFAULT_TARGET_LOW_MGDL
    )
    assert (
        _scalar_default(TargetGlucoseRange.__table__.c.high_target)
        == DEFAULT_TARGET_HIGH_MGDL
    )
    assert _scalar_default(InsulinConfig.__table__.c.dia_hours) == DEFAULT_DIA_HOURS
