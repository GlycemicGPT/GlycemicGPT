"""Story 3.4, 3.5, & 15.8: Tests for Tandem pump data ingestion, Control-IQ parsing,
and pump profile sync."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

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

    # Issue #1: Test country routing (replaces the old EU-region test now
    # that we route by ISO-3166 country and derive the cloud bucket).
    @patch("src.services.tandem_sync.TandemSourceApi")
    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_tandem_connect_with_eu_cloud_country(
        self, mock_validate, mock_tandem_class
    ):
        """Test connecting Tandem with an EU-cloud country (GB)."""
        mock_validate.return_value = (True, None)
        mock_api = MagicMock()
        mock_tandem_class.return_value = mock_api

        email = unique_email("tandem_gb_country")
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

            # Connect with GB (United Kingdom) -> routes to EU cloud
            response = await client.post(
                "/api/integrations/tandem",
                json={
                    "username": "tandem@example.com",
                    "password": "tandem_password",
                    "country": "GB",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        # Verify validate was called with the country (the validator derives
        # the cloud bucket internally via country_to_cloud).
        mock_validate.assert_called_with(
            "tandem@example.com",
            "tandem_password",
            "GB",
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


# ============================================================================
# Per-user Tandem sync control (toggle + interval) + scheduler due-checking
# ============================================================================


async def _register_login_connect_tandem(
    client: AsyncClient,
    email: str,
    *,
    password: str = "SecurePass123",
    country: str = "US",
) -> str:
    """Register + login + connect Tandem. Returns the session cookie.

    Caller MUST have ``validate_tandem_credentials`` patched to succeed.
    """
    await client.post("/api/auth/register", json={"email": email, "password": password})
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    cookie = login.cookies.get(settings.jwt_cookie_name)
    assert cookie
    resp = await client.post(
        "/api/integrations/tandem",
        json={"username": "t@example.com", "password": "pw", "country": country},
        cookies={settings.jwt_cookie_name: cookie},
    )
    assert resp.status_code == 201, resp.text
    return cookie


class TestTandemSyncPerUserControl:
    """The per-user sync toggle + interval surfaced on /tandem/sync/*."""

    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_status_defaults_when_no_state_row(self, mock_validate):
        """A connected user with no state row defaults to enabled@60 --
        the backward-compatible default (everyone was synced before)."""
        mock_validate.return_value = (True, None)
        email = unique_email("tsync_default")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _register_login_connect_tandem(client, email)
            resp = await client.get(
                "/api/integrations/tandem/sync/status",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["enabled"] is True
        assert data["sync_interval_minutes"] == 60
        assert data["events_pulled_total"] == 0
        assert data["needs_country_reselect"] is False

    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_settings_upsert_persists(self, mock_validate):
        """PUT settings creates the row and round-trips through status."""
        mock_validate.return_value = (True, None)
        email = unique_email("tsync_persist")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _register_login_connect_tandem(client, email)
            put = await client.put(
                "/api/integrations/tandem/sync/settings",
                json={"enabled": False, "sync_interval_minutes": 120},
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert put.status_code == 200, put.text
            assert put.json()["enabled"] is False
            assert put.json()["sync_interval_minutes"] == 120

            # Re-enable with a different interval.
            put2 = await client.put(
                "/api/integrations/tandem/sync/settings",
                json={"enabled": True, "sync_interval_minutes": 30},
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert put2.status_code == 200, put2.text

            status = await client.get(
                "/api/integrations/tandem/sync/status",
                cookies={settings.jwt_cookie_name: cookie},
            )
        data = status.json()
        assert data["enabled"] is True
        assert data["sync_interval_minutes"] == 30

    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_settings_interval_bounds(self, mock_validate):
        """Interval is bounded to [15, 1440]; out-of-range -> 422."""
        mock_validate.return_value = (True, None)
        email = unique_email("tsync_bounds")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _register_login_connect_tandem(client, email)

            async def _put(interval: int) -> int:
                r = await client.put(
                    "/api/integrations/tandem/sync/settings",
                    json={"enabled": True, "sync_interval_minutes": interval},
                    cookies={settings.jwt_cookie_name: cookie},
                )
                return r.status_code

            assert await _put(15) == 200
            assert await _put(1440) == 200
            assert await _put(60) == 200
            assert await _put(14) == 422
            assert await _put(1441) == 422
            assert await _put(0) == 422

    async def test_settings_404_when_not_configured(self):
        """PUT settings with no Tandem integration -> 404."""
        email = unique_email("tsync_nocfg")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": "SecurePass123"},
            )
            login = await client.post(
                "/api/auth/login",
                json={"email": email, "password": "SecurePass123"},
            )
            cookie = login.cookies.get(settings.jwt_cookie_name)
            resp = await client.put(
                "/api/integrations/tandem/sync/settings",
                json={"enabled": True, "sync_interval_minutes": 60},
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 404, resp.text

    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_settings_409_legacy_region(self, mock_validate):
        """A legacy 'EU' region credential blocks enabling sync with 409
        until the user reconnects with a country -- mirrors the sync 409."""
        mock_validate.return_value = (True, None)
        email = unique_email("tsync_legacy")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _register_login_connect_tandem(client, email)

            # Force the stored region to the legacy bucket label.
            from sqlalchemy import update

            from src.database import get_session_maker
            from src.models.integration import (
                IntegrationCredential,
                IntegrationType,
            )
            from src.models.user import User

            async with get_session_maker()() as db:
                user_id = (
                    await db.execute(select(User.id).where(User.email == email))
                ).scalar_one()
                await db.execute(
                    update(IntegrationCredential)
                    .where(
                        IntegrationCredential.user_id == user_id,
                        IntegrationCredential.integration_type
                        == IntegrationType.TANDEM,
                    )
                    .values(region="EU")
                )
                await db.commit()

            # ENABLING on a legacy region is blocked with 409.
            resp = await client.put(
                "/api/integrations/tandem/sync/settings",
                json={"enabled": True, "sync_interval_minutes": 60},
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert resp.status_code == 409, resp.text

            # DISABLING must still be allowed even on a legacy region -- a
            # user has to be able to turn sync off without reconnecting.
            off = await client.put(
                "/api/integrations/tandem/sync/settings",
                json={"enabled": False, "sync_interval_minutes": 60},
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert off.status_code == 200, off.text
            assert off.json()["enabled"] is False
            assert off.json()["needs_country_reselect"] is True

            # Status surfaces the needs_country_reselect flag.
            status = await client.get(
                "/api/integrations/tandem/sync/status",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert status.json()["needs_country_reselect"] is True

    @pytest.mark.parametrize(
        "country",
        [
            "US",  # US cloud
            "CA",  # US cloud
            "MX",  # US cloud
            "GB",  # EU cloud
            "DE",  # EU cloud
            "AU",  # EU cloud
            "IL",  # EU cloud
        ],
    )
    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_per_user_control_works_across_regions(self, mock_validate, country):
        """The per-user sync control is region-agnostic: every valid country
        (both Tandem cloud clusters) gets working status + settings, and a
        valid country must NEVER trip the legacy needs_country_reselect flag
        (that is reserved for the old 'EU'/'US' bucket labels)."""
        mock_validate.return_value = (True, None)
        email = unique_email(f"tsync_region_{country.lower()}")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _register_login_connect_tandem(
                client, email, country=country
            )
            status = await client.get(
                "/api/integrations/tandem/sync/status",
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert status.status_code == 200, status.text
            data = status.json()
            # Default control applies regardless of region.
            assert data["enabled"] is True
            assert data["sync_interval_minutes"] == 60
            # A valid ISO country is NOT a legacy bucket label.
            assert data["needs_country_reselect"] is False

            # Settings update succeeds (no legacy-region 409) for every region.
            put = await client.put(
                "/api/integrations/tandem/sync/settings",
                json={"enabled": True, "sync_interval_minutes": 90},
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert put.status_code == 200, put.text
            assert put.json()["sync_interval_minutes"] == 90


class TestTandemSyncSchedulerDueLogic:
    """The scheduler's per-user due-check + enabled gating."""

    def test_is_due(self):
        from src.services.scheduler import _tandem_is_due

        now = datetime.now(UTC)
        assert _tandem_is_due(None, 60, now=now) is True  # never synced
        assert _tandem_is_due(now - timedelta(minutes=30), 60, now=now) is False
        assert _tandem_is_due(now - timedelta(minutes=90), 60, now=now) is True
        # Naive timestamp is treated as UTC, not crashed on.
        assert (
            _tandem_is_due(
                (now - timedelta(minutes=90)).replace(tzinfo=None), 60, now=now
            )
            is True
        )

    @patch("src.services.scheduler.sync_tandem_for_user")
    async def test_tick_honors_enabled_and_due(self, mock_sync):
        """Scheduler tick behavior:
        - no state row -> enabled@default -> synced (backward compat);
        - explicitly disabled -> skipped;
        - enabled but synced recently (last_sync_at) -> skipped;
        - ERROR-status user with a RECENT last_attempt_at -> skipped (the
          retry-amplification fix: failing users pace by attempt, not by the
          success-only last_sync_at, so they aren't hammered every tick).
        Also verifies the attempt is recorded: the no-row user gets a state
        row auto-created with last_attempt_at stamped + events_pulled_total
        bumped."""

        from src.core.security import hash_password
        from src.database import get_session_maker
        from src.models.integration import (
            IntegrationCredential,
            IntegrationStatus,
            IntegrationType,
        )
        from src.models.tandem_sync_state import TandemSyncState
        from src.models.user import User, UserRole
        from src.services.scheduler import sync_all_tandem_users

        mock_sync.return_value = {"events_fetched": 7, "events_stored": 5}

        now = datetime.now(UTC)
        ids: dict[str, uuid.UUID] = {}
        async with get_session_maker()() as db:
            for key, status_, last_sync, state_kwargs in [
                # no state row -> enabled@default -> due
                ("norow", IntegrationStatus.CONNECTED, None, None),
                # opted out -> skip
                ("disabled", IntegrationStatus.CONNECTED, None, {"enabled": False}),
                # just synced -> skip
                (
                    "notdue",
                    IntegrationStatus.CONNECTED,
                    now,
                    {"enabled": True, "sync_interval_minutes": 60},
                ),
                # ERROR with a recent ATTEMPT -> skip (never succeeded, so
                # last_sync_at is None; pre-fix this would sync every tick).
                (
                    "errored_recent",
                    IntegrationStatus.ERROR,
                    None,
                    {
                        "enabled": True,
                        "sync_interval_minutes": 60,
                        "last_attempt_at": now,
                    },
                ),
            ]:
                user = User(
                    email=unique_email(f"tsched_{key}"),
                    hashed_password=hash_password("SecurePass123"),
                    role=UserRole.DIABETIC,
                )
                db.add(user)
                await db.flush()
                ids[key] = user.id
                db.add(
                    IntegrationCredential(
                        user_id=user.id,
                        integration_type=IntegrationType.TANDEM,
                        encrypted_username="x",
                        encrypted_password="x",
                        region="US",
                        status=status_,
                        last_sync_at=last_sync,
                    )
                )
                if state_kwargs is not None:
                    db.add(TandemSyncState(user_id=user.id, **state_kwargs))
            await db.commit()

        await sync_all_tandem_users()

        synced_ids = {call.args[1] for call in mock_sync.await_args_list}
        # Robust against other users polluting the shared dev DB: assert
        # membership for OUR seeded users, not exact counts.
        assert ids["norow"] in synced_ids, "no-row user must sync (backward compat)"
        assert ids["disabled"] not in synced_ids, "disabled user must be skipped"
        assert ids["notdue"] not in synced_ids, "not-due user must be skipped"
        assert ids["errored_recent"] not in synced_ids, (
            "ERROR user with a recent attempt must NOT be re-synced every tick"
        )

        # The no-row user's attempt was recorded: a row now exists with
        # last_attempt_at stamped and events_pulled_total bumped by the 5
        # events the mock reported stored.
        async with get_session_maker()() as db:
            row = (
                await db.execute(
                    select(TandemSyncState).where(
                        TandemSyncState.user_id == ids["norow"]
                    )
                )
            ).scalar_one()
            assert row.last_attempt_at is not None
            assert row.events_pulled_total == 5


class TestTandemSyncAvailability:
    """GET /tandem/sync/availability reports the cloud's data date range."""

    @patch("src.services.tandem_sync.TandemSourceApi")
    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_availability_returns_range_ignoring_bogus_max(
        self, mock_validate, mock_api_class
    ):
        """earliest = minDateWithEvents, latest = lastUpload.lastUploadedAt.
        The bogus far-future maxDateWithEvents (2066) must be ignored."""
        mock_validate.return_value = (True, None)
        mock_api = MagicMock()
        mock_api.pump_event_metadata.return_value = [
            {
                "tconnectDeviceId": 945039,
                "minDateWithEvents": "2018-07-18T22:35:14",
                "maxDateWithEvents": "2066-05-24T04:59:14",  # bogus -> ignore
                "lastUpload": {"lastUploadedAt": "2026-04-15T01:35:01.687"},
            }
        ]
        mock_api_class.return_value = mock_api

        email = unique_email("tsync_avail")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _register_login_connect_tandem(client, email)
            resp = await client.get(
                "/api/integrations/tandem/sync/availability",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200, resp.text
        d = resp.json()
        assert d["pump_count"] == 1
        assert d["earliest"].startswith("2018-07-18")
        # latest is the last-upload date, NOT the bogus 2066 maxDateWithEvents.
        assert d["latest"].startswith("2026-04-15")
        assert "2066" not in (d["latest"] or "")

    async def test_availability_404_when_not_configured(self):
        email = unique_email("tsync_avail_nocfg")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": "SecurePass123"},
            )
            login = await client.post(
                "/api/auth/login",
                json={"email": email, "password": "SecurePass123"},
            )
            cookie = login.cookies.get(settings.jwt_cookie_name)
            resp = await client.get(
                "/api/integrations/tandem/sync/availability",
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 404, resp.text


class TestTandemImport:
    """POST /tandem/sync/import: one-time manual custom-range pull."""

    @patch("src.services.tandem_sync.fetch_with_retry")
    @patch("src.services.tandem_sync.TandemSourceApi")
    @patch("src.routers.integrations.validate_tandem_credentials")
    async def test_import_uses_explicit_range(
        self, mock_validate, mock_api_class, mock_fetch
    ):
        """The import passes the user's explicit start/end through to the
        fetch (NOT a now-anchored window), and stores what comes back."""
        mock_validate.return_value = (True, None)
        mock_api_class.return_value = MagicMock()
        mock_fetch.return_value = (
            [
                {
                    "type": "bolus",
                    "timestamp": "2026-04-10T12:00:00+00:00",
                    "units": 2.0,
                }
            ],
            None,
        )
        email = unique_email("tsync_import")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie = await _register_login_connect_tandem(client, email)
            resp = await client.post(
                "/api/integrations/tandem/sync/import",
                json={
                    "start_date": "2026-04-01T00:00:00+00:00",
                    "end_date": "2026-04-16T00:00:00+00:00",
                },
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["events_stored"] == 1
        # fetch_with_retry(api, start_date, end_date) -- verify the explicit
        # range reached it (run via asyncio.to_thread, so use call_args).
        assert mock_fetch.call_args is not None
        _api, start_arg, end_arg = mock_fetch.call_args.args[:3]
        assert start_arg.date().isoformat() == "2026-04-01"
        assert end_arg.date().isoformat() == "2026-04-16"

    @pytest.mark.parametrize(
        "start,end",
        [
            # end before start
            ("2026-04-16T00:00:00+00:00", "2026-04-01T00:00:00+00:00"),
            # end in the far future
            ("2026-04-01T00:00:00+00:00", "2099-01-01T00:00:00+00:00"),
            # span > 366 days
            ("2024-01-01T00:00:00+00:00", "2025-06-01T00:00:00+00:00"),
        ],
    )
    async def test_import_rejects_bad_range_422(self, start, end):
        email = unique_email("tsync_import_bad")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": "SecurePass123"},
            )
            login = await client.post(
                "/api/auth/login",
                json={"email": email, "password": "SecurePass123"},
            )
            cookie = login.cookies.get(settings.jwt_cookie_name)
            resp = await client.post(
                "/api/integrations/tandem/sync/import",
                json={"start_date": start, "end_date": end},
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 422, resp.text

    async def test_import_404_when_not_configured(self):
        email = unique_email("tsync_import_nocfg")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/auth/register",
                json={"email": email, "password": "SecurePass123"},
            )
            login = await client.post(
                "/api/auth/login",
                json={"email": email, "password": "SecurePass123"},
            )
            cookie = login.cookies.get(settings.jwt_cookie_name)
            resp = await client.post(
                "/api/integrations/tandem/sync/import",
                json={
                    "start_date": "2026-04-01T00:00:00+00:00",
                    "end_date": "2026-04-16T00:00:00+00:00",
                },
                cookies={settings.jwt_cookie_name: cookie},
            )
        assert resp.status_code == 404, resp.text
