"""Tests for the Medtronic CareLink CSV export parser (clean-room).

All CSV content here is synthetic -- no real patient data.
"""

from datetime import datetime

from loguru import logger

from src.services.integrations.medtronic.carelink_csv import (
    CareLinkRow,
    parse_carelink_csv,
)

# The full observed v15.x column header (order preserved).
HEADER = [
    "Index",
    "Date",
    "Time",
    "New Device Time",
    "BG Source",
    "BG Reading (mg/dL)",
    "Linked BG Meter ID",
    "Basal Rate (U/h)",
    "Temp Basal Amount",
    "Temp Basal Type",
    "Temp Basal Duration (h:mm:ss)",
    "Bolus Type",
    "Bolus Volume Selected (U)",
    "Bolus Volume Delivered (U)",
    "Bolus Duration (h:mm:ss)",
    "Prime Type",
    "Prime Volume Delivered (U)",
    "Estimated Reservoir Volume after Fill (U)",
    "Alert",
    "User Cleared Alerts",
    "Suspend",
    "Rewind",
    "BWZ Estimate (U)",
    "BWZ Target High BG (mg/dL)",
    "BWZ Target Low BG (mg/dL)",
    "BWZ Carb Ratio (g/U)",
    "BWZ Insulin Sensitivity (mg/dL/U)",
    "BWZ Carb Input (grams)",
    "BWZ BG/SG Input (mg/dL)",
    "BWZ Correction Estimate (U)",
    "BWZ Food Estimate (U)",
    "BWZ Active Insulin (U)",
    "BWZ Status",
    "Sensor Calibration BG (mg/dL)",
    "Sensor Glucose (mg/dL)",
    "ISIG Value",
    "Event Marker",
    "Bolus Number",
    "Bolus Cancellation Reason",
    "BWZ Unabsorbed Insulin Total (U)",
    "Final Bolus Estimate",
    "Scroll Step Size",
    "Insulin Action Curve Time",
    "Sensor Calibration Rejected Reason",
    "Preset Bolus",
    "Bolus Source",
    "BLE Network Device",
    "Device Update Event",
    "Network Device Associated Reason",
    "Network Device Disassociated Reason",
    "Network Device Disconnected Reason",
    "Sensor Exception",
    "Preset Temp Basal Name",
    "Sensor State",
]


def _row(header: list[str], values: dict[str, str]) -> str:
    """Build one CSV data line from a {column: value} dict, padding the rest."""
    return ",".join(str(values.get(col, "")) for col in header)


def _build_csv(
    rows: list[dict[str, str]],
    *,
    header: list[str] = HEADER,
    bom: bool = True,
    extra_sections: list[list[dict[str, str]]] | None = None,
) -> str:
    lines = [
        "Last Name,First Name,Patient ID,System ID,Start Date,End Date,Device,"
        "MiniMed 780G MMT-1884,Hardware Version,A1.01,Firmware Version,11.11.7",
        '"Doe","Jane","","","01-18-2025 12:00:00 AM","01-31-2025 12:00:00 AM",'
        '"Serial Number",ABC1234567H,Software Version,6.21U',
        "Patient DOB,,,,,,CGM,Guardian™ 4 Sensor",
        "",
        "-------,MiniMed 780G MMT-1884,Pump,ABC1234567H,------- ",
        ",".join(header),
        *[_row(header, r) for r in rows],
    ]
    for section in extra_sections or []:
        lines.append(",".join(header))
        lines.extend(_row(header, r) for r in section)
    text = "\n".join(lines)
    return ("﻿" + text) if bom else text


def _by_index(export, idx: int) -> CareLinkRow:
    return next(r for r in export.rows if r.index == idx)


def test_parses_metadata_and_basic_rows():
    csv_text = _build_csv(
        [
            {
                "Index": "0",
                "Date": "2025/01/31",
                "Time": "15:02:05",
                "Basal Rate (U/h)": "0.85",
            },
            {
                "Index": "1",
                "Date": "2025/01/31",
                "Time": "14:55:00",
                "Sensor Glucose (mg/dL)": "124",
                "ISIG Value": "21.5",
                "Sensor State": "NO_ERROR_MESSAGE",
            },
        ]
    )
    export = parse_carelink_csv(csv_text)

    assert export.device == "MiniMed 780G MMT-1884"
    assert export.serial_number == "ABC1234567H"
    assert export.cgm == "Guardian™ 4 Sensor"
    assert export.section_count == 1
    assert len(export.rows) == 2

    basal = _by_index(export, 0)
    assert basal.timestamp == datetime(2025, 1, 31, 15, 2, 5)
    assert basal.basal_rate_uh == 0.85
    assert basal.sensor_glucose_mgdl is None  # empty -> None

    sg = _by_index(export, 1)
    assert sg.sensor_glucose_mgdl == 124
    assert sg.isig == 21.5
    assert sg.sensor_state == "NO_ERROR_MESSAGE"


def test_parses_bolus_with_source_and_carbs():
    csv_text = _build_csv(
        [
            {
                "Index": "0",
                "Date": "2025/01/31",
                "Time": "12:00:00",
                "Bolus Type": "NORMAL",
                "Bolus Volume Selected (U)": "3.0",
                "Bolus Volume Delivered (U)": "3.0",
                "Bolus Source": "BOLUS_WIZARD",
                "BWZ Carb Input (grams)": "45",
                "BWZ Active Insulin (U)": "1.2",
            },
            {
                "Index": "1",
                "Date": "2025/01/31",
                "Time": "12:30:00",
                "Bolus Type": "NORMAL",
                "Bolus Volume Delivered (U)": "0.6",
                "Bolus Source": "CLOSED_LOOP_AUTO_BOLUS",
            },
        ]
    )
    export = parse_carelink_csv(csv_text)

    manual = _by_index(export, 0)
    assert manual.bolus_delivered_u == 3.0
    assert manual.bolus_source == "BOLUS_WIZARD"
    assert manual.carb_input_g == 45.0
    assert manual.active_insulin_u == 1.2

    auto = _by_index(export, 1)
    assert auto.bolus_delivered_u == 0.6
    assert auto.bolus_source == "CLOSED_LOOP_AUTO_BOLUS"  # SmartGuard auto-bolus
    assert auto.carb_input_g is None


def test_multi_section_export():
    """The real export repeats the header per section (pump/CGM/meter). All
    sections' rows are returned in order; Index restarts per section."""
    csv_text = _build_csv(
        [
            {
                "Index": "0",
                "Date": "2025/01/31",
                "Time": "10:00:00",
                "Basal Rate (U/h)": "1.0",
            }
        ],
        extra_sections=[
            [
                {
                    "Index": "0",
                    "Date": "2025/01/30",
                    "Time": "09:00:00",
                    "BG Source": "METER",
                    "BG Reading (mg/dL)": "98",
                }
            ],
        ],
    )
    export = parse_carelink_csv(csv_text)
    assert export.section_count == 2
    assert len(export.rows) == 2
    assert export.rows[0].basal_rate_uh == 1.0
    assert export.rows[1].bg_mgdl == 98
    assert export.rows[1].bg_source == "METER"


def test_name_based_mapping_survives_column_reorder():
    """Columns are mapped by name, so a reordered header still parses."""
    reordered = ["Index", "Time", "Date", "Sensor Glucose (mg/dL)", "Basal Rate (U/h)"]
    csv_text = _build_csv(
        [
            {
                "Index": "0",
                "Date": "2025/01/31",
                "Time": "08:15:00",
                "Sensor Glucose (mg/dL)": "150",
                "Basal Rate (U/h)": "0.5",
            }
        ],
        header=reordered,
    )
    export = parse_carelink_csv(csv_text)
    assert len(export.rows) == 1
    row = export.rows[0]
    assert row.sensor_glucose_mgdl == 150
    assert row.basal_rate_uh == 0.5
    assert row.timestamp == datetime(2025, 1, 31, 8, 15, 0)


def test_semicolon_delimited_with_european_decimal_comma():
    """A locale export that uses ';' as the delimiter and ',' as the decimal
    mark: the parser must auto-detect the delimiter (so '0,85' stays one
    field) and then read the comma as a decimal point."""
    header = ["Index", "Date", "Time", "Basal Rate (U/h)", "Bolus Volume Delivered (U)"]
    csv_text = "\n".join(
        [
            ";".join(header),
            ";".join(["0", "2025/01/31", "07:00:00", "0,85", "2,5"]),
        ]
    )
    export = parse_carelink_csv(csv_text)
    assert len(export.rows) == 1
    row = export.rows[0]
    assert row.basal_rate_uh == 0.85
    assert row.bolus_delivered_u == 2.5


def test_skips_blank_and_nondata_rows_and_strips_bom():
    csv_text = _build_csv(
        [
            {
                "Index": "0",
                "Date": "2025/01/31",
                "Time": "06:00:00",
                "Suspend": "USER_SUSPEND",
            }
        ],
        bom=True,
    )
    export = parse_carelink_csv(csv_text)
    # Only the one real data row; blank lines + metadata preamble excluded.
    assert len(export.rows) == 1
    assert export.rows[0].suspend == "USER_SUSPEND"
    # BOM did not leak into the first metadata cell used for device detection.
    assert export.device == "MiniMed 780G MMT-1884"


def test_empty_input_returns_empty_export():
    export = parse_carelink_csv("")
    assert export.rows == []
    assert export.section_count == 0


def test_ambiguous_non_year_first_date_yields_no_timestamp():
    """We only accept unambiguous year-first dates. A day/month-first value is
    NOT guessed (which could misdate by months) -> timestamp is None."""
    csv_text = _build_csv(
        [
            {
                "Index": "0",
                "Date": "02/03/2025",
                "Time": "08:00:00",
                "Sensor Glucose (mg/dL)": "130",
            }
        ]
    )
    export = parse_carelink_csv(csv_text)
    assert len(export.rows) == 1
    assert export.rows[0].timestamp is None  # not silently mis-parsed
    assert export.rows[0].sensor_glucose_mgdl == 130


def test_raw_is_empty_unless_keep_raw():
    csv_text = _build_csv(
        [
            {
                "Index": "0",
                "Date": "2025/01/31",
                "Time": "08:00:00",
                "Basal Rate (U/h)": "0.7",
            }
        ]
    )
    assert parse_carelink_csv(csv_text).rows[0].raw == {}
    kept = parse_carelink_csv(csv_text, keep_raw=True).rows[0].raw
    assert kept.get("Basal Rate (U/h)") == "0.7"


def test_carelink_mmol_header_detected_and_glucose_skipped():
    """CareLink CSV with mmol/L headers: glucose rows are skipped visibly."""
    csv_text = (
        "Index,Date,Time,BG Source,BG Reading (mmol/L),Sensor Glucose (mmol/L)\n"
        "0,2026-05-06,11:30:00,Meter,5.5,6.1\n"
    )
    export = parse_carelink_csv(csv_text)
    assert export.section_count == 1
    # Glucose values must be None -- skipped, not stored as raw mmol numbers
    for row in export.rows:
        assert row.bg_mgdl is None
        assert row.sensor_glucose_mgdl is None


def test_carelink_mmol_section_drops_populated_mgdl_columns_and_warns():
    """A mmol section that ALSO carries populated mg/dL-named glucose columns still
    drops glucose, and emits the operator warning.

    This is the enforcement guard: the mmol headers signal the section's true unit, so
    even the mg/dL-named values (180/200 here) must be dropped -- without the explicit
    ``is_mmol_section`` skip they would be stored as mg/dL. Non-glucose fields (basal)
    are retained. The earlier mmol-only test passes incidentally because the mg/dL alias
    simply isn't present; this one cannot.
    """
    csv_text = (
        "Index,Date,Time,BG Source,BG Reading (mg/dL),BG Reading (mmol/L),"
        "Sensor Glucose (mg/dL),Sensor Glucose (mmol/L),Basal Rate (U/h)\n"
        "0,2026-05-06,11:30:00,Meter,180,10.0,200,11.1,0.85\n"
    )
    messages: list[str] = []
    sink_id = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    try:
        export = parse_carelink_csv(csv_text)
    finally:
        logger.remove(sink_id)

    assert export.section_count == 1
    row = export.rows[0]
    assert row.bg_mgdl is None
    assert row.sensor_glucose_mgdl is None
    # Non-glucose fields survive the glucose-only skip.
    assert row.basal_rate_uh == 0.85
    # The skip is announced so an operator can see a section was partially dropped.
    assert any("mmol/L headers" in m for m in messages)


def test_carelink_mgdl_header_still_works():
    """CareLink CSV with mg/dL headers continues to parse correctly."""
    csv_text = (
        "Index,Date,Time,BG Source,BG Reading (mg/dL),Sensor Glucose (mg/dL)\n"
        "0,2026-05-06,11:30:00,Meter,120,145\n"
    )
    export = parse_carelink_csv(csv_text)
    assert export.section_count == 1
    assert export.rows[0].bg_mgdl == 120
    assert export.rows[0].sensor_glucose_mgdl == 145
