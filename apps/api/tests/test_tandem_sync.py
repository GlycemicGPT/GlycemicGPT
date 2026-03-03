"""Story 3.4, 3.5, & 15.8: Tests for Tandem pump data ingestion, Control-IQ parsing,
and pump profile sync."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.main import app
from src.models.pump_data import PumpActivityMode, PumpEventType
from src.services.tandem_sync import (
    _normalize_pump_event,
    _store_pump_settings,
    calculate_basal_adjustment,
    detect_pump_activity_mode,
    map_event_type,
    parse_control_iq_event,
)


def unique_email(prefix: str = "test") -> str:
    """Generate a unique email for testing."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


class TestEventTypeMapping:
    """Tests for Tandem event type mapping."""

    def test_map_basal_event(self):
        """Test mapping basal event."""
        event_type, is_automated, reason = map_event_type({"type": "basal"})
        assert event_type == PumpEventType.BASAL
        assert is_automated is False
        assert reason is None

    def test_map_automated_basal_event(self):
        """Test mapping automated basal event."""
        event_type, is_automated, reason = map_event_type(
            {
                "type": "autoBasal",
                "isAutomated": True,
            }
        )
        assert event_type == PumpEventType.BASAL
        assert is_automated is True
        assert reason == "basal_adjustment"

    def test_map_bolus_event(self):
        """Test mapping bolus event."""
        event_type, is_automated, reason = map_event_type({"type": "bolus"})
        assert event_type == PumpEventType.BOLUS
        assert is_automated is False
        assert reason is None

    def test_map_correction_bolus_event(self):
        """Test mapping correction bolus event (Control-IQ)."""
        event_type, is_automated, reason = map_event_type(
            {
                "type": "correctionBolus",
            }
        )
        assert event_type == PumpEventType.CORRECTION
        assert is_automated is True
        assert reason == "correction"

    def test_map_automated_correction_event(self):
        """Test mapping automated correction event."""
        event_type, is_automated, reason = map_event_type(
            {
                "type": "correction",
                "isAutomated": True,
            }
        )
        assert event_type == PumpEventType.CORRECTION
        assert is_automated is True
        assert reason == "correction"

    def test_map_suspend_event(self):
        """Test mapping suspend event."""
        event_type, is_automated, reason = map_event_type({"type": "suspend"})
        assert event_type == PumpEventType.SUSPEND
        assert is_automated is False

    def test_map_automated_suspend_event(self):
        """Test mapping automated suspend event (Control-IQ)."""
        event_type, is_automated, reason = map_event_type(
            {
                "type": "autoSuspend",
                "isAutomated": True,
            }
        )
        assert event_type == PumpEventType.SUSPEND
        assert is_automated is True
        assert reason == "suspend"

    def test_map_resume_event(self):
        """Test mapping resume event."""
        event_type, is_automated, reason = map_event_type({"type": "resume"})
        assert event_type == PumpEventType.RESUME
        assert is_automated is False

    def test_map_unknown_event_defaults_to_bolus(self):
        """Test that unknown event types default to bolus."""
        event_type, is_automated, reason = map_event_type({"type": "unknown"})
        assert event_type == PumpEventType.BOLUS
        assert is_automated is False

    # Issue #10: Missing malformed data tests
    def test_map_event_type_handles_missing_type(self):
        """Test handling of events with missing type field."""
        event_type, is_automated, reason = map_event_type({})
        assert event_type == PumpEventType.BOLUS  # Default
        assert is_automated is False

    def test_map_event_type_handles_none_type(self):
        """Test handling of None type value."""
        event_type, is_automated, reason = map_event_type({"type": None})
        assert event_type == PumpEventType.BOLUS


class TestTandemSyncEndpoints:
    """Tests for Tandem sync endpoints."""

    async def test_tandem_sync_requires_auth(self):
        """Test that Tandem sync endpoint requires authentication."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/api/integrations/tandem/sync")

        assert response.status_code == 401

    async def test_tandem_sync_status_requires_auth(self):
        """Test that Tandem sync status endpoint requires authentication."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/integrations/tandem/sync/status")

        assert response.status_code == 401

    async def test_tandem_sync_not_configured(self):
        """Test sync fails when Tandem is not configured."""
        email = unique_email("tandem_sync_nocred")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Try to sync
            response = await client.post(
                "/api/integrations/tandem/sync",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 404
        assert "not configured" in response.json()["detail"].lower()

    async def test_get_tandem_sync_status_not_configured(self):
        """Test sync status when Tandem is not configured."""
        email = unique_email("tandem_status")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Get sync status
            response = await client.get(
                "/api/integrations/tandem/sync/status",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["integration_status"] == "not_configured"
        assert data["events_available"] == 0

    @patch("src.services.tandem_sync.fetch_with_retry")
    @patch("src.services.tandem_sync.TandemSourceApi")
    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_sync_tandem_with_mocked_data(
        self, mock_validate, mock_tandem_class, mock_fetch
    ):
        """Test Tandem sync with mocked Tandem API."""
        mock_validate.return_value = (True, None)
        mock_tandem_class.return_value = MagicMock()

        # Create mock normalized events (as returned by fetch_with_retry)
        mock_fetch.return_value = (
            [
                {
                    "type": "bolus",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "units": 2.5,
                    "iob": 3.2,
                },
                {
                    "type": "autoBasal",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "units": 0.8,
                    "isAutomated": True,
                    "duration": 30,
                },
            ],
            None,
        )

        email = unique_email("tandem_sync_mock")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Connect Tandem first
            await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "tandem@example.com",
                    "password": "tandem_password",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Now sync
            response = await client.post(
                "/api/integrations/tandem/sync",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Sync completed successfully"
        assert data["events_fetched"] == 2
        assert data["events_stored"] == 2

    @patch("src.services.tandem_sync.fetch_with_retry")
    @patch("src.services.tandem_sync.TandemSourceApi")
    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_sync_tandem_control_iq_flagging(
        self, mock_validate, mock_tandem_class, mock_fetch
    ):
        """Test that Control-IQ events are properly flagged as automated."""
        mock_validate.return_value = (True, None)
        mock_tandem_class.return_value = MagicMock()

        # Create mock Control-IQ correction event
        mock_fetch.return_value = (
            [
                {
                    "type": "correctionBolus",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "units": 0.5,
                    "isAutomated": True,
                    "iob": 2.1,
                    "bg": 180,
                },
            ],
            None,
        )

        email = unique_email("tandem_controliq")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Connect Tandem first
            await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "tandem@example.com",
                    "password": "tandem_password",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Sync
            response = await client.post(
                "/api/integrations/tandem/sync",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["events_stored"] == 1
        # Verify the last event is automated
        assert data["last_event"]["is_automated"] is True
        assert data["last_event"]["event_type"] == "correction"

    @patch("src.services.tandem_sync.fetch_with_retry")
    @patch("src.services.tandem_sync.TandemSourceApi")
    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_sync_tandem_empty_response(
        self, mock_validate, mock_tandem_class, mock_fetch
    ):
        """Test Tandem sync with no events."""
        mock_validate.return_value = (True, None)
        mock_tandem_class.return_value = MagicMock()
        mock_fetch.return_value = ([], None)

        email = unique_email("tandem_empty")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Connect Tandem first
            await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "tandem@example.com",
                    "password": "tandem_password",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Sync
            response = await client.post(
                "/api/integrations/tandem/sync",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["events_fetched"] == 0
        assert data["events_stored"] == 0
        assert data["last_event"] is None

    @patch("src.services.tandem_sync.fetch_with_retry")
    @patch("src.services.tandem_sync.TandemSourceApi")
    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_tandem_sync_status_after_sync(
        self, mock_validate, mock_tandem_class, mock_fetch
    ):
        """Test sync status after a successful sync."""
        mock_validate.return_value = (True, None)
        mock_tandem_class.return_value = MagicMock()

        mock_fetch.return_value = (
            [
                {
                    "type": "bolus",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "units": 3.0,
                },
            ],
            None,
        )

        email = unique_email("tandem_status_sync")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Connect and sync
            await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "tandem@example.com",
                    "password": "tandem_password",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            await client.post(
                "/api/integrations/tandem/sync",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Check status
            response = await client.get(
                "/api/integrations/tandem/sync/status",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["integration_status"] == "connected"
        assert data["events_available"] == 1
        assert data["last_sync_at"] is not None
        assert data["latest_event"] is not None

    # Issue #10: Test for skipping events without timestamp
    @patch("src.services.tandem_sync.fetch_with_retry")
    @patch("src.services.tandem_sync.TandemSourceApi")
    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_sync_skips_events_without_timestamp(
        self, mock_validate, mock_tandem_class, mock_fetch
    ):
        """Test that events without valid timestamps are skipped."""
        mock_validate.return_value = (True, None)
        mock_tandem_class.return_value = MagicMock()

        mock_fetch.return_value = (
            [
                {"type": "bolus", "units": 2.5},  # No timestamp - should skip
                {
                    "type": "bolus",
                    "timestamp": "invalid-date",
                    "units": 1.0,
                },  # Invalid - skip
                {
                    "type": "bolus",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "units": 3.0,
                },  # Valid
            ],
            None,
        )

        email = unique_email("tandem_skip_invalid")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "tandem@example.com",
                    "password": "tandem_password",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            response = await client.post(
                "/api/integrations/tandem/sync",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        # Should only store 1 event (the valid one)
        assert data["events_stored"] == 1

    # Issue #1: Test region configuration
    @patch("src.services.tandem_sync.TandemSourceApi")
    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_tandem_connect_with_eu_region(
        self, mock_validate, mock_tandem_class
    ):
        """Test connecting Tandem with EU region."""
        mock_validate.return_value = (True, None)
        mock_api = MagicMock()
        mock_tandem_class.return_value = mock_api

        email = unique_email("tandem_eu_region")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )

            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )

            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            # Connect with EU region
            response = await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "tandem@example.com",
                    "password": "tandem_password",
                    "region": "EU",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        # Verify validate was called with EU region
        mock_validate.assert_called_with(
            "tandem@example.com",
            "tandem_password",
            "EU",
        )


# Issue #4: Tests for get_pump_events helper function
# Note: The get_pump_events function is tested indirectly through:
# 1. TestTandemSyncService tests (sync stores events, which get_pump_events retrieves)
# 2. test_get_tandem_sync_status_* tests (sync status endpoint uses get_pump_events)


# Story 3.5: Tests for Control-IQ Activity Parsing


class TestPumpActivityModeDetection:
    """Tests for pump activity mode detection (Story 3.5)."""

    def test_detect_sleep_mode_from_activity_type(self):
        """Test detecting Sleep mode from activityType field."""
        mode = detect_pump_activity_mode({"activityType": "Sleep"})
        assert mode == PumpActivityMode.SLEEP

    def test_detect_exercise_mode_from_activity_type(self):
        """Test detecting Exercise mode from activityType field."""
        mode = detect_pump_activity_mode({"activityType": "Exercise"})
        assert mode == PumpActivityMode.EXERCISE

    def test_detect_none_mode(self):
        """Test detecting None (standard) mode."""
        mode = detect_pump_activity_mode({"mode": "standard"})
        assert mode == PumpActivityMode.NONE

    def test_detect_sleep_mode_from_flag(self):
        """Test detecting Sleep mode from boolean flag."""
        mode = detect_pump_activity_mode({"isSleepMode": True})
        assert mode == PumpActivityMode.SLEEP

    def test_detect_exercise_mode_from_flag(self):
        """Test detecting Exercise mode from boolean flag."""
        mode = detect_pump_activity_mode({"isExerciseMode": True})
        assert mode == PumpActivityMode.EXERCISE

    def test_detect_mode_returns_none_for_unknown(self):
        """Test that unknown mode returns None."""
        mode = detect_pump_activity_mode({"type": "bolus"})
        assert mode is None

    def test_detect_mode_case_insensitive(self):
        """Test that mode detection is case insensitive."""
        mode = detect_pump_activity_mode({"activityType": "SLEEP"})
        assert mode == PumpActivityMode.SLEEP


class TestBasalAdjustmentCalculation:
    """Tests for basal adjustment percentage calculation (Story 3.5)."""

    def test_calculate_adjustment_from_direct_percentage(self):
        """Test getting adjustment from direct percentage field."""
        adj = calculate_basal_adjustment({"adjustmentPercent": 25.0})
        assert adj == 25.0

    def test_calculate_adjustment_from_rates(self):
        """Test calculating adjustment from profile vs actual rates."""
        # Profile rate: 1.0, Actual rate: 1.5 = 50% increase
        adj = calculate_basal_adjustment(
            {
                "profileRate": 1.0,
                "rate": 1.5,
            }
        )
        assert adj == 50.0

    def test_calculate_adjustment_decrease(self):
        """Test calculating a decrease in basal rate."""
        # Profile rate: 1.0, Actual rate: 0.5 = 50% decrease
        adj = calculate_basal_adjustment(
            {
                "profileRate": 1.0,
                "rate": 0.5,
            }
        )
        assert adj == -50.0

    def test_calculate_adjustment_returns_none_when_missing_data(self):
        """Test that None is returned when data is missing."""
        adj = calculate_basal_adjustment({"type": "basal"})
        assert adj is None

    def test_calculate_adjustment_with_zero_profile_rate(self):
        """Test handling of zero profile rate (avoid division by zero)."""
        adj = calculate_basal_adjustment(
            {
                "profileRate": 0,
                "rate": 1.0,
            }
        )
        assert adj is None


class TestParseControlIQEvent:
    """Tests for full Control-IQ event parsing (Story 3.5)."""

    def test_parse_automated_correction(self):
        """Test parsing an automated correction bolus."""
        parsed = parse_control_iq_event(
            {
                "type": "correction",
                "isAutomated": True,
                "units": 0.5,
            }
        )
        assert parsed.event_type == PumpEventType.CORRECTION
        assert parsed.is_automated is True
        assert parsed.control_iq_reason == "correction"

    def test_parse_basal_increase_with_mode(self):
        """Test parsing a basal increase in Sleep mode."""
        parsed = parse_control_iq_event(
            {
                "type": "basal",
                "isAutomated": True,
                "profileRate": 1.0,
                "rate": 1.5,
                "activityType": "Sleep",
            }
        )
        assert parsed.event_type == PumpEventType.BASAL
        assert parsed.is_automated is True
        assert parsed.control_iq_reason == "basal_increase"
        assert parsed.pump_activity_mode == PumpActivityMode.SLEEP
        assert parsed.basal_adjustment_pct == 50.0

    def test_parse_basal_decrease(self):
        """Test parsing a basal decrease."""
        parsed = parse_control_iq_event(
            {
                "type": "basal",
                "isAutomated": True,
                "profileRate": 1.0,
                "rate": 0.3,
            }
        )
        assert parsed.event_type == PumpEventType.BASAL
        assert parsed.control_iq_reason == "basal_decrease"
        assert parsed.basal_adjustment_pct == -70.0

    def test_parse_manual_bolus_no_mode(self):
        """Test parsing a manual bolus has no Control-IQ mode."""
        parsed = parse_control_iq_event(
            {
                "type": "bolus",
                "units": 5.0,
            }
        )
        assert parsed.event_type == PumpEventType.BOLUS
        assert parsed.is_automated is False
        assert parsed.pump_activity_mode is None
        assert parsed.basal_adjustment_pct is None

    def test_parse_automated_suspend(self):
        """Test parsing an automated suspend (predicted low)."""
        parsed = parse_control_iq_event(
            {
                "type": "autoSuspend",
                "isAutomated": True,
            }
        )
        assert parsed.event_type == PumpEventType.SUSPEND
        assert parsed.is_automated is True
        assert parsed.control_iq_reason == "suspend"


class TestBgReadingEventType:
    """Tests for bg_reading event type mapping."""

    def test_map_bg_reading_event(self):
        """Test mapping bg_reading event type returns BG_READING."""
        event_type, is_automated, reason = map_event_type({"type": "bg_reading"})
        assert event_type == PumpEventType.BG_READING
        assert is_automated is False
        assert reason is None


class TestNormalizePumpEvent:
    """Tests for _normalize_pump_event IoB and units extraction."""

    def _make_event(self, data: dict):
        """Create a mock event object with todict() returning data."""
        mock = MagicMock()
        mock.todict.return_value = data
        return mock

    def test_event_id_16_extracts_iob(self):
        """Event ID 16 (LidBgReadingTaken) should extract IoB."""
        import arrow

        event = self._make_event(
            {
                "id": "16",
                "eventTimestamp": arrow.now(),
                "IOB": "6.14",
                "BG": "257",
            }
        )
        result = _normalize_pump_event(event)
        assert result is not None
        assert result["type"] == "bg_reading"
        assert result["iob"] == 6.14
        assert result["bg"] == 257

    def test_event_id_20_is_excluded(self):
        """Event ID 20 (LidBolusCompleted) should be excluded to prevent duplication."""
        import arrow

        event = self._make_event(
            {
                "id": "20",
                "eventTimestamp": arrow.now(),
                "InsulinDelivered": "3.5",
            }
        )
        result = _normalize_pump_event(event)
        assert result is None

    def test_event_id_280_completed_extracts_units(self):
        """Event ID 280 (LidBolusDelivery) Completed should extract units."""
        import arrow

        event = self._make_event(
            {
                "id": "280",
                "eventTimestamp": arrow.now(),
                "bolusDeliveryStatusRaw": "0",  # Completed
                "deliveredTotal": "3000",  # milliunits
            }
        )
        result = _normalize_pump_event(event)
        assert result is not None
        assert result["type"] == "bolus"
        assert result["units"] == 3.0

    def test_event_id_280_started_is_skipped(self):
        """Event ID 280 (LidBolusDelivery) Started should be skipped."""
        import arrow

        event = self._make_event(
            {
                "id": "280",
                "eventTimestamp": arrow.now(),
                "bolusDeliveryStatusRaw": "1",  # Started
                "deliveredTotal": "3000",
            }
        )
        result = _normalize_pump_event(event)
        assert result is None

    def test_unmapped_event_id_returns_none(self):
        """Unmapped event IDs should return None."""
        import arrow

        event = self._make_event(
            {
                "id": "999",
                "eventTimestamp": arrow.now(),
            }
        )
        result = _normalize_pump_event(event)
        assert result is None

    def test_missing_timestamp_returns_none(self):
        """Events without timestamps should return None."""
        event = self._make_event(
            {
                "id": "16",
            }
        )
        result = _normalize_pump_event(event)
        assert result is None

    def test_iob_none_when_not_present(self):
        """Events without IOB field should not have iob key."""
        import arrow

        event = self._make_event(
            {
                "id": "3",
                "eventTimestamp": arrow.now(),
            }
        )
        result = _normalize_pump_event(event)
        assert result is not None
        assert result["type"] == "basal"
        assert "iob" not in result

    def test_event_279_populates_units_from_rate(self):
        """Event 279 (LidBasalDelivery) should store rate as units for aggregation."""
        import arrow

        event = self._make_event(
            {
                "id": "279",
                "eventTimestamp": arrow.now(),
                "commandedRate": "800",  # 800 milliunits/hr = 0.8 U/hr
                "profileBasalRate": "750",
            }
        )
        result = _normalize_pump_event(event)
        assert result is not None
        assert result["type"] == "basal"
        assert result["actualRate"] == 0.8
        assert result["units"] == 0.8
        assert result["profileRate"] == 0.75

    def test_event_3_populates_units_from_rate(self):
        """Event 3 (basal rate change) should store rate as units for aggregation."""
        import arrow

        event = self._make_event(
            {
                "id": "3",
                "eventTimestamp": arrow.now(),
                "commandedbasalrate": "1.2",
                "basebasalrate": "0.9",
            }
        )
        result = _normalize_pump_event(event)
        assert result is not None
        assert result["type"] == "basal"
        assert result["actualRate"] == 1.2
        assert result["units"] == 1.2
        assert result["profileRate"] == 0.9

    def test_event_279_no_rate_no_units(self):
        """Event 279 without commandedRate should not set units."""
        import arrow

        event = self._make_event(
            {
                "id": "279",
                "eventTimestamp": arrow.now(),
                "profileBasalRate": "750",
            }
        )
        result = _normalize_pump_event(event)
        assert result is not None
        assert result["type"] == "basal"
        assert "units" not in result


class TestControlIQActivityEndpoint:
    """Tests for the Control-IQ activity endpoint (Story 3.5)."""

    async def test_control_iq_activity_requires_auth(self):
        """Test that the endpoint requires authentication."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/integrations/tandem/control-iq/activity")
        assert response.status_code == 401

    async def test_control_iq_activity_empty_result(self):
        """Test activity endpoint returns zeros when no events exist."""
        email = unique_email("controliq_empty")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Register and login
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )
            login_resp = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )
            session_cookie = login_resp.cookies.get(settings.jwt_cookie_name)

            response = await client.get(
                "/api/integrations/tandem/control-iq/activity",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["total_events"] == 0
        assert data["automated_events"] == 0
        assert data["correction_count"] == 0
        assert data["hours_analyzed"] == 24

    async def test_control_iq_activity_custom_hours(self):
        """Test activity endpoint accepts custom hours parameter."""
        email = unique_email("controliq_hours")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )
            login_resp = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )
            session_cookie = login_resp.cookies.get(settings.jwt_cookie_name)

            response = await client.get(
                "/api/integrations/tandem/control-iq/activity",
                params={"hours": 48},
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["hours_analyzed"] == 48


# Story 15.8: Tests for pump profile sync


def _make_raw_settings(
    profiles: list[dict] | None = None,
    active_idp: int = 1,
    cgm_high: int = 240,
    cgm_low: int = 70,
) -> dict:
    """Build a raw settings dict matching the structure of Tandem metadata."""
    if profiles is None:
        profiles = [
            {
                "name": "Default",
                "idp": 1,
                "tDependentSegs": [
                    {
                        "startTime": 0,
                        "basalRate": 1500,  # milliunits/hr -> 1.5 u/hr
                        "isf": 31,
                        "carbRatio": 8000,  # milliunits -> 8.0
                        "targetBg": 110,
                    },
                    {
                        "startTime": 300,  # 5:00 AM
                        "basalRate": 1650,
                        "isf": 25,
                        "carbRatio": 7000,  # milliunits -> 7.0
                        "targetBg": 110,
                    },
                ],
                "insulinDuration": 300,  # 5 hours
                "carbEntry": 1,
                "maxBolus": 30000,  # milliunits -> 30.0 units
            },
        ]
    return {
        "profiles": {
            "activeIdp": active_idp,
            "profile": profiles,
        },
        "cgmSettings": {
            "highGlucoseAlert": {
                "mgPerDl": cgm_high,
                "enabled": 1,
                "duration": 0,
                "status": 0,
            },
            "lowGlucoseAlert": {
                "mgPerDl": cgm_low,
                "enabled": 1,
                "duration": 0,
                "status": 0,
            },
        },
    }


class TestStorePumpSettings:
    """Tests for _store_pump_settings (Story 15.8)."""

    @pytest.mark.asyncio
    async def test_stores_single_profile(self):
        """Test storing a single pump profile with segments."""
        raw_settings = _make_raw_settings()
        user_id = uuid.uuid4()

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        db.execute = AsyncMock(return_value=mock_result)

        count = await _store_pump_settings(db, user_id, raw_settings)

        assert count == 1
        db.execute.assert_called_once()

        # Inspect the upsert statement values
        call_args = db.execute.call_args
        stmt = call_args[0][0]
        # The statement should be an insert with on_conflict_do_update
        compiled = stmt.compile(compile_kwargs={"literal_binds": False})
        sql = str(compiled)
        assert "pump_profiles" in sql
        assert "ON CONFLICT" in sql

    @pytest.mark.asyncio
    async def test_converts_milliunits_correctly(self):
        """Test that milliunits are converted to units."""
        raw_settings = _make_raw_settings()
        user_id = uuid.uuid4()

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        db.execute = AsyncMock(return_value=mock_result)

        await _store_pump_settings(db, user_id, raw_settings)

        # Extract the values from the insert statement
        call_args = db.execute.call_args
        stmt = call_args[0][0]
        params = stmt.compile().params
        # max_bolus should be 30.0 (30000 / 1000)
        assert params["max_bolus_units"] == 30.0
        # Segments should have converted basal rates and carb ratios
        segments = params["segments"]
        assert segments[0]["basal_rate"] == 1.5  # 1500 / 1000
        assert segments[1]["basal_rate"] == 1.65  # 1650 / 1000
        assert segments[0]["carb_ratio"] == 8.0  # 8000 / 1000
        assert segments[1]["carb_ratio"] == 7.0  # 7000 / 1000

    @pytest.mark.asyncio
    async def test_time_conversion(self):
        """Test that startTime minutes are converted to HH:MM AM/PM."""
        raw_settings = _make_raw_settings()
        user_id = uuid.uuid4()

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        db.execute = AsyncMock(return_value=mock_result)

        await _store_pump_settings(db, user_id, raw_settings)

        call_args = db.execute.call_args
        stmt = call_args[0][0]
        params = stmt.compile().params
        segments = params["segments"]
        assert segments[0]["time"] == "12:00 AM"  # 0 minutes
        assert segments[1]["time"] == "5:00 AM"  # 300 minutes

    @pytest.mark.asyncio
    async def test_multiple_profiles(self):
        """Test storing multiple profiles with correct active flag."""
        profiles = [
            {
                "name": "Default",
                "idp": 1,
                "tDependentSegs": [
                    {
                        "startTime": 0,
                        "basalRate": 1000,
                        "isf": 30,
                        "carbRatio": 8000,  # milliunits -> 8.0
                        "targetBg": 110,
                    },
                ],
                "insulinDuration": 300,
                "carbEntry": 1,
                "maxBolus": 25000,
            },
            {
                "name": "Weekend",
                "idp": 2,
                "tDependentSegs": [
                    {
                        "startTime": 0,
                        "basalRate": 800,
                        "isf": 35,
                        "carbRatio": 10000,  # milliunits -> 10.0
                        "targetBg": 120,
                    },
                ],
                "insulinDuration": 300,
                "carbEntry": 1,
                "maxBolus": 20000,
            },
        ]
        raw_settings = _make_raw_settings(profiles=profiles, active_idp=1)
        user_id = uuid.uuid4()

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        db.execute = AsyncMock(return_value=mock_result)

        count = await _store_pump_settings(db, user_id, raw_settings)

        assert count == 2
        assert db.execute.call_count == 2

        # First call (Default, active) should have is_active=True
        first_stmt = db.execute.call_args_list[0][0][0]
        first_params = first_stmt.compile().params
        assert first_params["is_active"] is True

        # Second call (Weekend, inactive) should have is_active=False
        second_stmt = db.execute.call_args_list[1][0][0]
        second_params = second_stmt.compile().params
        assert second_params["is_active"] is False

    @pytest.mark.asyncio
    async def test_cgm_alerts_only_on_active_profile(self):
        """Test CGM alert thresholds only appear on the active profile."""
        profiles = [
            {
                "name": "Default",
                "idp": 1,
                "tDependentSegs": [
                    {
                        "startTime": 0,
                        "basalRate": 1000,
                        "isf": 30,
                        "carbRatio": 8000,  # milliunits -> 8.0
                        "targetBg": 110,
                    },
                ],
                "insulinDuration": 300,
                "carbEntry": 1,
                "maxBolus": 25000,
            },
            {
                "name": "Weekend",
                "idp": 2,
                "tDependentSegs": [
                    {
                        "startTime": 0,
                        "basalRate": 800,
                        "isf": 35,
                        "carbRatio": 10000,  # milliunits -> 10.0
                        "targetBg": 120,
                    },
                ],
                "insulinDuration": 300,
                "carbEntry": 1,
                "maxBolus": 20000,
            },
        ]
        raw_settings = _make_raw_settings(
            profiles=profiles, active_idp=1, cgm_high=240, cgm_low=70
        )
        user_id = uuid.uuid4()

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        db.execute = AsyncMock(return_value=mock_result)

        await _store_pump_settings(db, user_id, raw_settings)

        # Active profile (idp=1) should have CGM alerts
        first_stmt = db.execute.call_args_list[0][0][0]
        first_params = first_stmt.compile().params
        assert first_params["cgm_high_alert_mgdl"] == 240
        assert first_params["cgm_low_alert_mgdl"] == 70

        # Inactive profile should not
        second_stmt = db.execute.call_args_list[1][0][0]
        second_params = second_stmt.compile().params
        assert second_params["cgm_high_alert_mgdl"] is None
        assert second_params["cgm_low_alert_mgdl"] is None


class TestFetchWithRetryReturnsSettings:
    """Tests for fetch_with_retry returning settings alongside events."""

    @patch("src.services.tandem_sync.TandemSourceApi")
    def test_returns_settings_from_metadata(self, mock_api_class):
        """Test that pump settings are extracted from metadata."""
        from src.services.tandem_sync import fetch_with_retry

        mock_api = MagicMock()
        mock_api.pump_event_metadata.return_value = [
            {
                "tconnectDeviceId": "device-123",
                "serialNumber": "12345678",
                "lastUpload": {
                    "settings": {"profiles": {"activeIdp": 1, "profile": []}},
                },
            }
        ]
        mock_api.pump_events.return_value = iter([])

        events, settings_data = fetch_with_retry(
            mock_api,
            datetime.now(UTC),
            datetime.now(UTC),
        )

        assert settings_data is not None
        assert settings_data["profiles"]["activeIdp"] == 1

    @patch("src.services.tandem_sync.TandemSourceApi")
    def test_returns_none_when_no_settings(self, mock_api_class):
        """Test that None is returned when metadata has no settings."""
        from src.services.tandem_sync import fetch_with_retry

        mock_api = MagicMock()
        mock_api.pump_event_metadata.return_value = [
            {
                "tconnectDeviceId": "device-123",
                "serialNumber": "12345678",
            }
        ]
        mock_api.pump_events.return_value = iter([])

        events, settings_data = fetch_with_retry(
            mock_api,
            datetime.now(UTC),
            datetime.now(UTC),
        )

        assert settings_data is None

    @patch("src.services.tandem_sync.TandemSourceApi")
    def test_returns_none_when_last_upload_empty(self, mock_api_class):
        """Test that None is returned when lastUpload has no settings."""
        from src.services.tandem_sync import fetch_with_retry

        mock_api = MagicMock()
        mock_api.pump_event_metadata.return_value = [
            {
                "tconnectDeviceId": "device-123",
                "serialNumber": "12345678",
                "lastUpload": {},
            }
        ]
        mock_api.pump_events.return_value = iter([])

        events, settings_data = fetch_with_retry(
            mock_api,
            datetime.now(UTC),
            datetime.now(UTC),
        )

        assert settings_data is None


class TestSyncTandemProfilesIntegration:
    """Integration tests for pump profile sync in sync_tandem_for_user."""

    @patch("src.services.tandem_sync._store_pump_settings", new_callable=AsyncMock)
    @patch("src.services.tandem_sync.fetch_with_retry")
    @patch("src.services.tandem_sync.TandemSourceApi")
    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_sync_stores_profiles_alongside_events(
        self, mock_validate, mock_tandem_class, mock_fetch, mock_store_settings
    ):
        """Test that sync_tandem_for_user calls _store_pump_settings."""
        mock_validate.return_value = (True, None)
        mock_tandem_class.return_value = MagicMock()
        mock_store_settings.return_value = 2  # 2 profiles stored

        mock_fetch.return_value = (
            [
                {
                    "type": "bolus",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "units": 2.5,
                },
            ],
            {"profiles": {"activeIdp": 1, "profile": []}},
        )

        email = unique_email("tandem_profile_sync")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )
            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )
            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "tandem@example.com",
                    "password": "tandem_password",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            response = await client.post(
                "/api/integrations/tandem/sync",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["events_stored"] == 1
        assert data["profiles_stored"] == 2
        mock_store_settings.assert_called_once()

    @patch("src.services.tandem_sync._store_pump_settings", new_callable=AsyncMock)
    @patch("src.services.tandem_sync.fetch_with_retry")
    @patch("src.services.tandem_sync.TandemSourceApi")
    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_profile_failure_doesnt_block_event_sync(
        self, mock_validate, mock_tandem_class, mock_fetch, mock_store_settings
    ):
        """Test that pump settings failure doesn't block event storage."""
        mock_validate.return_value = (True, None)
        mock_tandem_class.return_value = MagicMock()
        mock_store_settings.side_effect = RuntimeError("PumpSettings parse error")

        mock_fetch.return_value = (
            [
                {
                    "type": "bolus",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "units": 1.5,
                },
            ],
            {"profiles": {"invalid": "data"}},
        )

        email = unique_email("tandem_profile_fail")
        password = "SecurePass123"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": password},
            )
            login_response = await client.post(
                "/api/auth/login",
                json={"email": email, "password": password},
            )
            session_cookie = login_response.cookies.get(settings.jwt_cookie_name)

            await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "tandem@example.com",
                    "password": "tandem_password",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            response = await client.post(
                "/api/integrations/tandem/sync",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        # Event sync should still succeed
        assert response.status_code == 200
        data = response.json()
        assert data["events_stored"] == 1
        assert data["profiles_stored"] == 0
