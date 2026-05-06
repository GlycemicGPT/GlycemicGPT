"""Parser tests for Nightscout input models against Tier-1 fixtures.

Story 43.3 PR1. Each fixture exercises a specific routing decision
or wire-format quirk documented in the synthesis doc. The tests
assert what the translator's input layer extracts from each shape;
the ORM-mapping layer (PR2) consumes these typed results.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.services.integrations.nightscout.models import (
    MGDL_PER_MMOL,
    SGV_MAX_VALID,
    SGV_MIN_VALID,
    NightscoutDeviceStatus,
    NightscoutEntry,
    NightscoutProfile,
    NightscoutTreatment,
    detect_uploader,
    parse_openaps_uri,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "nightscout"


def _load(category: str, name: str) -> dict:
    """Load a fixture by category + filename (without .json)."""
    return json.loads((FIXTURE_ROOT / category / f"{name}.json").read_text())


# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------


class TestConstants:
    def test_mgdl_per_mmol_factor(self):
        # Synthesis §2.6: 18.02 (not 18.0); derived from glucose
        # molecular weight 180.16/10. Match Reporter + AAPS conventions.
        assert MGDL_PER_MMOL == 18.02

    def test_sgv_gap_bounds(self):
        assert SGV_MIN_VALID == 20
        assert SGV_MAX_VALID == 1000


# ---------------------------------------------------------------------------
# Uploader detection
# ---------------------------------------------------------------------------


class TestUploaderDetection:
    def test_loop_via_device_uri(self):
        assert detect_uploader(None, "loop://iPhone") == "loop"

    def test_loop_via_entered_by(self):
        assert detect_uploader("Loop", None) == "loop"
        assert detect_uploader("Loop (via remote command)", None) == "loop"

    def test_aaps_via_entered_by_androidaps_substring(self):
        assert detect_uploader("openaps://AndroidAPS", None) == "aaps"
        assert detect_uploader("AndroidAPS", None) == "aaps"

    def test_trio(self):
        assert detect_uploader("Trio", None) == "trio"
        assert detect_uploader(None, "Trio") == "trio"

    def test_oref0_via_openaps_device_uri(self):
        # Distinguished from AAPS by presence of host segment after `openaps://`
        assert detect_uploader(None, "openaps://my-rig/medtronic-722") == "oref0"

    def test_oref0_profile_switch_uses_bare_openaps_string(self):
        assert detect_uploader("OpenAPS", None) == "oref0"

    def test_xdrip_plus_lowercase(self):
        # xDrip+ Android: `enteredBy: "xdrip"` (lowercase)
        assert detect_uploader("xdrip", None) == "xdrip+"
        assert detect_uploader(None, "xDrip-DexcomG6") == "xdrip+"

    def test_xdrip4ios_camelcase(self):
        # xDrip4iOS: `enteredBy: "xDrip4iOS"` (camelCase) -- distinct
        # from xDrip+ Android. Substring match wins over prefix match.
        assert detect_uploader("xDrip4iOS", None) == "xdrip4ios"

    def test_unknown(self):
        assert detect_uploader("test-user", None) == "unknown"
        assert detect_uploader(None, None) == "unknown"


class TestOpenapsUriParsing:
    def test_full_uri(self):
        host, ref = parse_openaps_uri("openaps://my-rig/medtronic-722")
        assert host == "my-rig"
        assert ref == "medtronic-722"

    def test_aaps_degenerate_one_segment(self):
        # AAPS uses `openaps://AndroidAPS` -- one segment, no host
        host, ref = parse_openaps_uri("openaps://AndroidAPS")
        assert host is None
        assert ref == "AndroidAPS"

    def test_non_openaps(self):
        host, ref = parse_openaps_uri("loop://iPhone")
        assert host is None
        assert ref is None

    def test_none(self):
        assert parse_openaps_uri(None) == (None, None)


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------


class TestEntriesXdripSgv:
    @pytest.fixture
    def fixture(self) -> NightscoutEntry:
        return NightscoutEntry.model_validate(_load("entries", "xdrip_sgv"))

    def test_basic_fields(self, fixture):
        assert fixture.type == "sgv"
        assert fixture.sgv == 120
        assert fixture.direction == "Flat"
        assert fixture.device == "xDrip-DexcomG6"

    def test_xdrip_specific_fields(self, fixture):
        # Per synthesis §1.7: rssi 100 is hardcoded, filtered/unfiltered
        # scaled by 1000.
        assert fixture.rssi == 100
        assert fixture.filtered == 119870
        assert fixture.unfiltered == 120130
        assert fixture.delta == 0.5

    def test_not_a_glucose_gap(self, fixture):
        assert fixture.is_glucose_gap is False

    def test_not_a_fingerstick(self, fixture):
        # Entries-route fingerstick is type=mbg, not sgv.
        assert fixture.is_fingerstick is False

    def test_canonical_timestamp(self, fixture):
        # `date` (epoch ms) is canonical for entries; `dateString` mirrors.
        ts = fixture.canonical_timestamp
        assert ts is not None
        assert ts == datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)


class TestEntriesDexcomBridgeSgv:
    @pytest.fixture
    def fixture(self) -> NightscoutEntry:
        return NightscoutEntry.model_validate(_load("entries", "dexcom_bridge_sgv"))

    def test_lean_shape_no_raw_fields(self, fixture):
        # Catches code that assumes raw fields (filtered/unfiltered/rssi)
        # are always present.
        assert fixture.filtered is None
        assert fixture.unfiltered is None
        assert fixture.rssi is None
        assert fixture.delta is None

    def test_basic_fields(self, fixture):
        assert fixture.type == "sgv"
        assert fixture.sgv == 125
        assert fixture.direction == "FortyFiveUp"


class TestEntriesXdripMbgFingerstick:
    @pytest.fixture
    def fixture(self) -> NightscoutEntry:
        return NightscoutEntry.model_validate(_load("entries", "xdrip_mbg_fingerstick"))

    def test_is_fingerstick_via_mbg_type(self, fixture):
        # Synthesis §1.8: dual-path fingerstick. Entries route is mbg.
        assert fixture.type == "mbg"
        assert fixture.is_fingerstick is True
        assert fixture.mbg == 110
        assert fixture.sgv is None


class TestEntriesCalCalibration:
    @pytest.fixture
    def fixture(self) -> NightscoutEntry:
        return NightscoutEntry.model_validate(_load("entries", "cal_calibration"))

    def test_cal_type_with_required_fields(self, fixture):
        assert fixture.type == "cal"
        assert fixture.slope == 1000
        assert fixture.intercept == 10000
        # Per Ben's openaps/nightscout-formats: scale defaults to 1.
        assert fixture.scale == 1

    def test_not_a_glucose_gap(self, fixture):
        # Gap rule only applies to sgv-type entries.
        assert fixture.is_glucose_gap is False


# ---------------------------------------------------------------------------
# Treatments -- the 5 SMB encodings (synthesis §1.1)
# ---------------------------------------------------------------------------


class TestSmbDetection:
    """All 5 SMB encodings must route to is_smb=True."""

    def _load_treatment(self, name: str) -> NightscoutTreatment:
        return NightscoutTreatment.model_validate(_load("treatments", name))

    def test_loop_smb_via_automatic_flag(self):
        t = self._load_treatment("loop_correction_bolus")
        assert t.event_type == "Correction Bolus"
        assert t.automatic is True
        assert t.is_smb is True
        assert t.semantic_kind == "bolus"
        # Loop SMB has no `_id` (Loop omits on POST per syncIdentifier dedup)
        assert t.id is None
        assert t.sync_identifier is not None

    def test_aaps_v1_smb_via_is_smb_field(self):
        t = self._load_treatment("aaps_v1_smb_correction_bolus")
        assert t.event_type == "Correction Bolus"
        assert t.type == "SMB"
        assert t.is_smb_flag is True  # V1 writes `isSMB`
        assert t.is_basal_insulin is None  # V1 does NOT write `isBasalInsulin`
        assert t.is_smb is True
        assert t.pump_id == 4102
        assert t.pump_serial == "33013206"

    def test_aaps_v3_smb_via_type_field_only(self):
        t = self._load_treatment("aaps_v3_smb_correction_bolus")
        # V3 writes `type: "SMB"` but NOT `isSMB` (per §10.V1 verification)
        assert t.event_type == "Correction Bolus"
        assert t.type == "SMB"
        assert t.is_smb_flag is None  # V3 omits isSMB
        assert t.is_basal_insulin is False  # V3 writes isBasalInsulin instead
        assert t.is_smb is True
        # V3 envelope fields
        assert t.identifier is not None
        assert t.app == "AAPS"
        assert t.srv_created is not None


# ---------------------------------------------------------------------------
# Treatments -- carb routing (synthesis §1.2)
# ---------------------------------------------------------------------------


class TestCarbRouting:
    def _load_treatment(self, name: str) -> NightscoutTreatment:
        return NightscoutTreatment.model_validate(_load("treatments", name))

    def test_loop_carb_correction_uses_identifier_not_syncidentifier(self):
        t = self._load_treatment("loop_carb_correction")
        # Per-eventType field-name distinction: Loop carbs use
        # `identifier`, boluses use `syncIdentifier`.
        assert t.event_type == "Carb Correction"
        assert t.identifier is not None
        assert t.sync_identifier is None
        assert t.carbs == 42
        assert t.insulin is None
        assert t.semantic_kind == "carb_entry"

    def test_aaps_meal_bolus_with_carbs_only(self):
        t = self._load_treatment("aaps_meal_bolus_carbs_only")
        # AAPS ≥12g carbs: eventType="Meal Bolus" with NO insulin field.
        # Translator must route by field presence.
        assert t.event_type == "Meal Bolus"
        assert t.carbs == 30
        assert t.insulin is None
        assert t.semantic_kind == "carb_entry"

    def test_xdrip_empty_eventtype_with_carbs(self):
        t = self._load_treatment("xdrip_empty_eventtype_with_carbs")
        # Per synthesis §1.2 4th carb shape: empty eventType + carbs
        # field. Don't crash on empty/None eventType.
        assert t.event_type == ""
        assert t.carbs == 30
        assert t.semantic_kind == "carb_entry"
        # xDrip+ also carries a separate `uuid` field (distinct from `_id`)
        assert t.uuid is not None

    def test_careportal_meal_bolus_pair(self):
        t = self._load_treatment("careportal_meal_bolus")
        # Both carbs AND insulin populated -- meal+bolus pair, will
        # split into 2 internal rows in the ORM mapping (PR2).
        assert t.has_carbs is True
        assert t.has_insulin is True
        assert t.semantic_kind == "meal_bolus_pair"


# ---------------------------------------------------------------------------
# Treatments -- temp basal subtypes (synthesis §1.3)
# ---------------------------------------------------------------------------


class TestTempBasalRouting:
    def test_normal_temp_basal(self):
        t = NightscoutTreatment.model_validate(
            _load("treatments", "careportal_temp_basal")
        )
        assert t.event_type == "Temp Basal"
        assert t.rate == 0.8
        assert t.duration == 30
        assert t.is_temp_basal_suspend is False
        assert t.is_temp_basal_cancel is False
        assert t.semantic_kind == "temp_basal"

    def test_synthetic_pump_suspend(self):
        # rate=0 + duration>=30 = suspend
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Temp Basal",
                "rate": 0,
                "absolute": 0,
                "duration": 30,
                "reason": "suspend",
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.is_temp_basal_suspend is True
        assert t.is_temp_basal_cancel is False
        assert t.semantic_kind == "temp_basal_suspend"

    def test_synthetic_cancel_temp_not_suspend(self):
        # rate=0 + duration=0 = cancel signal, NOT suspend (synthesis §1.3 trap)
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Temp Basal",
                "rate": 0,
                "duration": 0,
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.is_temp_basal_suspend is False
        assert t.is_temp_basal_cancel is True
        assert t.semantic_kind == "temp_basal_cancel"


# ---------------------------------------------------------------------------
# Treatments -- override / temp target (synthesis §1.4)
# ---------------------------------------------------------------------------


class TestOverrideRouting:
    def test_careportal_temporary_target(self):
        t = NightscoutTreatment.model_validate(
            _load("treatments", "careportal_temporary_target")
        )
        assert t.event_type == "Temporary Target"
        assert t.target_top == 90
        assert t.target_bottom == 80
        assert t.duration == 60
        assert t.semantic_kind == "temp_target"

    def test_synthetic_loop_temporary_override(self):
        # Loop override: duration in MINUTES on the wire (verified
        # §10.V2: NightscoutKit converts seconds->minutes at encode time).
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Temporary Override",
                "enteredBy": "Loop",
                "reason": "Workout",
                "duration": 60,
                "correctionRange": [140, 160],
                "insulinNeedsScaleFactor": 0.5,
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.semantic_kind == "override"
        assert t.uploader == "loop"
        assert t.correction_range == [140, 160]
        assert t.insulin_needs_scale_factor == 0.5

    def test_synthetic_trio_exercise_override(self):
        # Trio override toggle uploads as eventType="Exercise"
        # (verified §10.V3 against current Trio main).
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Exercise",
                "enteredBy": "Trio",
                "duration": 60,
                "notes": "Workout preset",
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.uploader == "trio"
        assert t.semantic_kind == "override"  # NOT exercise_log
        # Per synthesis §1.4: Trio loses target/percentage info on the wire;
        # only duration + notes survive.
        assert t.duration == 60
        assert t.notes == "Workout preset"

    def test_synthetic_trio_indefinite_override(self):
        # Trio uploads indefinite overrides as duration=43200 (30 days).
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Exercise",
                "enteredBy": "Trio",
                "duration": 43200,
                "notes": "Eating Soon",
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.is_indefinite_trio_override is True


# ---------------------------------------------------------------------------
# Treatments -- profile switch (synthesis §1.6)
# ---------------------------------------------------------------------------


class TestProfileSwitchRouting:
    def test_canonical_profile_switch(self):
        t = NightscoutTreatment.model_validate(
            _load("treatments", "careportal_profile_switch")
        )
        assert t.event_type == "Profile Switch"
        assert t.profile == "Default"
        assert t.original_profile_name == "Default"
        assert t.percentage == 100
        assert t.semantic_kind == "profile_switch"

    def test_aaps_profile_switch_percentage_adjustment(self):
        t = NightscoutTreatment.model_validate(
            _load("treatments", "aaps_profile_switch_percentage")
        )
        # Per synthesis §1.6: a 110% override is semantically distinct
        # from a true switch. Translator must preserve the full tuple.
        assert t.percentage == 110
        assert t.original_profile_name == "MyProfile"
        assert t.profile_json is not None  # stringified embedded snapshot
        assert t.duration == 120
        assert t.original_duration == 7200000
        assert t.semantic_kind == "profile_switch"

    def test_synthetic_aaps_effective_profile_switch_as_note(self):
        # AAPS gotcha (synthesis §1.6 trailing): EPS arrives as
        # eventType="Note" with originalProfileName as telltale.
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Note",
                "notes": "MyProfile (80%, 2h)",
                "originalProfileName": "MyProfile",
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.is_effective_profile_switch_note is True
        assert t.semantic_kind == "effective_profile_switch"


# ---------------------------------------------------------------------------
# Treatments -- fingerstick dual-path (synthesis §1.8)
# ---------------------------------------------------------------------------


class TestFingerstickDualPath:
    def test_xdrip4ios_bg_check_treatment(self):
        # Synthesis §1.8: same logical event as xdrip_mbg_fingerstick
        # entry, but in treatments collection.
        t = NightscoutTreatment.model_validate(
            _load("treatments", "xdrip4ios_bg_check_treatment")
        )
        assert t.event_type == "BG Check"
        assert t.glucose == 120
        assert t.glucose_type == "Finger"
        assert t.units == "mg/dl"
        assert t.is_fingerstick_treatment is True
        assert t.semantic_kind == "fingerstick_bg_check"
        # xDrip4iOS uses camelCase enteredBy
        assert t.entered_by == "xDrip4iOS"
        assert t.uploader == "xdrip4ios"

    def test_synthetic_glucose_type_finger_alone_is_enough(self):
        # Either signal (eventType OR glucoseType) confirms fingerstick.
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Note",
                "glucose": 130,
                "glucoseType": "Finger",
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.is_fingerstick_treatment is True
        assert t.semantic_kind == "fingerstick_bg_check"


# ---------------------------------------------------------------------------
# DeviceStatus
# ---------------------------------------------------------------------------


class TestDeviceStatusLoop:
    @pytest.fixture
    def fixture(self) -> NightscoutDeviceStatus:
        return NightscoutDeviceStatus.model_validate(
            _load("devicestatus", "loop_devicestatus")
        )

    def test_uploader_via_loop_uri(self, fixture):
        assert fixture.device == "loop://iPhone"
        assert fixture.uploader_name == "loop"

    def test_iob_extracted_from_loop_subtree(self, fixture):
        # Synthesis §7.3: pump.iob is always nil for Loop; only loop.iob
        # is populated. Translator IOB priority: loop.iob first.
        assert fixture.iob_value == 1.2

    def test_pump_iob_is_explicitly_null(self, fixture):
        # Locks the Loop quirk -- ensures parser doesn't fall back to
        # an absent pump.iob field.
        assert fixture.pump is not None
        assert fixture.pump.get("iob") is None

    def test_loop_failure_reason_absent_when_enacted_present(self, fixture):
        # loop.failureReason and loop.enacted are mutually exclusive
        # at the source.
        assert fixture.loop_failure_reason is None

    def test_pump_battery_extraction(self, fixture):
        assert fixture.pump_battery_percent == 87


class TestDeviceStatusAaps:
    @pytest.fixture
    def fixture(self) -> NightscoutDeviceStatus:
        return NightscoutDeviceStatus.model_validate(
            _load("devicestatus", "aaps_devicestatus")
        )

    def test_v1_quirk_top_level_uploader_battery_int(self, fixture):
        # AAPS V1: emits uploaderBattery (top-level int) AND
        # nested uploader.battery. Both should be accessible.
        assert fixture.uploader_battery == 92
        assert fixture.uploader is not None
        assert fixture.uploader["battery"] == 92

    def test_iob_via_openaps_subtree(self, fixture):
        # AAPS populates pump.iob AND openaps.iob. Our priority is
        # loop.iob (absent here) -> pump.iob (also absent) -> openaps.iob.
        # The fixture only has openaps.iob, so we should fall through.
        assert fixture.iob_value == 1.234

    def test_pump_extended_freeform_blob_preserved(self, fixture):
        # pump.extended is driver-specific; preserve verbatim.
        assert fixture.pump is not None
        ext = fixture.pump.get("extended")
        assert ext is not None
        assert ext["Version"] == "AAPS-3.2.0"
        assert ext["BaseBasalRate"] == 0.85


class TestDeviceStatusOref0:
    @pytest.fixture
    def fixture(self) -> NightscoutDeviceStatus:
        return NightscoutDeviceStatus.model_validate(
            _load("devicestatus", "oref0_devicestatus_with_predbgs")
        )

    def test_predbgs_all_four_arrays(self, fixture):
        # oref0 emits all four predBGs arrays when conditions allow.
        suggested = fixture.openaps["suggested"]
        predbgs = suggested["predBGs"]
        assert "IOB" in predbgs
        assert "ZT" in predbgs
        assert "COB" in predbgs
        assert "UAM" in predbgs
        # Always integer mg/dL even on mmol profiles (synthesis §2.5)
        assert all(isinstance(v, int) for v in predbgs["IOB"])

    def test_tick_signed_string(self, fixture):
        # oref0 `tick` is a signed string ("-1", "+5"), not a number.
        suggested = fixture.openaps["suggested"]
        assert suggested["tick"] == "-1"
        assert isinstance(suggested["tick"], str)

    def test_reservoir_null_accepted(self, fixture):
        # oref0 may emit reservoir: null -- don't crash.
        assert fixture.pump_reservoir is None

    def test_structured_openaps_uri(self, fixture):
        # device: "openaps://my-rig/medtronic-722" parses into rig + ref
        host, ref = parse_openaps_uri(fixture.device)
        assert host == "my-rig"
        assert ref == "medtronic-722"
        assert fixture.uploader_name == "oref0"


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


class TestProfile:
    @pytest.fixture
    def fixture(self) -> NightscoutProfile:
        return NightscoutProfile.model_validate(_load("profile", "multi_store_profile"))

    def test_default_profile_indirection(self, fixture):
        assert fixture.default_profile == "Default"
        active = fixture.active_profile()
        assert active is not None
        assert active.dia == 5

    def test_multi_store(self, fixture):
        assert "Default" in fixture.store
        assert "Exercise" in fixture.store
        # Exercise profile has higher target range (130-150)
        ex = fixture.store["Exercise"]
        assert ex.target_low[0]["value"] == 130
        assert ex.target_high[0]["value"] == 150

    def test_first_entry_not_at_midnight_forces_wrap(self, fixture):
        # Synthesis §7.4: profile parser must handle midnight wrap
        # when first entry isn't at 00:00.
        default = fixture.active_profile()
        first_basal = default.basal[0]
        assert first_basal["time"] == "06:00"
        # Translator's profile-time parser (PR2) needs to know the last
        # entry's value wraps back to 00:00 -> 06:00. We don't compute
        # that here; the fixture exercises the input shape.

    def test_canonical_timestamp_is_startdate(self, fixture):
        # Profile timestamp is `startDate`, NOT `created_at` or `date`.
        ts = fixture.canonical_timestamp
        assert ts is not None
        assert ts == datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Glucose-gap filter (synthesis §2.6)
# ---------------------------------------------------------------------------


class TestGlucoseGapFilter:
    def test_low_value_is_gap(self):
        e = NightscoutEntry.model_validate(
            {
                "type": "sgv",
                "sgv": 5,
                "date": 1778421600000,
                "dateString": "2026-05-06T12:00:00Z",
            }
        )
        assert e.is_glucose_gap is True

    def test_high_value_is_gap(self):
        e = NightscoutEntry.model_validate(
            {
                "type": "sgv",
                "sgv": 1100,
                "date": 1778421600000,
                "dateString": "2026-05-06T12:00:00Z",
            }
        )
        assert e.is_glucose_gap is True

    def test_zero_is_gap_locks_against_corruption(self):
        e = NightscoutEntry.model_validate(
            {
                "type": "sgv",
                "sgv": 0,
                "date": 1778421600000,
                "dateString": "2026-05-06T12:00:00Z",
            }
        )
        assert e.is_glucose_gap is True

    def test_normal_value_not_gap(self):
        e = NightscoutEntry.model_validate(
            {
                "type": "sgv",
                "sgv": 120,
                "date": 1778421600000,
                "dateString": "2026-05-06T12:00:00Z",
            }
        )
        assert e.is_glucose_gap is False


# ---------------------------------------------------------------------------
# Direction enum (synthesis §2.2)
# ---------------------------------------------------------------------------


class TestDirectionNormalization:
    def test_canonical_spaced_form_passes_through(self):
        e = NightscoutEntry.model_validate(
            {
                "type": "sgv",
                "sgv": 120,
                "date": 1778421600000,
                "direction": "NOT COMPUTABLE",
            }
        )
        assert e.direction == "NOT COMPUTABLE"

    def test_underscore_form_normalized_to_spaced(self):
        e = NightscoutEntry.model_validate(
            {
                "type": "sgv",
                "sgv": 120,
                "date": 1778421600000,
                "direction": "NOT_COMPUTABLE",
            }
        )
        assert e.direction == "NOT COMPUTABLE"

    def test_trio_tripleup_passes_through_for_defensive_parse(self):
        # Trio extends the canonical enum with TripleUp/TripleDown.
        # Defensive parser accepts; translator may coerce later.
        e = NightscoutEntry.model_validate(
            {
                "type": "sgv",
                "sgv": 220,
                "date": 1778421600000,
                "direction": "TripleUp",
            }
        )
        assert e.direction == "TripleUp"


# ---------------------------------------------------------------------------
# Care Portal numeric-string coercion
# ---------------------------------------------------------------------------


class TestCareportalStringCoercion:
    def test_carbs_as_string(self):
        # Care Portal sends numbers as strings; server coerces, but
        # uploaders bypassing server may keep strings.
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Carb Correction",
                "carbs": "30",
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.carbs == 30.0
        assert t.semantic_kind == "carb_entry"

    def test_invalid_numeric_string_is_none(self):
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Carb Correction",
                "carbs": "not-a-number",
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.carbs is None

    def test_empty_string_microbolus_does_not_reject_record(self):
        # Care Portal numeric coercion covers microbolus too -- empty
        # string must not raise ValidationError.
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Bolus",
                "insulin": 5,
                "microbolus": "",
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.insulin == 5
        assert t.microbolus is None


# ---------------------------------------------------------------------------
# Adversarial regression tests -- each test pins a specific defect that
# was caught in the PR1 adversarial review pass.
# ---------------------------------------------------------------------------


class TestAdversarialRegressions:
    """Tests that lock specific findings from the adversarial review.

    Each test pins a defect that was fixed during PR1 review:
    H1-H6 (HIGH), M1-M9 (MEDIUM), and selected LOW findings.
    """

    # H1: AAPS V1 device-only path was misclassified as oref0
    def test_h1_aaps_devicestatus_classified_as_aaps_not_oref0(self):
        # device: "openaps://samsung SM-G970F" with empty enteredBy --
        # was returning "oref0" before fix. Now must return "aaps".
        assert detect_uploader(None, "openaps://samsung SM-G970F") == "aaps"
        assert detect_uploader(None, "openaps://AndroidAPS") == "aaps"
        # oref0 still wins when there's a host segment
        assert detect_uploader(None, "openaps://my-rig/medtronic-722") == "oref0"

    def test_h1_aaps_devicestatus_fixture_uploader_detection(self):
        # Lock against the exact aaps_devicestatus.json fixture
        ds = NightscoutDeviceStatus.model_validate(
            _load("devicestatus", "aaps_devicestatus")
        )
        assert ds.uploader_name == "aaps"

    # H2: is_smb returned True for microbolus=0
    def test_h2_microbolus_zero_does_not_classify_as_smb(self):
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Bolus",
                "insulin": 5,
                "microbolus": 0,
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.is_smb is False

    def test_h2_positive_microbolus_still_classifies_as_smb(self):
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Bolus",
                "insulin": 0.2,
                "microbolus": 0.1,
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.is_smb is True

    # H3: Loop fixtures were placing the URI in enteredBy
    def test_h3_loop_correction_bolus_fixture_uploader_is_loop(self):
        t = NightscoutTreatment.model_validate(
            _load("treatments", "loop_correction_bolus")
        )
        assert t.uploader == "loop"
        assert t.entered_by == "Loop"
        assert t.device == "loop://iPhone"

    def test_h3_loop_carb_correction_fixture_uploader_is_loop(self):
        t = NightscoutTreatment.model_validate(
            _load("treatments", "loop_carb_correction")
        )
        assert t.uploader == "loop"

    # H4: is_temp_basal_suspend ignored percent-mode TBR
    def test_h4_percent_minus_100_with_duration_30_is_suspend(self):
        # AAPS percent-mode 0% basal with non-trivial duration
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Temp Basal",
                "percent": -100,
                "duration": 30,
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.is_temp_basal_suspend is True
        assert t.semantic_kind == "temp_basal_suspend"

    def test_h4_percent_minus_100_with_duration_0_is_cancel(self):
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Temp Basal",
                "percent": -100,
                "duration": 0,
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.is_temp_basal_cancel is True
        assert t.semantic_kind == "temp_basal_cancel"

    def test_h4_percent_minus_50_is_not_suspend(self):
        # 50% basal is a real temp, not a suspend.
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Temp Basal",
                "percent": -50,
                "duration": 30,
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.is_temp_basal_suspend is False
        assert t.semantic_kind == "temp_basal"

    # H5: extendedEmulated on a Note made it a combo bolus
    def test_h5_note_with_extended_emulated_is_not_combo_bolus(self):
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Note",
                "notes": "stray field",
                "extendedEmulated": {"some": "data"},
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.is_combo_bolus is False
        # Lands as a note (eventType match), no field-presence override
        assert t.semantic_kind == "note"

    def test_h5_temp_basal_with_empty_extended_emulated_is_not_combo_bolus(self):
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Temp Basal",
                "rate": 0.6,
                "duration": 30,
                "extendedEmulated": {},
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.is_combo_bolus is False
        assert t.semantic_kind == "temp_basal"

    def test_h5_temp_basal_with_emulated_bolus_data_is_combo_bolus(self):
        # Real AAPS extended-bolus-emulating-TBR shape
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Temp Basal",
                "rate": 0.6,
                "duration": 30,
                "extendedEmulated": {
                    "eventType": "Combo Bolus",
                    "enteredinsulin": 1.5,
                    "duration": 30,
                    "isEmulatingTempBasal": True,
                },
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.is_combo_bolus is True
        assert t.semantic_kind == "combo_bolus"

    # H6: device events were eaten by carb/bolus routing
    def test_h6_site_change_with_carbs_field_is_still_device_event(self):
        # A Care Portal Site Change with an incidental carbs field
        # must NOT route to carb_entry.
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Site Change",
                "carbs": 30,
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.semantic_kind == "device_event"

    def test_h6_sensor_start_with_glucose_is_not_fingerstick(self):
        # Sensor Start with a glucose field would be unusual but
        # possible. eventType wins over field-presence for device
        # events (which would be considered "fingerstick" via glucose
        # field by the field-presence rule otherwise).
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Sensor Start",
                "transmitterId": "ABCDEF",
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.semantic_kind == "device_event"

    def test_h6_announcement_with_insulin_field_is_announcement(self):
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Announcement",
                "notes": "alert",
                "insulin": 1.0,
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.semantic_kind == "announcement"

    # M1: extend numeric coercion to all numeric fields
    def test_m1_glucose_string_coerces(self):
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "BG Check",
                "glucose": "120",
                "glucoseType": "Finger",
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.glucose == 120.0

    def test_m1_target_top_string_coerces(self):
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Temporary Target",
                "targetTop": "90",
                "targetBottom": "80",
                "duration": "60",
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.target_top == 90.0
        assert t.target_bottom == 80.0

    # M3: bool was slipping through numeric coercion
    def test_m3_bool_iob_does_not_coerce_to_one(self):
        ds = NightscoutDeviceStatus.model_validate(
            {
                "device": "test",
                "pump": {"iob": True},
                "loop": None,
                "openaps": None,
            }
        )
        assert ds.iob_value is None

    def test_m3_bool_insulin_does_not_coerce_to_one(self):
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Bolus",
                "insulin": True,
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.insulin is None

    # M2: pump_battery_percent now accepts floats
    def test_m2_pump_battery_percent_accepts_float(self):
        ds = NightscoutDeviceStatus.model_validate(
            {
                "device": "test",
                "pump": {"battery": {"percent": 87.0}},
            }
        )
        assert ds.pump_battery_percent == 87

    # M4: numeric-string in dateString now falls through to epoch parse
    def test_m4_numeric_string_in_datestring_parses_as_epoch(self):
        e = NightscoutEntry.model_validate(
            {
                "type": "sgv",
                "sgv": 120,
                "dateString": "1778068800000",
            }
        )
        assert e.canonical_timestamp == datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)

    # M5: SMB type field now whitespace-tolerant
    def test_m5_type_smb_with_whitespace_still_classifies_as_smb(self):
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Correction Bolus",
                "insulin": 0.3,
                "type": "  SMB  ",
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.is_smb is True

    # M6: profileJson now accepts dict
    def test_m6_profile_json_accepts_dict_without_crashing(self):
        # An uploader that emits the snapshot as a dict instead of
        # stringified JSON should not reject the whole record.
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Profile Switch",
                "profile": "MyProfile",
                "originalProfileName": "MyProfile",
                "profileJson": {"dia": 5, "units": "mg/dl"},
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.profile_json == {"dia": 5, "units": "mg/dl"}
        assert t.semantic_kind == "profile_switch"

    # M9: declared device/date/timestamp/mills as fields
    def test_m9_device_field_declared_on_treatment(self):
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Meal Bolus",
                "carbs": 30,
                "device": "loop://iPhone",
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.device == "loop://iPhone"
        assert t.uploader == "loop"

    def test_m9_canonical_timestamp_falls_back_through_chain(self):
        # No created_at, but date (epoch ms) is present
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "Bolus",
                "insulin": 1,
                "date": 1778068800000,
            }
        )
        assert t.canonical_timestamp == datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)

    # External insulin (was missing from L11)
    def test_l11_external_insulin_eventtype_routed_correctly(self):
        t = NightscoutTreatment.model_validate(
            {
                "eventType": "External Insulin",
                "insulin": 2,
                "enteredBy": "Trio",
                "created_at": "2026-05-06T15:00:00Z",
            }
        )
        assert t.is_external_insulin is True
        # The bolus eventType field-presence routing still applies
        assert t.semantic_kind == "bolus"


# ---------------------------------------------------------------------------
# Fixture invariants -- meta-finding from the adversarial review
# ---------------------------------------------------------------------------


class TestFixtureInvariants:
    """Invariants that every Tier-1 fixture must satisfy.

    Adversarial-review meta-finding: H3 was undetected because the
    test suite never asserted `t.uploader != "unknown"`. Locking that
    invariant here so any future fixture that fails uploader detection
    trips immediately.
    """

    UPLOADER_BY_FIXTURE_NAME: dict[str, str] = {
        "xdrip_sgv.json": "xdrip+",
        "dexcom_bridge_sgv.json": "unknown",  # bridge, no uploader signature
        "xdrip_mbg_fingerstick.json": "xdrip+",
        "cal_calibration.json": "oref0",
        "careportal_meal_bolus.json": "unknown",  # care portal: no signature
        "careportal_temp_basal.json": "unknown",
        "careportal_profile_switch.json": "unknown",
        "careportal_temporary_target.json": "unknown",
        "loop_correction_bolus.json": "loop",
        "loop_carb_correction.json": "loop",
        "aaps_v1_smb_correction_bolus.json": "aaps",
        "aaps_v3_smb_correction_bolus.json": "aaps",
        "aaps_meal_bolus_carbs_only.json": "aaps",
        "aaps_profile_switch_percentage.json": "aaps",
        "xdrip_empty_eventtype_with_carbs.json": "xdrip+",
        "xdrip4ios_bg_check_treatment.json": "xdrip4ios",
        # devicestatus fixtures
        "loop_devicestatus.json": "loop",
        "aaps_devicestatus.json": "aaps",
        "oref0_devicestatus_with_predbgs.json": "oref0",
    }

    def test_treatment_fixtures_route_to_known_semantic_kinds(self):
        """Every treatment fixture should produce a non-'unknown' semantic_kind.

        If a fixture lands on 'unknown', either the model is missing
        a routing branch OR the fixture is malformed.
        """
        treatments_dir = FIXTURE_ROOT / "treatments"
        for path in sorted(treatments_dir.glob("*.json")):
            data = json.loads(path.read_text())
            t = NightscoutTreatment.model_validate(data)
            assert t.semantic_kind != "unknown", (
                f"{path.name} → semantic_kind='unknown' "
                f"(eventType={data.get('eventType')!r})"
            )

    def test_treatment_fixture_uploader_detections(self):
        """Lock the expected uploader for each treatment fixture.

        Catches regressions like H3 (where Loop fixtures used the wrong
        field for the URI and silently misdetected as 'unknown').
        """
        treatments_dir = FIXTURE_ROOT / "treatments"
        for path in sorted(treatments_dir.glob("*.json")):
            expected = self.UPLOADER_BY_FIXTURE_NAME.get(path.name)
            if expected is None:
                pytest.fail(f"Fixture {path.name} not in expected-uploader table")
            data = json.loads(path.read_text())
            t = NightscoutTreatment.model_validate(data)
            assert t.uploader == expected, (
                f"{path.name} → uploader={t.uploader!r}, expected {expected!r}"
            )

    def test_devicestatus_fixture_uploader_detections(self):
        ds_dir = FIXTURE_ROOT / "devicestatus"
        for path in sorted(ds_dir.glob("*.json")):
            expected = self.UPLOADER_BY_FIXTURE_NAME.get(path.name)
            if expected is None:
                pytest.fail(f"Fixture {path.name} not in expected-uploader table")
            data = json.loads(path.read_text())
            ds = NightscoutDeviceStatus.model_validate(data)
            assert ds.uploader_name == expected, (
                f"{path.name} → uploader={ds.uploader_name!r}, expected {expected!r}"
            )

    def test_all_fixtures_parse_as_valid_models(self):
        """No fixture should raise a ValidationError. AC6 of Story 43.3."""
        for category, model in (
            ("entries", NightscoutEntry),
            ("treatments", NightscoutTreatment),
            ("devicestatus", NightscoutDeviceStatus),
            ("profile", NightscoutProfile),
        ):
            cat_dir = FIXTURE_ROOT / category
            for path in sorted(cat_dir.glob("*.json")):
                data = json.loads(path.read_text())
                # Should not raise
                model.model_validate(data)
