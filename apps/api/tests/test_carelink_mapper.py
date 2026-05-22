"""Tests for the CareLink -> normalized-model mapper (pure, clean-room)."""

from datetime import datetime

from src.models.pump_data import PumpEventType
from src.services.integrations.medtronic.carelink_csv import (
    CareLinkExport,
    CareLinkRow,
)
from src.services.integrations.medtronic.carelink_mapper import (
    SOURCE,
    map_carelink_export,
)

TS = datetime(2025, 1, 31, 12, 0, 0)


def _export(*rows: CareLinkRow) -> CareLinkExport:
    return CareLinkExport(rows=list(rows))


def _events_of(records, etype):
    return [e for e in records.pump_events if e.event_type == etype]


def test_sensor_glucose_maps_to_glucose_reading():
    rec = map_carelink_export(
        _export(CareLinkRow(timestamp=TS, index=0, sensor_glucose_mgdl=124))
    )
    assert len(rec.glucose) == 1
    assert rec.glucose[0].value_mgdl == 124
    assert rec.glucose[0].timestamp == TS
    assert rec.glucose[0].source == SOURCE
    assert rec.pump_events == []


def test_manual_bolus_maps_to_bolus_with_carbs_and_iob():
    rec = map_carelink_export(
        _export(
            CareLinkRow(
                timestamp=TS,
                index=0,
                bolus_delivered_u=3.0,
                bolus_source="BOLUS_WIZARD",
                carb_input_g=45.0,
                active_insulin_u=1.2,
            )
        )
    )
    bolus = _events_of(rec, PumpEventType.BOLUS)
    assert len(bolus) == 1
    assert bolus[0].units == 3.0
    assert bolus[0].is_automated is False
    assert bolus[0].cob_at_event == 45.0
    assert bolus[0].iob_at_event == 1.2
    assert _events_of(rec, PumpEventType.CORRECTION) == []


def test_smartguard_auto_correction_maps_to_automated_correction():
    # Real 780G closed-loop correction source (no food component).
    rec = map_carelink_export(
        _export(
            CareLinkRow(
                timestamp=TS,
                index=0,
                bolus_delivered_u=0.6,
                bolus_source="CLOSED_LOOP_BG_CORRECTION",
            )
        )
    )
    corr = _events_of(rec, PumpEventType.CORRECTION)
    assert len(corr) == 1
    assert corr[0].units == 0.6
    assert corr[0].is_automated is True
    assert corr[0].control_iq_reason == "correction"
    assert _events_of(rec, PumpEventType.BOLUS) == []


def test_smartguard_food_bolus_maps_to_user_bolus():
    # A closed-loop meal bolus is user-initiated -> BOLUS, not automated.
    rec = map_carelink_export(
        _export(
            CareLinkRow(
                timestamp=TS,
                index=0,
                bolus_delivered_u=3.5,
                bolus_source="CLOSED_LOOP_BG_CORRECTION_AND_FOOD_BOLUS",
            )
        )
    )
    bolus = _events_of(rec, PumpEventType.BOLUS)
    assert len(bolus) == 1
    assert bolus[0].units == 3.5
    assert bolus[0].is_automated is False
    assert _events_of(rec, PumpEventType.CORRECTION) == []


def test_auto_insulin_daily_basal_total_is_skipped():
    # CLOSED_LOOP_AUTO_INSULIN is a daily auto-basal TOTAL, not a bolus -- it
    # must NOT be stored as a bolus (inflates bolus insulin) or a basal-rate
    # event (would be x24'd by the TDD calc). It produces no event.
    rec = map_carelink_export(
        _export(
            CareLinkRow(
                timestamp=TS,
                index=0,
                bolus_delivered_u=47.872,
                bolus_source="CLOSED_LOOP_AUTO_INSULIN",
            )
        )
    )
    assert rec.pump_events == []
    assert rec.glucose == []


def test_fingerstick_bg_maps_to_bg_reading_event():
    rec = map_carelink_export(
        _export(CareLinkRow(timestamp=TS, index=0, bg_source="METER", bg_mgdl=98))
    )
    bg = _events_of(rec, PumpEventType.BG_READING)
    assert len(bg) == 1
    assert bg[0].bg_at_event == 98


def test_scheduled_basal_maps_to_basal_rate():
    rec = map_carelink_export(
        _export(CareLinkRow(timestamp=TS, index=0, basal_rate_uh=0.85))
    )
    basal = _events_of(rec, PumpEventType.BASAL)
    assert len(basal) == 1
    assert basal[0].units == 0.85
    assert basal[0].is_automated is False


def test_temp_basal_maps_to_automated_basal_with_duration():
    rec = map_carelink_export(
        _export(
            CareLinkRow(
                timestamp=TS,
                index=0,
                temp_basal_amount=1.2,
                temp_basal_type="Percent",
                temp_basal_duration="0:30:00",
            )
        )
    )
    basal = _events_of(rec, PumpEventType.BASAL)
    assert len(basal) == 1
    assert basal[0].units == 1.2
    assert basal[0].duration_minutes == 30
    assert basal[0].is_automated is True
    assert basal[0].control_iq_reason == "temp_basal"


def test_suspend_and_resume():
    rec = map_carelink_export(
        _export(
            CareLinkRow(timestamp=TS, index=0, suspend="USER_SUSPEND"),
            CareLinkRow(timestamp=TS, index=1, suspend="NORMAL_PUMPING"),
        )
    )
    assert len(_events_of(rec, PumpEventType.SUSPEND)) == 1
    assert len(_events_of(rec, PumpEventType.RESUME)) == 1


def test_carb_only_entry_maps_to_carbs():
    rec = map_carelink_export(
        _export(CareLinkRow(timestamp=TS, index=0, carb_input_g=30.0))
    )
    carbs = _events_of(rec, PumpEventType.CARBS)
    assert len(carbs) == 1
    assert carbs[0].cob_at_event == 30.0


def test_row_without_timestamp_is_skipped():
    rec = map_carelink_export(
        _export(CareLinkRow(timestamp=None, index=0, sensor_glucose_mgdl=120))
    )
    assert rec.glucose == []
    assert rec.pump_events == []


def test_end_to_end_parse_then_map():
    """A small real-shaped CSV through parser + mapper."""
    from src.services.integrations.medtronic.carelink_csv import parse_carelink_csv

    header = "Index,Date,Time,Basal Rate (U/h),Bolus Volume Delivered (U),Bolus Source,Sensor Glucose (mg/dL)"
    csv_text = "\n".join(
        [
            header,
            "0,2025/01/31,12:00:00,0.85,,,",
            "1,2025/01/31,12:05:00,,2.0,BOLUS_WIZARD,",
            "2,2025/01/31,12:05:00,,,,140",
        ]
    )
    rec = map_carelink_export(parse_carelink_csv(csv_text))
    assert len(rec.glucose) == 1 and rec.glucose[0].value_mgdl == 140
    assert len(_events_of(rec, PumpEventType.BASAL)) == 1
    assert len(_events_of(rec, PumpEventType.BOLUS)) == 1
