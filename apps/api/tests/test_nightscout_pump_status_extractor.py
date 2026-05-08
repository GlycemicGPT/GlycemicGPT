"""Tests for the BATTERY/RESERVOIR/BASAL extractor and the multi-row
INSERT shape normalizer in the Nightscout translator.

Two pieces under test:

1. `extract_pump_events_from_devicestatuses` -- pure function, no DB.
   Given a list of NightscoutDeviceStatus + a `last_state` dict,
   returns the list of pump_event row dicts to insert. Tests cover
   value-change dedupe, the 1-min min-interval guard, multi-field
   extraction (battery + reservoir + basal from one devicestatus),
   `iob_at_event` annotation on BATTERY rows, missing fields, and
   in-batch state propagation.

2. `_normalize_row_shapes` -- pure function, fixes the SQLAlchemy
   2.x multi-row INSERT bug where bolus rows lack `duration_minutes`
   while temp-basal rows have it. Tests cover key-padding and
   default-value preservation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

# Importing NightscoutSyncStatus eagerly registers the SQLAlchemy
# mapper for NightscoutConnection, which `_base_event` and `_map_bolus`
# need at construction time. Without this module-level import, running
# the regression-class tests in isolation (e.g. via -k filters) raises
# an InvalidRequestError because the mapper hasn't been configured.
from src.models.nightscout_connection import NightscoutSyncStatus  # noqa: F401
from src.models.pump_data import PumpEventType
from src.services.integrations.nightscout._pump_status_extractor import (
    _MIN_INTERVAL_SECONDS,
    extract_pump_events_from_devicestatuses,
)
from src.services.integrations.nightscout.models import NightscoutDeviceStatus
from src.services.integrations.nightscout.translator import _normalize_row_shapes


def _make_ds(
    *,
    ds_id: str,
    when: datetime,
    battery: int | None = None,
    reservoir: float | None = None,
    enacted_rate: float | None = None,
    iob: float | None = None,
    cob: float | None = None,
    is_charging: bool | None = None,
) -> NightscoutDeviceStatus:
    """Build a minimal NightscoutDeviceStatus in the shape of Loop's
    devicestatus payload. Only the fields tests need are populated."""
    raw = {
        "_id": ds_id,
        "device": "loop://iPhone",
        "created_at": when.isoformat().replace("+00:00", "Z"),
    }
    pump: dict = {}
    if battery is not None:
        pump["battery"] = {"percent": battery}
    if reservoir is not None:
        pump["reservoir"] = reservoir
    if pump:
        raw["pump"] = pump
    loop_subtree: dict = {}
    if iob is not None:
        loop_subtree["iob"] = {"iob": iob, "timestamp": raw["created_at"]}
    if cob is not None:
        loop_subtree["cob"] = {"cob": cob, "timestamp": raw["created_at"]}
    if enacted_rate is not None:
        loop_subtree["enacted"] = {
            "rate": enacted_rate,
            "duration": 30,
            "timestamp": raw["created_at"],
        }
    if loop_subtree:
        raw["loop"] = loop_subtree
    if is_charging is not None:
        raw["isCharging"] = is_charging
    return NightscoutDeviceStatus.model_validate(raw)


# ---------------------------------------------------------------------------
# extract_pump_events_from_devicestatuses
# ---------------------------------------------------------------------------


class TestExtractor:
    def test_first_devicestatus_emits_all_three_when_state_empty(self):
        ds = _make_ds(
            ds_id="ds1",
            when=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            battery=80,
            reservoir=145.5,
            enacted_rate=0.8,
            iob=2.3,
            cob=15.0,
        )
        rows = extract_pump_events_from_devicestatuses(
            [ds],
            user_id="u1",
            source="nightscout:c1",
            last_state={},
        )
        kinds = [(r["event_type"], r["units"]) for r in rows]
        assert (PumpEventType.BATTERY, 80.0) in kinds
        assert (PumpEventType.RESERVOIR, 145.5) in kinds
        assert (PumpEventType.BASAL, 0.8) in kinds

    def test_battery_row_carries_iob_and_cob_anchor(self):
        ds = _make_ds(
            ds_id="ds1",
            when=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            battery=80,
            iob=2.3,
            cob=15.0,
        )
        rows = extract_pump_events_from_devicestatuses(
            [ds], user_id="u1", source="nightscout:c1", last_state={}
        )
        battery_row = next(r for r in rows if r["event_type"] == PumpEventType.BATTERY)
        assert battery_row["iob_at_event"] == 2.3
        assert battery_row["cob_at_event"] == 15.0

    def test_unchanged_value_skipped_after_min_interval(self):
        """Within-batch dedupe: same value across consecutive
        devicestatuses must not duplicate."""
        t0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
        ds_list = [
            _make_ds(ds_id=f"ds{i}", when=t0 + timedelta(minutes=i * 5), battery=80)
            for i in range(3)
        ]
        rows = extract_pump_events_from_devicestatuses(
            ds_list, user_id="u1", source="nightscout:c1", last_state={}
        )
        battery_rows = [r for r in rows if r["event_type"] == PumpEventType.BATTERY]
        assert len(battery_rows) == 1, (
            "Unchanged battery value should not produce additional rows"
        )

    def test_value_change_within_min_interval_is_skipped(self):
        """The 1-min min-interval guard fires even when value changes
        — defends against oscillation hammering the table."""
        t0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
        ds_list = [
            _make_ds(ds_id="ds1", when=t0, battery=80),
            # 30s later, battery flickered down a percent
            _make_ds(ds_id="ds2", when=t0 + timedelta(seconds=30), battery=79),
        ]
        rows = extract_pump_events_from_devicestatuses(
            ds_list, user_id="u1", source="nightscout:c1", last_state={}
        )
        battery_rows = [r for r in rows if r["event_type"] == PumpEventType.BATTERY]
        assert len(battery_rows) == 1
        assert battery_rows[0]["units"] == 80.0

    def test_value_change_after_min_interval_emits(self):
        t0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
        ds_list = [
            _make_ds(ds_id="ds1", when=t0, battery=80),
            _make_ds(
                ds_id="ds2",
                when=t0 + timedelta(seconds=_MIN_INTERVAL_SECONDS + 1),
                battery=79,
            ),
        ]
        rows = extract_pump_events_from_devicestatuses(
            ds_list, user_id="u1", source="nightscout:c1", last_state={}
        )
        battery_rows = [r for r in rows if r["event_type"] == PumpEventType.BATTERY]
        assert len(battery_rows) == 2

    def test_initial_state_blocks_first_row(self):
        """When the DB has a recent prior row, we respect the
        min-interval against the pre-batch state."""
        t0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
        last_state = {
            "battery": {
                "value": 80.0,
                "timestamp": t0 - timedelta(seconds=30),
            }
        }
        ds = _make_ds(ds_id="ds1", when=t0, battery=79)
        rows = extract_pump_events_from_devicestatuses(
            [ds],
            user_id="u1",
            source="nightscout:c1",
            last_state=last_state,
        )
        battery_rows = [r for r in rows if r["event_type"] == PumpEventType.BATTERY]
        assert len(battery_rows) == 0

    def test_missing_fields_dont_crash(self):
        """A devicestatus missing pump or loop subtrees emits zero
        rows for the missing fields and the existing ones unaffected."""
        ds = _make_ds(
            ds_id="ds1",
            when=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            battery=80,
            # no reservoir, no enacted_rate
        )
        rows = extract_pump_events_from_devicestatuses(
            [ds], user_id="u1", source="nightscout:c1", last_state={}
        )
        kinds = {r["event_type"] for r in rows}
        assert PumpEventType.BATTERY in kinds
        assert PumpEventType.RESERVOIR not in kinds
        assert PumpEventType.BASAL not in kinds

    def test_missing_id_skips_row(self):
        """No `_id` -> no stable ns_id for dedupe -> drop the row
        rather than invent a key."""
        ds = NightscoutDeviceStatus.model_validate(
            {
                "device": "loop://iPhone",
                "created_at": "2026-05-01T12:00:00Z",
                "pump": {"battery": {"percent": 80}},
            }
        )
        rows = extract_pump_events_from_devicestatuses(
            [ds], user_id="u1", source="nightscout:c1", last_state={}
        )
        assert rows == []

    def test_ns_id_suffix_per_event_type(self):
        """Multiple events from one devicestatus must have distinct
        ns_ids so the per-source unique index works correctly."""
        ds = _make_ds(
            ds_id="ds-shared",
            when=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            battery=80,
            reservoir=145.5,
            enacted_rate=0.8,
        )
        rows = extract_pump_events_from_devicestatuses(
            [ds], user_id="u1", source="nightscout:c1", last_state={}
        )
        ns_ids = [r["ns_id"] for r in rows]
        assert len(set(ns_ids)) == len(ns_ids)
        assert "ds-shared:battery" in ns_ids
        assert "ds-shared:reservoir" in ns_ids
        assert "ds-shared:basal" in ns_ids

    def test_is_automated_set_per_type(self):
        """is_automated must be non-null for every emitted row.
        BASAL=True (loop.enacted IS automated), BATTERY/RESERVOIR=False
        unless `isCharging` flips BATTERY semantics."""
        ds = _make_ds(
            ds_id="ds1",
            when=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            battery=80,
            reservoir=145.5,
            enacted_rate=0.8,
            is_charging=True,
        )
        rows = extract_pump_events_from_devicestatuses(
            [ds], user_id="u1", source="nightscout:c1", last_state={}
        )
        by_type = {r["event_type"]: r for r in rows}
        # All three rows have is_automated explicitly set (not None)
        for r in rows:
            assert r["is_automated"] is not None
        assert by_type[PumpEventType.BASAL]["is_automated"] is True
        # BATTERY uses isCharging
        assert by_type[PumpEventType.BATTERY]["is_automated"] is True
        assert by_type[PumpEventType.RESERVOIR]["is_automated"] is False

    def test_battery_is_automated_false_when_not_charging_unset(self):
        """is_charging=None must coerce to False (NOT NULL constraint)."""
        ds = _make_ds(
            ds_id="ds1",
            when=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            battery=80,
            # is_charging not set -> ds.is_charging will be None
        )
        rows = extract_pump_events_from_devicestatuses(
            [ds], user_id="u1", source="nightscout:c1", last_state={}
        )
        battery_row = next(r for r in rows if r["event_type"] == PumpEventType.BATTERY)
        assert battery_row["is_automated"] is False

    def test_in_batch_state_propagates(self):
        """Walking a multi-tick batch, the state from earlier rows
        affects emit decisions for later rows."""
        t0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
        ds_list = [
            # ds1: first sight, both fields emit (state empty).
            _make_ds(ds_id="ds1", when=t0, battery=80, reservoir=145.5),
            # ds2 +90s: battery 80 -> 79 (emit; 90s > 60s, value changed),
            #          reservoir 145.5 unchanged (skip; value-change gate).
            _make_ds(
                ds_id="ds2",
                when=t0 + timedelta(seconds=90),
                battery=79,
                reservoir=145.5,
            ),
            # ds3 +30s after ds2: battery 79 -> 78 (skip; only 30s elapsed
            #                     since last battery emit, < 60s min-interval),
            #                     reservoir 145.5 -> 145.0 (emit; 120s
            #                     since last reservoir emit, value changed).
            _make_ds(
                ds_id="ds3",
                when=t0 + timedelta(seconds=120),
                battery=78,
                reservoir=145.0,
            ),
        ]
        rows = extract_pump_events_from_devicestatuses(
            ds_list, user_id="u1", source="nightscout:c1", last_state={}
        )
        battery_rows = [r for r in rows if r["event_type"] == PumpEventType.BATTERY]
        reservoir_rows = [r for r in rows if r["event_type"] == PumpEventType.RESERVOIR]
        assert [r["units"] for r in battery_rows] == [80.0, 79.0]
        assert [r["units"] for r in reservoir_rows] == [145.5, 145.0]

    def test_out_of_order_input_does_not_self_correct(self):
        """The function does NOT sort internally -- the translator is
        expected to sort before calling. Out-of-order input means a
        later-timestamp row gets processed first; the in-batch state
        machine then sees the earlier-timestamp row as "going back in
        time" and applies the min-interval guard against the
        already-recorded later-state, suppressing the early row.

        Document the behavior so a future contributor doesn't try to
        relax sorting at the call site without reading this test.
        """
        t0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
        ds_list = [
            _make_ds(ds_id="ds-late", when=t0 + timedelta(minutes=5), battery=79),
            _make_ds(ds_id="ds-early", when=t0, battery=80),
        ]
        rows = extract_pump_events_from_devicestatuses(
            ds_list, user_id="u1", source="nightscout:c1", last_state={}
        )
        battery_rows = [r for r in rows if r["event_type"] == PumpEventType.BATTERY]
        # Late one emits (state empty). Early one is suppressed -- diff
        # vs last_state (ds-late) is -5 min, which is < 60s so the
        # min-interval gate fires. This is the documented hazard of
        # passing unsorted input.
        assert [r["ns_id"] for r in battery_rows] == ["ds-late:battery"]


# ---------------------------------------------------------------------------
# _normalize_row_shapes (multi-row INSERT bug fix)
# ---------------------------------------------------------------------------


class TestNormalizeRowShapes:
    def test_pads_missing_keys_to_none(self):
        rows = [
            {"a": 1, "b": 2},
            {"a": 3, "c": 4},
        ]
        out = _normalize_row_shapes(rows)
        assert all(set(r.keys()) == {"a", "b", "c"} for r in out)
        assert out[0] == {"a": 1, "b": 2, "c": None}
        assert out[1] == {"a": 3, "b": None, "c": 4}

    def test_uniform_rows_unchanged(self):
        rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        out = _normalize_row_shapes(rows)
        assert out == rows

    def test_empty_input(self):
        assert _normalize_row_shapes([]) == []

    def test_preserves_falsy_values(self):
        """0 / None / False / "" are real values, not absent keys."""
        rows = [
            {"a": 0, "b": False, "c": None},
            {"a": 1, "b": True},  # missing "c"
        ]
        out = _normalize_row_shapes(rows)
        assert out[0]["a"] == 0
        assert out[0]["b"] is False
        assert out[0]["c"] is None
        assert out[1]["c"] is None  # padded


# ---------------------------------------------------------------------------
# Regression: meal-bolus pair (carbs + bolus in one batch) used to
# produce inconsistent dict shapes that crashed the multi-row INSERT.
# ---------------------------------------------------------------------------


class TestMealBolusMultiRowRegression:
    """The translator-level meal-bolus pair test (in
    test_nightscout_translator.py::TestTreatmentsPath::
    test_meal_bolus_pair_splits_into_two_linked_rows) covers the
    end-to-end DB insert. Here we cover the unit-level shape
    invariant: the bolus row dict and the carb-entry row dict
    must agree on column keys after `_base_event` has set the
    common `is_automated=False` baseline.
    """

    def test_base_event_sets_is_automated(self):
        from src.services.integrations.nightscout._pump_events_mapper import (
            _base_event,
        )
        from src.services.integrations.nightscout.models import (
            NightscoutTreatment,
        )

        treatment = NightscoutTreatment.model_validate(
            {
                "_id": "x",
                "eventType": "Bolus",
                "created_at": "2026-05-01T12:00:00Z",
                "insulin": 1.0,
            }
        )
        base = _base_event(
            treatment,
            user_id="u1",
            source="nightscout:c1",
            event_type=PumpEventType.BOLUS,
            received_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
        assert base is not None
        assert "is_automated" in base
        assert base["is_automated"] is False

    def test_bolus_overrides_is_automated_for_smb(self):
        from src.services.integrations.nightscout._pump_events_mapper import (
            _base_event,
            _map_bolus,
        )
        from src.services.integrations.nightscout.models import (
            NightscoutTreatment,
        )

        treatment = NightscoutTreatment.model_validate(
            {
                "_id": "x",
                "eventType": "SMB",
                "created_at": "2026-05-01T12:00:00Z",
                "insulin": 0.3,
            }
        )
        base = _base_event(
            treatment,
            user_id="u1",
            source="nightscout:c1",
            event_type=PumpEventType.BOLUS,
            received_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
        result = _map_bolus(treatment, base)
        # SMB is automated by definition
        assert result["is_automated"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
