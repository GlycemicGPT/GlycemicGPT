"""Story 6.2: Tests for predictive alert engine."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from src.config import settings
from src.core.units import GlucoseUnit
from src.models.alert import AlertSeverity, AlertType
from src.services.predictive_alerts import (
    calculate_trajectory,
    check_iob_threshold,
    check_threshold_crossings,
    determine_severity,
)


def unique_email(prefix: str = "test") -> str:
    """Generate a unique email for testing."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def register_and_login(client: AsyncClient) -> str:
    """Register a new user and return the session cookie value."""
    email = unique_email("alerts")
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


# ── Trajectory calculation tests ──


class TestCalculateTrajectory:
    """Tests for glucose trajectory calculation."""

    def test_flat_trajectory(self):
        """Flat trend rate should predict same value at all horizons."""
        trajectory = calculate_trajectory(100.0, 0.0)
        assert trajectory.current_value == 100.0
        assert trajectory.predictions[20] == 100.0
        assert trajectory.predictions[30] == 100.0
        assert trajectory.predictions[45] == 100.0

    def test_falling_trajectory(self):
        """Negative trend rate should predict decreasing values."""
        trajectory = calculate_trajectory(100.0, -2.0)
        assert trajectory.predictions[20] == 60.0  # 100 - 2*20
        assert trajectory.predictions[30] == 40.0  # 100 - 2*30
        assert trajectory.predictions[45] == 10.0  # 100 - 2*45

    def test_rising_trajectory(self):
        """Positive trend rate should predict increasing values."""
        trajectory = calculate_trajectory(150.0, 1.5)
        assert trajectory.predictions[20] == 180.0  # 150 + 1.5*20
        assert trajectory.predictions[30] == 195.0  # 150 + 1.5*30
        assert trajectory.predictions[45] == 217.5  # 150 + 1.5*45

    def test_clamps_to_zero(self):
        """Predicted values should not go below 0."""
        trajectory = calculate_trajectory(20.0, -3.0)
        assert trajectory.predictions[20] == 0.0  # 20 - 3*20 = -40 -> 0
        assert trajectory.predictions[30] == 0.0

    def test_custom_horizons(self):
        """Should support custom prediction horizons."""
        trajectory = calculate_trajectory(100.0, -1.0, horizons=[10, 60])
        assert 10 in trajectory.predictions
        assert 60 in trajectory.predictions
        assert 20 not in trajectory.predictions

    def test_stores_trend_rate(self):
        """Trajectory should preserve the trend rate."""
        trajectory = calculate_trajectory(100.0, -1.5)
        assert trajectory.trend_rate == -1.5


# ── Severity determination tests ──


class TestDetermineSeverity:
    """Tests for severity determination with IoB escalation."""

    def test_base_severity_low_warning(self):
        """LOW_WARNING should default to WARNING."""
        severity = determine_severity(AlertType.LOW_WARNING, None, 3.0)
        assert severity == AlertSeverity.WARNING

    def test_base_severity_low_urgent(self):
        """LOW_URGENT should default to URGENT."""
        severity = determine_severity(AlertType.LOW_URGENT, None, 3.0)
        assert severity == AlertSeverity.URGENT

    def test_base_severity_high_warning(self):
        """HIGH_WARNING should default to WARNING."""
        severity = determine_severity(AlertType.HIGH_WARNING, None, 3.0)
        assert severity == AlertSeverity.WARNING

    def test_iob_escalation_warning_to_urgent(self):
        """High IoB should escalate LOW_WARNING from WARNING to URGENT."""
        # iob_threshold=3.0, factor=0.8, so 2.4 triggers escalation
        severity = determine_severity(AlertType.LOW_WARNING, 2.5, 3.0)
        assert severity == AlertSeverity.URGENT

    def test_iob_escalation_urgent_to_emergency(self):
        """High IoB should escalate LOW_URGENT from URGENT to EMERGENCY."""
        severity = determine_severity(AlertType.LOW_URGENT, 3.0, 3.0)
        assert severity == AlertSeverity.EMERGENCY

    def test_no_escalation_low_iob(self):
        """Low IoB should not escalate severity."""
        severity = determine_severity(AlertType.LOW_WARNING, 1.0, 3.0)
        assert severity == AlertSeverity.WARNING

    def test_no_escalation_for_high_alerts(self):
        """IoB escalation should not apply to HIGH alerts."""
        severity = determine_severity(AlertType.HIGH_WARNING, 5.0, 3.0)
        assert severity == AlertSeverity.WARNING

    def test_no_escalation_none_iob(self):
        """None IoB should not cause escalation."""
        severity = determine_severity(AlertType.LOW_WARNING, None, 3.0)
        assert severity == AlertSeverity.WARNING


# ── Threshold crossing tests ──


class TestCheckThresholdCrossings:
    """Tests for threshold crossing detection."""

    def _make_thresholds(self, **overrides):
        """Create mock thresholds with defaults."""
        mock = MagicMock()
        mock.urgent_low = overrides.get("urgent_low", 55.0)
        mock.low_warning = overrides.get("low_warning", 70.0)
        mock.high_warning = overrides.get("high_warning", 180.0)
        mock.urgent_high = overrides.get("urgent_high", 250.0)
        mock.iob_warning = overrides.get("iob_warning", 3.0)
        return mock

    def test_no_crossings_in_range(self):
        """Normal glucose should produce no alerts."""
        trajectory = calculate_trajectory(100.0, 0.0)
        thresholds = self._make_thresholds()
        candidates = check_threshold_crossings(trajectory, thresholds, None)
        assert len(candidates) == 0

    def test_current_low_warning(self):
        """Current glucose at low_warning should trigger LOW_WARNING."""
        trajectory = calculate_trajectory(70.0, 0.0)
        thresholds = self._make_thresholds()
        candidates = check_threshold_crossings(trajectory, thresholds, None)
        assert len(candidates) == 1
        assert candidates[0].alert_type == AlertType.LOW_WARNING
        assert candidates[0].source == "current"

    def test_current_urgent_low(self):
        """Current glucose at urgent_low should trigger LOW_URGENT."""
        trajectory = calculate_trajectory(50.0, 0.0)
        thresholds = self._make_thresholds()
        candidates = check_threshold_crossings(trajectory, thresholds, None)
        assert len(candidates) == 1
        assert candidates[0].alert_type == AlertType.LOW_URGENT

    def test_message_mgdl_unchanged_from_legacy(self):
        """The persisted message is byte-identical for mg/dL (default)."""
        trajectory = calculate_trajectory(50.0, 0.0)
        thresholds = self._make_thresholds()
        candidates = check_threshold_crossings(trajectory, thresholds, None)
        assert candidates[0].message == "Urgent low glucose: 50 mg/dL (threshold: 55)"

    def test_message_renders_mmol(self):
        """The persisted message renders in the patient's unit
        (50->2.8, threshold 55->3.1) when the unit is mmol/L."""
        trajectory = calculate_trajectory(50.0, 0.0)
        thresholds = self._make_thresholds()
        candidates = check_threshold_crossings(
            trajectory, thresholds, None, GlucoseUnit.MMOL
        )
        assert candidates[0].message == (
            "Urgent low glucose: 2.8 mmol/L (threshold: 3.1)"
        )

    def test_predicted_message_renders_mmol(self):
        """Predicted messages convert the predicted, current, and
        threshold figures to the patient's unit."""
        # Falling fast: current 90 -> predicted low within the horizon.
        trajectory = calculate_trajectory(90.0, -2.0)
        thresholds = self._make_thresholds()
        candidates = check_threshold_crossings(
            trajectory, thresholds, None, GlucoseUnit.MMOL
        )
        predicted = [c for c in candidates if c.source == "predictive"]
        assert predicted
        assert "mmol/L" in predicted[0].message
        assert "mg/dL" not in predicted[0].message

    def test_current_high_warning(self):
        """Current glucose at high_warning should trigger HIGH_WARNING."""
        trajectory = calculate_trajectory(180.0, 0.0)
        thresholds = self._make_thresholds()
        candidates = check_threshold_crossings(trajectory, thresholds, None)
        assert len(candidates) == 1
        assert candidates[0].alert_type == AlertType.HIGH_WARNING

    def test_current_urgent_high(self):
        """Current glucose at urgent_high should trigger HIGH_URGENT."""
        trajectory = calculate_trajectory(260.0, 0.0)
        thresholds = self._make_thresholds()
        candidates = check_threshold_crossings(trajectory, thresholds, None)
        assert len(candidates) == 1
        assert candidates[0].alert_type == AlertType.HIGH_URGENT

    def test_predicted_low_crossing(self):
        """Dropping glucose should trigger predictive low warning."""
        # 95 mg/dL falling at 2 mg/dL/min = 55 at 20min, below low_warning (70) at 13min
        trajectory = calculate_trajectory(95.0, -2.0)
        thresholds = self._make_thresholds()
        candidates = check_threshold_crossings(trajectory, thresholds, None)
        # Should get LOW_WARNING (predicted at 20min: 55) and LOW_URGENT (at 20min: 55)
        types = {c.alert_type for c in candidates}
        assert AlertType.LOW_URGENT in types
        assert all(c.source == "predictive" for c in candidates)

    def test_predicted_high_crossing(self):
        """Rising glucose should trigger predictive high warning."""
        # 160 mg/dL rising at 1.5 mg/dL/min = 190 at 20min
        trajectory = calculate_trajectory(160.0, 1.5)
        thresholds = self._make_thresholds()
        candidates = check_threshold_crossings(trajectory, thresholds, None)
        types = {c.alert_type for c in candidates}
        assert AlertType.HIGH_WARNING in types

    def test_no_duplicate_types(self):
        """Current alert should suppress predicted alert of same type."""
        # Current is already LOW_URGENT, should not also get predicted LOW_URGENT
        trajectory = calculate_trajectory(50.0, -2.0)
        thresholds = self._make_thresholds()
        candidates = check_threshold_crossings(trajectory, thresholds, None)
        type_counts = {}
        for c in candidates:
            type_counts[c.alert_type] = type_counts.get(c.alert_type, 0) + 1
        for count in type_counts.values():
            assert count == 1

    def test_predicted_includes_prediction_minutes(self):
        """Predictive alerts should include prediction timeframe."""
        trajectory = calculate_trajectory(160.0, 1.5)
        thresholds = self._make_thresholds()
        candidates = check_threshold_crossings(trajectory, thresholds, None)
        predictive = [c for c in candidates if c.source == "predictive"]
        for c in predictive:
            assert c.prediction_minutes is not None
            assert c.predicted_value is not None


# ── IoB threshold tests ──


class TestCheckIoBThreshold:
    """Tests for IoB threshold checking."""

    def test_below_threshold(self):
        """IoB below threshold should return None."""
        result = check_iob_threshold(100.0, 2.0, 3.0, -1.0)
        assert result is None

    def test_at_threshold(self):
        """IoB at threshold should trigger alert."""
        result = check_iob_threshold(100.0, 3.0, 3.0, -1.0)
        assert result is not None
        assert result.alert_type == AlertType.IOB_WARNING
        assert result.source == "iob"

    def test_above_threshold(self):
        """IoB above threshold should trigger alert."""
        result = check_iob_threshold(100.0, 5.0, 3.0, -1.0)
        assert result is not None
        assert result.iob_value == 5.0


# ── Service-level tests (with mocked DB) ──


class TestEvaluateAlertsForUser:
    """Tests for the full alert evaluation pipeline."""

    @pytest.mark.asyncio
    async def test_no_readings_returns_empty(self):
        """Should return empty list when no glucose readings exist."""
        from src.services.predictive_alerts import evaluate_alerts_for_user

        user_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        result = await evaluate_alerts_for_user(mock_db, user_id)
        assert result == []

    @pytest.mark.asyncio
    async def test_stale_reading_returns_empty(self):
        """Should skip alert evaluation for stale readings."""
        from src.services.predictive_alerts import evaluate_alerts_for_user

        user_id = uuid.uuid4()
        stale_reading = MagicMock()
        stale_reading.value = 50
        stale_reading.trend_rate = -2.0
        stale_reading.reading_timestamp = datetime.now(UTC) - timedelta(minutes=15)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = stale_reading

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        result = await evaluate_alerts_for_user(mock_db, user_id)
        assert result == []

    @pytest.mark.asyncio
    async def test_low_glucose_creates_alert(self):
        """Should create a LOW_URGENT alert for very low glucose."""
        from src.services.predictive_alerts import evaluate_alerts_for_user

        user_id = uuid.uuid4()

        # Fresh low glucose reading
        low_reading = MagicMock()
        low_reading.value = 50
        low_reading.trend_rate = -1.0
        low_reading.reading_timestamp = datetime.now(UTC) - timedelta(minutes=2)

        # Mock thresholds
        mock_thresholds = MagicMock()
        mock_thresholds.urgent_low = 55.0
        mock_thresholds.low_warning = 70.0
        mock_thresholds.high_warning = 180.0
        mock_thresholds.urgent_high = 250.0
        mock_thresholds.iob_warning = 3.0

        # First execute call returns the glucose reading
        reading_result = MagicMock()
        reading_result.scalar_one_or_none.return_value = low_reading

        # Subsequent execute calls for has_recent_alert return no duplicates
        dedup_result = MagicMock()
        dedup_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute.side_effect = [reading_result, dedup_result]
        mock_db.add = MagicMock()  # add() is synchronous

        with (
            patch(
                "src.services.predictive_alerts.get_or_create_thresholds",
                new_callable=AsyncMock,
                return_value=mock_thresholds,
            ),
            patch(
                "src.services.predictive_alerts.get_iob_projection",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.services.predictive_alerts.get_user_dia",
                new_callable=AsyncMock,
                return_value=4.0,
            ),
            patch(
                "src.services.predictive_alerts.resolve_glucose_unit",
                new_callable=AsyncMock,
                return_value=GlucoseUnit.MGDL,
            ),
        ):
            result = await evaluate_alerts_for_user(mock_db, user_id)

        assert len(result) == 1
        assert result[0].alert_type == AlertType.LOW_URGENT
        # Verify commit was called
        mock_db.commit.assert_awaited_once()


# ── Deduplication tests ──


class TestHasRecentAlert:
    """Tests for alert deduplication."""

    @pytest.mark.asyncio
    async def test_no_recent_alert(self):
        """Should return False when no recent alert exists."""
        from src.services.predictive_alerts import has_recent_alert

        user_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        result = await has_recent_alert(mock_db, user_id, AlertType.LOW_WARNING)
        assert result is False

    @pytest.mark.asyncio
    async def test_recent_alert_exists(self):
        """Should return True when a recent alert exists."""
        from src.services.predictive_alerts import has_recent_alert

        user_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = uuid.uuid4()

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        result = await has_recent_alert(mock_db, user_id, AlertType.LOW_WARNING)
        assert result is True


# ── Endpoint tests ──


class TestGetActiveAlertsEndpoint:
    """Tests for GET /api/alerts/active."""

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get("/api/alerts/active")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_authenticated_returns_empty_list(self, client):
        """New user should have no active alerts."""
        cookie = await register_and_login(client)
        response = await client.get(
            "/api/alerts/active",
            cookies={settings.jwt_cookie_name: cookie},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["alerts"] == []
        assert data["count"] == 0


class TestAcknowledgeAlertEndpoint:
    """Tests for PATCH /api/alerts/{alert_id}/acknowledge."""

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        fake_id = str(uuid.uuid4())
        response = await client.patch(f"/api/alerts/{fake_id}/acknowledge")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_nonexistent_alert_returns_404(self, client):
        cookie = await register_and_login(client)
        fake_id = str(uuid.uuid4())
        response = await client.patch(
            f"/api/alerts/{fake_id}/acknowledge",
            cookies={settings.jwt_cookie_name: cookie},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_422(self, client):
        cookie = await register_and_login(client)
        response = await client.patch(
            "/api/alerts/not-a-uuid/acknowledge",
            cookies={settings.jwt_cookie_name: cookie},
        )
        assert response.status_code == 422
