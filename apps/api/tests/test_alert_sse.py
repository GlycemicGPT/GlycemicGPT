"""Story 6.3: Tests for alert event emission via SSE stream."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.routers.glucose_stream import format_sse_event, generate_glucose_stream


class TestFormatSseAlertEvent:
    """Tests for SSE alert event formatting."""

    async def test_format_alert_event(self):
        """Test formatting an alert as an SSE event."""
        alert_data = {
            "id": "abc-123",
            "alert_type": "low_urgent",
            "severity": "emergency",
            "current_value": 50.0,
            "predicted_value": None,
            "prediction_minutes": None,
            "iob_value": 2.5,
            "message": "Urgent low glucose: 50 mg/dL",
            "trend_rate": -3.0,
            "source": "threshold",
            "created_at": "2025-01-01T00:00:00+00:00",
            "expires_at": "2025-01-01T00:30:00+00:00",
        }

        result = format_sse_event(
            event_type="alert",
            data=alert_data,
            event_id="42",
        )

        assert "event: alert" in result
        assert "id: 42" in result
        assert "data:" in result

        # Extract and parse the data line
        data_line = [line for line in result.split("\n") if line.startswith("data:")][0]
        parsed = json.loads(data_line[5:].strip())
        assert parsed["alert_type"] == "low_urgent"
        assert parsed["severity"] == "emergency"
        assert parsed["current_value"] == 50.0
        assert parsed["message"] == "Urgent low glucose: 50 mg/dL"


class TestAlertDeduplication:
    """Tests for alert deduplication in SSE stream."""

    @patch("src.routers.glucose_stream.get_active_alerts")
    @patch("src.routers.glucose_stream.get_latest_glucose_reading")
    @patch(
        "src.routers.glucose_stream.get_user_dia",
        new_callable=AsyncMock,
        return_value=4.0,
    )
    @patch("src.routers.glucose_stream.get_iob_projection")
    @patch("src.routers.glucose_stream.get_db_session")
    async def test_alert_not_sent_twice(
        self, mock_db_session, mock_iob, mock_dia, mock_glucose, mock_alerts
    ):
        """Test that the same alert is not sent twice per connection."""
        from enum import Enum

        class MockAlertType(Enum):
            low_urgent = "low_urgent"

        class MockSeverity(Enum):
            emergency = "emergency"

        mock_alert = MagicMock()
        mock_alert.id = uuid.uuid4()
        mock_alert.alert_type = MockAlertType.low_urgent
        mock_alert.severity = MockSeverity.emergency
        mock_alert.current_value = 50.0
        mock_alert.predicted_value = None
        mock_alert.prediction_minutes = None
        mock_alert.iob_value = 2.5
        mock_alert.message = "Urgent low glucose: 50 mg/dL"
        mock_alert.trend_rate = -3.0
        mock_alert.source = "threshold"
        mock_alert.created_at = datetime.now(UTC)
        mock_alert.expires_at = datetime.now(UTC) + timedelta(minutes=30)

        # Return the same alert on every call
        mock_alerts.return_value = [mock_alert]

        # No glucose reading
        mock_glucose.return_value = None
        mock_iob.return_value = None

        # Mock db session context manager
        mock_session = AsyncMock()
        mock_db_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_session.return_value.__aexit__ = AsyncMock(return_value=False)

        # Mock request that disconnects after 2 iterations
        mock_request = MagicMock()
        call_count = 0

        async def mock_is_disconnected():
            nonlocal call_count
            call_count += 1
            # Disconnect after enough iterations to check dedup
            return call_count > 3

        mock_request.is_disconnected = mock_is_disconnected

        # Collect all events
        events = []
        with patch("asyncio.sleep", AsyncMock()):
            async for event in generate_glucose_stream(
                "00000000-0000-0000-0000-000000000001", mock_request
            ):
                events.append(event)

        # Count alert events
        alert_events = [e for e in events if "event: alert" in e]

        # Should only have 1 alert event despite multiple iterations
        assert len(alert_events) == 1, (
            f"Expected 1 alert event but got {len(alert_events)}. "
            "Alert deduplication may not be working."
        )

    @patch("src.routers.glucose_stream.get_active_alerts")
    @patch("src.routers.glucose_stream.get_latest_glucose_reading")
    @patch(
        "src.routers.glucose_stream.get_user_dia",
        new_callable=AsyncMock,
        return_value=4.0,
    )
    @patch("src.routers.glucose_stream.get_iob_projection")
    @patch("src.routers.glucose_stream.get_db_session")
    async def test_no_alert_events_when_no_alerts(
        self, mock_db_session, mock_iob, mock_dia, mock_glucose, mock_alerts
    ):
        """Test that no alert events are emitted when there are no active alerts."""
        mock_alerts.return_value = []
        mock_glucose.return_value = None
        mock_iob.return_value = None

        mock_session = AsyncMock()
        mock_db_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_request = MagicMock()
        call_count = 0

        async def mock_is_disconnected():
            nonlocal call_count
            call_count += 1
            return call_count > 2

        mock_request.is_disconnected = mock_is_disconnected

        events = []
        with patch("asyncio.sleep", AsyncMock()):
            async for event in generate_glucose_stream(
                "00000000-0000-0000-0000-000000000001", mock_request
            ):
                events.append(event)

        alert_events = [e for e in events if "event: alert" in e]
        assert len(alert_events) == 0


class TestAlertEventPayload:
    """Tests for alert event payload structure."""

    async def test_alert_event_has_required_fields(self):
        """Test that alert SSE event data contains all required fields."""
        required_fields = [
            "id",
            "alert_type",
            "severity",
            "current_value",
            "predicted_value",
            "prediction_minutes",
            "iob_value",
            "message",
            "trend_rate",
            "source",
            "created_at",
            "expires_at",
        ]

        alert_data = {
            "id": "test-id",
            "alert_type": "high_warning",
            "severity": "warning",
            "current_value": 200.0,
            "predicted_value": 220.0,
            "prediction_minutes": 30,
            "iob_value": None,
            "message": "High glucose warning",
            "trend_rate": 2.0,
            "source": "predictive",
            "created_at": "2025-01-01T00:00:00+00:00",
            "expires_at": "2025-01-01T00:30:00+00:00",
        }

        result = format_sse_event("alert", alert_data, event_id="1")

        data_line = [line for line in result.split("\n") if line.startswith("data:")][0]
        parsed = json.loads(data_line[5:].strip())

        for field in required_fields:
            assert field in parsed, f"Missing required field: {field}"

    @patch("src.routers.glucose_stream.get_active_alerts")
    @patch("src.routers.glucose_stream.get_latest_glucose_reading")
    @patch(
        "src.routers.glucose_stream.get_user_dia",
        new_callable=AsyncMock,
        return_value=4.0,
    )
    @patch("src.routers.glucose_stream.get_iob_projection")
    @patch("src.routers.glucose_stream.get_db_session")
    async def test_alert_payload_numerics_are_canonical_mgdl_without_unit_tag(
        self, mock_db_session, mock_iob, mock_dia, mock_glucose, mock_alerts
    ):
        """The emitted SSE alert payload keeps current/predicted as canonical
        mg/dL floats and carries NO unit tag. The web client converts off the
        viewer's own glucose-unit preference, never off the payload, so nothing
        double-interprets; mobile keeps mg/dL until a later unit story adds an
        explicit tag plus numeric conversion verified with a mobile consumer.
        """
        from enum import Enum

        class MockAlertType(Enum):
            low_urgent = "low_urgent"

        class MockSeverity(Enum):
            emergency = "emergency"

        mock_alert = MagicMock()
        mock_alert.id = uuid.uuid4()
        mock_alert.alert_type = MockAlertType.low_urgent
        mock_alert.severity = MockSeverity.emergency
        mock_alert.current_value = 70.0
        mock_alert.predicted_value = 65.0
        mock_alert.prediction_minutes = 15
        mock_alert.iob_value = None
        # The message is rendered in the patient's unit at persist (may be mmol);
        # the numeric fields below stay canonical mg/dL.
        mock_alert.message = "Urgent low glucose: 3.9 mmol/L"
        mock_alert.trend_rate = -2.0
        mock_alert.source = "predictive"
        mock_alert.created_at = datetime.now(UTC)
        mock_alert.expires_at = datetime.now(UTC) + timedelta(minutes=30)
        mock_alerts.return_value = [mock_alert]
        mock_glucose.return_value = None
        mock_iob.return_value = None

        mock_session = AsyncMock()
        mock_db_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_db_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_request = MagicMock()
        call_count = 0

        async def mock_is_disconnected():
            nonlocal call_count
            call_count += 1
            return call_count > 2

        mock_request.is_disconnected = mock_is_disconnected

        events = []
        with patch("asyncio.sleep", AsyncMock()):
            async for event in generate_glucose_stream(
                "00000000-0000-0000-0000-000000000001", mock_request
            ):
                events.append(event)

        alert_events = [e for e in events if "event: alert" in e]
        assert len(alert_events) == 1
        data_line = [
            line for line in alert_events[0].split("\n") if line.startswith("data:")
        ][0]
        parsed = json.loads(data_line[5:].strip())
        # Numerics are canonical mg/dL, untouched by any unit preference.
        assert parsed["current_value"] == 70.0
        assert parsed["predicted_value"] == 65.0
        # No unit tag on the payload (recorded decision for this cut).
        assert "glucose_unit" not in parsed
        assert "unit" not in parsed
