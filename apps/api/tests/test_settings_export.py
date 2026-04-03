"""Story 9.5: Tests for settings export capability.

Tests cover:
- Schema validation (ExportType, request, response)
- Service layer (export_user_data)
- API endpoint (POST /api/settings/export)
- Structural auth verification
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from src.config import settings
from src.schemas.settings_export import (
    ExportType,
    SettingsExportRequest,
    SettingsExportResponse,
)


def unique_email(prefix: str = "export") -> str:
    """Generate a unique email for testing."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def register_and_login(client) -> str:
    """Register a new user and return the session cookie value."""
    email = unique_email()
    password = "SecurePass123"

    await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )

    login_response = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )

    return login_response.cookies.get(settings.jwt_cookie_name)


# ── Schema tests ──


class TestSettingsExportSchemas:
    """Tests for settings export schema validation."""

    def test_valid_settings_only_request(self):
        req = SettingsExportRequest(export_type=ExportType.SETTINGS_ONLY)
        assert req.export_type == ExportType.SETTINGS_ONLY

    def test_valid_all_data_request(self):
        req = SettingsExportRequest(export_type=ExportType.ALL_DATA)
        assert req.export_type == ExportType.ALL_DATA

    def test_invalid_export_type(self):
        with pytest.raises(ValidationError):
            SettingsExportRequest(export_type="invalid")

    def test_missing_export_type(self):
        with pytest.raises(ValidationError):
            SettingsExportRequest()

    def test_response_schema(self):
        resp = SettingsExportResponse(export_data={"metadata": {}, "settings": {}})
        assert "metadata" in resp.export_data


# ── Service tests ──


class TestExportUserData:
    """Tests for export_user_data service function."""

    @pytest.mark.asyncio
    async def test_settings_only_export_structure(self):
        """Verify settings-only export has correct top-level keys."""
        from src.services.settings_export import export_user_data

        user_id = uuid.uuid4()
        db = AsyncMock()

        # Mock all queries to return None/empty
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        result = await export_user_data(user_id, db, include_data=False)

        assert "metadata" in result
        assert "settings" in result
        assert "data" not in result
        assert result["metadata"]["export_type"] == "settings_only"
        assert result["metadata"]["version"] == "1.0"

    @pytest.mark.asyncio
    async def test_all_data_export_structure(self):
        """Verify all-data export includes data and record_counts."""
        from src.services.settings_export import export_user_data

        user_id = uuid.uuid4()
        db = AsyncMock()

        # Mock queries
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        result = await export_user_data(user_id, db, include_data=True)

        assert "metadata" in result
        assert "settings" in result
        assert "data" in result
        assert result["metadata"]["export_type"] == "all_data"
        assert "record_counts" in result["metadata"]

    @pytest.mark.asyncio
    async def test_pump_event_serialization_uses_units(self):
        """Verify PumpEvent export uses 'units' (not 'value') and includes is_automated."""
        from datetime import UTC, datetime

        from src.services.settings_export import _export_all_data

        user_id = uuid.uuid4()
        db = AsyncMock()

        # Create a mock PumpEvent with all expected attributes
        mock_event = MagicMock()
        mock_event.event_type.value = "bolus"
        mock_event.event_timestamp = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
        mock_event.units = 2.5
        mock_event.duration_minutes = None
        mock_event.is_automated = False
        mock_event.source = "tandem"

        # First call returns glucose (empty), second returns pump events
        def make_result(has_events=False):
            result = MagicMock()
            if has_events:
                result.scalars.return_value.all.return_value = [mock_event]
            else:
                result.scalars.return_value.all.return_value = []
            return result

        results = [
            make_result(False),  # glucose_readings
            make_result(True),  # pump_events
            make_result(False),  # daily_briefs
            make_result(False),  # meal_analyses
            make_result(False),  # correction_analyses
            make_result(False),  # suggestion_responses
            make_result(False),  # safety_logs
            make_result(False),  # alerts
        ]
        db.execute = AsyncMock(side_effect=results)

        data = await _export_all_data(user_id, db)

        assert len(data["pump_events"]) == 1
        event = data["pump_events"][0]
        assert event["units"] == 2.5
        assert event["is_automated"] is False
        assert event["event_type"] == "bolus"
        assert event["source"] == "tandem"
        assert "value" not in event  # Ensure old attribute name is gone

    @pytest.mark.asyncio
    async def test_settings_export_contains_all_categories(self):
        """Verify settings export includes all expected configuration categories."""
        from src.services.settings_export import export_user_data

        user_id = uuid.uuid4()
        db = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        result = await export_user_data(user_id, db, include_data=False)

        settings_data = result["settings"]
        assert "target_glucose_range" in settings_data
        assert "alert_thresholds" in settings_data
        assert "escalation_config" in settings_data
        assert "brief_delivery" in settings_data
        assert "data_retention" in settings_data
        assert "ai_provider" in settings_data
        assert "integrations" in settings_data
        assert "emergency_contacts" in settings_data

    @pytest.mark.asyncio
    async def test_defaults_when_no_config_exists(self):
        """Verify default values are returned when no settings are configured."""
        from src.services.settings_export import export_user_data

        user_id = uuid.uuid4()
        db = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        result = await export_user_data(user_id, db, include_data=False)

        tgr = result["settings"]["target_glucose_range"]
        assert tgr["low_target"] == 70.0
        assert tgr["high_target"] == 180.0

        at = result["settings"]["alert_thresholds"]
        assert at["urgent_low"] == 55.0
        assert at["urgent_high"] == 250.0

        assert result["settings"]["ai_provider"] is None
        assert result["settings"]["integrations"] == []


# ── Endpoint tests ──


class TestExportEndpoint:
    """Tests for POST /api/settings/export."""

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        response = await client.post(
            "/api/settings/export",
            json={"export_type": "settings_only"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_export_type_returns_422(self, client):
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        response = await client.post(
            "/api/settings/export",
            json={"export_type": "invalid_type"},
            cookies=cookies,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_body_returns_422(self, client):
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        response = await client.post(
            "/api/settings/export",
            json={},
            cookies=cookies,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_settings_only_export(self, client):
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        response = await client.post(
            "/api/settings/export",
            json={"export_type": "settings_only"},
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()
        assert "export_data" in data
        export = data["export_data"]
        assert export["metadata"]["export_type"] == "settings_only"
        assert "settings" in export
        assert "data" not in export

    @pytest.mark.asyncio
    async def test_all_data_export(self, client):
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        response = await client.post(
            "/api/settings/export",
            json={"export_type": "all_data"},
            cookies=cookies,
        )
        assert response.status_code == 200
        data = response.json()
        export = data["export_data"]
        assert export["metadata"]["export_type"] == "all_data"
        assert "settings" in export
        assert "data" in export
        assert "record_counts" in export["metadata"]

    @pytest.mark.asyncio
    async def test_export_does_not_include_credentials(self, client):
        """Verify no API keys or passwords appear in the export."""
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        response = await client.post(
            "/api/settings/export",
            json={"export_type": "settings_only"},
            cookies=cookies,
        )
        assert response.status_code == 200
        export_str = str(response.json())
        assert "encrypted_api_key" not in export_str
        assert "encrypted_username" not in export_str
        assert "encrypted_password" not in export_str

    @pytest.mark.asyncio
    async def test_export_metadata_has_date_and_version(self, client):
        cookie = await register_and_login(client)
        cookies = {settings.jwt_cookie_name: cookie}

        response = await client.post(
            "/api/settings/export",
            json={"export_type": "settings_only"},
            cookies=cookies,
        )
        assert response.status_code == 200
        metadata = response.json()["export_data"]["metadata"]
        assert "export_date" in metadata
        assert metadata["version"] == "1.0"


# ── Structural tests ──


class TestExportEndpointStructure:
    """Verify the export endpoint has correct auth dependencies."""

    def test_export_endpoint_has_role_checker(self):
        """POST /api/settings/export must have RoleChecker."""
        from src.core.auth import RoleChecker
        from src.routers.settings import router

        export_routes = [
            r
            for r in router.routes
            if hasattr(r, "path")
            and r.path == "/api/settings/export"
            and hasattr(r, "methods")
            and "POST" in r.methods
        ]
        assert len(export_routes) == 1

        route = export_routes[0]
        dep_classes = [type(d.dependency) for d in route.dependencies]
        assert RoleChecker in dep_classes
