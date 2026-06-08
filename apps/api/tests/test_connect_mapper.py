"""Tests for the CareLink CarePartner RecentData -> normalized-model mapper.

The payload shapes mirror xDrip's ``cgm/carelinkfollow`` message classes
(GPL-3.0), re-implemented here independently. Fixtures use the field names the
CarePartner ``display/message`` endpoint returns.
"""

from datetime import UTC, datetime, timedelta, timezone

from src.models.pump_data import PumpEventType
from src.services.integrations.medtronic.connect_mapper import (
    SOURCE,
    map_recent_data,
)

_EST = timezone(-timedelta(hours=5))

# Device clock == server clock (no skew) unless a test overrides these.
_SERVER_MS = 1_700_000_000_000
_CONDUIT_MS = 1_700_000_000_000


def _events_of(records, etype):
    return [e for e in records.pump_events if e.event_type == etype]


def _recent(**overrides) -> dict:
    base = {
        "lastConduitUpdateServerDateTime": _SERVER_MS,
        "lastConduitDateTime": _CONDUIT_MS,
        "sgs": [],
        "markers": [],
    }
    base.update(overrides)
    return base


def test_empty_or_non_dict_payload_is_safe():
    assert map_recent_data({}).glucose == []
    assert map_recent_data(None).glucose == []  # type: ignore[arg-type]
    assert map_recent_data([]).pump_events == []  # type: ignore[arg-type]


def test_sensor_glucose_maps_to_glucose_reading():
    rec = map_recent_data(
        _recent(sgs=[{"sg": 124, "datetime": "2025-01-31T12:00:00-05:00"}])
    )
    assert len(rec.glucose) == 1
    g = rec.glucose[0]
    assert g.value_mgdl == 124
    assert g.source == SOURCE
    assert g.timestamp == datetime(2025, 1, 31, 12, 0, tzinfo=_EST)
    assert rec.pump_events == []


def test_zero_or_missing_sg_is_skipped():
    rec = map_recent_data(
        _recent(
            sgs=[
                {"sg": 0, "datetime": "2025-01-31T12:00:00-05:00"},  # sensor gap
                {"sg": 100},  # no datetime
                {"datetime": "2025-01-31T12:05:00-05:00"},  # no sg
            ]
        )
    )
    assert rec.glucose == []


def test_insulin_marker_maps_to_bolus():
    rec = map_recent_data(
        _recent(
            markers=[
                {
                    "type": "INSULIN",
                    "displayTime": "2025-01-31T12:00:00-05:00",
                    "deliveredFastAmount": 3.5,
                    "deliveredExtendedAmount": 0.0,
                }
            ]
        )
    )
    bolus = _events_of(rec, PumpEventType.BOLUS)
    assert len(bolus) == 1
    assert bolus[0].units == 3.5
    assert bolus[0].is_automated is False
    # Conservative v1: nothing classified as an automated correction yet.
    assert _events_of(rec, PumpEventType.CORRECTION) == []


def test_normal_bolus_fast_amount_only_no_extended_key():
    # Regression: an ordinary bolus carries only top-level deliveredFastAmount
    # with NO deliveredExtendedAmount key at all. Earlier logic required BOTH
    # top-level amounts to be present before using them, so this was silently
    # dropped (returned None) and never stored. Either top-level amount alone
    # must be honored.
    rec = map_recent_data(
        _recent(
            markers=[
                {
                    "type": "INSULIN",
                    "displayTime": "2025-01-31T12:00:00-05:00",
                    "deliveredFastAmount": 4.2,
                }
            ]
        )
    )
    bolus = _events_of(rec, PumpEventType.BOLUS)
    assert len(bolus) == 1
    assert bolus[0].units == 4.2


def test_extended_bolus_extended_amount_only_no_fast_key():
    # Symmetric case: a square/extended-wave bolus may carry only
    # deliveredExtendedAmount. It must also map (missing fast component = 0).
    rec = map_recent_data(
        _recent(
            markers=[
                {
                    "type": "INSULIN",
                    "displayTime": "2025-01-31T12:00:00-05:00",
                    "deliveredExtendedAmount": 1.75,
                }
            ]
        )
    )
    bolus = _events_of(rec, PumpEventType.BOLUS)
    assert len(bolus) == 1
    assert bolus[0].units == 1.75


def test_dual_wave_bolus_sums_fast_and_extended():
    # Dual-wave: both components present -> sum them.
    rec = map_recent_data(
        _recent(
            markers=[
                {
                    "type": "INSULIN",
                    "displayTime": "2025-01-31T12:00:00-05:00",
                    "deliveredFastAmount": 2.0,
                    "deliveredExtendedAmount": 1.5,
                }
            ]
        )
    )
    bolus = _events_of(rec, PumpEventType.BOLUS)
    assert len(bolus) == 1
    assert bolus[0].units == 3.5


def test_insulin_amount_falls_back_to_data_values():
    rec = map_recent_data(
        _recent(
            markers=[
                {
                    "type": "INSULIN",
                    "dateTime": "2025-01-31T12:00:00-05:00",
                    "data": {"dataValues": {"deliveredFastAmount": 2.25}},
                }
            ]
        )
    )
    bolus = _events_of(rec, PumpEventType.BOLUS)
    assert len(bolus) == 1
    assert bolus[0].units == 2.25


def test_zero_insulin_marker_is_skipped():
    rec = map_recent_data(
        _recent(
            markers=[
                {
                    "type": "INSULIN",
                    "displayTime": "2025-01-31T12:00:00-05:00",
                    "deliveredFastAmount": 0.0,
                    "deliveredExtendedAmount": 0.0,
                }
            ]
        )
    )
    assert rec.pump_events == []


def test_meal_marker_maps_to_carbs():
    rec = map_recent_data(
        _recent(
            markers=[
                {
                    "type": "MEAL",
                    "displayTime": "2025-01-31T12:00:00-05:00",
                    "amount": 45.0,
                }
            ]
        )
    )
    carbs = _events_of(rec, PumpEventType.CARBS)
    assert len(carbs) == 1
    assert carbs[0].cob_at_event == 45.0


def test_bg_and_calibration_markers_map_to_bg_reading():
    rec = map_recent_data(
        _recent(
            markers=[
                {
                    "type": "BG_READING",
                    "displayTime": "2025-01-31T12:00:00-05:00",
                    "value": 110,
                },
                {
                    "type": "CALIBRATION",
                    "displayTime": "2025-01-31T12:05:00-05:00",
                    "data": {"dataValues": {"unitValue": 118}},
                },
            ]
        )
    )
    bgs = _events_of(rec, PumpEventType.BG_READING)
    assert len(bgs) == 2
    assert {b.bg_at_event for b in bgs} == {110, 118}


def test_naive_datetime_is_refused():
    # CarePartner datetimes are zoned; a naive string must not be misdated.
    rec = map_recent_data(
        _recent(
            sgs=[{"sg": 120, "datetime": "2025-01-31T12:00:00"}],
            markers=[
                {
                    "type": "INSULIN",
                    "displayTime": "2025-01-31T12:00:00",
                    "deliveredFastAmount": 1.0,
                }
            ],
        )
    )
    assert rec.glucose == []
    assert rec.pump_events == []


def test_clock_skew_shifts_timestamps_forward():
    # Device clock 2h behind server -> diffInHour = +2, shift readings +2h.
    rec = map_recent_data(
        _recent(
            lastConduitUpdateServerDateTime=_SERVER_MS,
            lastConduitDateTime=_SERVER_MS - 2 * 3_600_000,
            sgs=[{"sg": 130, "datetime": "2025-01-31T12:00:00-05:00"}],
        )
    )
    assert rec.glucose[0].timestamp == datetime(2025, 1, 31, 14, 0, tzinfo=_EST)


def test_large_or_zero_skew_is_not_applied():
    # >= 26h diff is treated as garbage (xDrip parity); no shift applied.
    rec = map_recent_data(
        _recent(
            lastConduitUpdateServerDateTime=_SERVER_MS,
            lastConduitDateTime=_SERVER_MS - 30 * 3_600_000,
            sgs=[{"sg": 130, "datetime": "2025-01-31T12:00:00-05:00"}],
        )
    )
    assert rec.glucose[0].timestamp == datetime(2025, 1, 31, 12, 0, tzinfo=_EST)


def test_unmapped_marker_types_are_ignored():
    # v1 deliberately skips auto-basal/auto-mode-status markers.
    rec = map_recent_data(
        _recent(
            markers=[
                {
                    "type": "AUTO_BASAL_DELIVERY",
                    "displayTime": "2025-01-31T12:00:00-05:00",
                    "value": 0.5,
                },
                {
                    "type": "AUTO_MODE_STATUS",
                    "displayTime": "2025-01-31T12:05:00-05:00",
                },
            ]
        )
    )
    assert rec.pump_events == []


def test_implausible_sg_values_are_dropped():
    rec = map_recent_data(
        _recent(
            sgs=[
                {"sg": 5000, "datetime": "2025-01-31T12:00:00-05:00"},  # absurd high
                {"sg": 3, "datetime": "2025-01-31T12:05:00-05:00"},  # absurd low
                {"sg": 120, "datetime": "2025-01-31T12:10:00-05:00"},  # valid
            ]
        )
    )
    assert [g.value_mgdl for g in rec.glucose] == [120]


def test_large_negative_skew_is_not_applied():
    # Device clock far AHEAD of server -> large negative diff -> treated as
    # garbage (symmetric bound), no shift.
    rec = map_recent_data(
        _recent(
            lastConduitUpdateServerDateTime=_SERVER_MS,
            lastConduitDateTime=_SERVER_MS + 40 * 3_600_000,
            sgs=[{"sg": 130, "datetime": "2025-01-31T12:00:00-05:00"}],
        )
    )
    assert rec.glucose[0].timestamp == datetime(2025, 1, 31, 12, 0, tzinfo=_EST)


def test_small_negative_skew_shifts_backward():
    # Device 3h ahead -> diff -3 -> shift readings back 3h.
    rec = map_recent_data(
        _recent(
            lastConduitUpdateServerDateTime=_SERVER_MS,
            lastConduitDateTime=_SERVER_MS + 3 * 3_600_000,
            sgs=[{"sg": 130, "datetime": "2025-01-31T12:00:00-05:00"}],
        )
    )
    assert rec.glucose[0].timestamp == datetime(2025, 1, 31, 9, 0, tzinfo=_EST)


def test_scheduled_basal_rate_maps_to_basal_event_at_snapshot():
    rec = map_recent_data(
        _recent(basal={"activeBasalPattern": "Weekday", "basalRate": 0.85})
    )
    basal = _events_of(rec, PumpEventType.BASAL)
    assert len(basal) == 1
    assert basal[0].units == 0.85
    # Timestamped at the server snapshot instant (lastConduitUpdateServerDateTime).
    assert basal[0].timestamp == datetime.fromtimestamp(_SERVER_MS / 1000, tz=UTC)


def test_implausible_basal_rate_is_dropped():
    rec = map_recent_data(_recent(basal={"basalRate": 99}))
    assert _events_of(rec, PumpEventType.BASAL) == []


def test_non_numeric_amounts_fail_soft():
    # External data could carry non-numeric junk; conversions must not raise.
    rec = map_recent_data(
        _recent(
            markers=[
                {
                    "type": "INSULIN",
                    "displayTime": "2025-01-31T12:00:00-05:00",
                    "deliveredFastAmount": "N/A",
                    "deliveredExtendedAmount": "N/A",
                },
                {
                    "type": "MEAL",
                    "displayTime": "2025-01-31T12:05:00-05:00",
                    "amount": "oops",
                },
            ],
            basal={"basalRate": "bad"},
        )
    )
    assert rec.pump_events == []
