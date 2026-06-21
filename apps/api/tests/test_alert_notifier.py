"""Story 7.2: Tests for alert delivery via Telegram."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.units import GlucoseUnit
from src.models.alert import Alert, AlertSeverity, AlertType
from src.services.alert_notifier import (
    SEVERITY_EMOJI,
    format_alert_message,
    format_escalation_contact_message,
    notify_user_of_alerts,
    trend_description,
)
from src.services.telegram_bot import TelegramBotError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_alert(
    alert_type: AlertType = AlertType.LOW_URGENT,
    severity: AlertSeverity = AlertSeverity.URGENT,
    current_value: float = 55.0,
    trend_rate: float | None = -2.0,
    predicted_value: float | None = 45.0,
    prediction_minutes: int | None = 30,
    iob_value: float | None = 2.5,
) -> MagicMock:
    """Create a mock Alert for testing."""
    alert = MagicMock(spec=Alert)
    alert.id = uuid.uuid4()
    alert.user_id = uuid.uuid4()
    alert.alert_type = alert_type
    alert.severity = severity
    alert.current_value = current_value
    alert.trend_rate = trend_rate
    alert.predicted_value = predicted_value
    alert.prediction_minutes = prediction_minutes
    alert.iob_value = iob_value
    alert.message = "Test alert message"
    alert.source = "predictive"
    alert.created_at = datetime.now(UTC)
    alert.expires_at = datetime.now(UTC) + timedelta(hours=1)
    return alert


# ---------------------------------------------------------------------------
# Trend description tests (pure function)
# ---------------------------------------------------------------------------
class TestTrendDescription:
    """Tests for trend_description()."""

    def test_none_returns_unknown(self):
        assert trend_description(None) == "unknown"

    def test_rising_fast(self):
        result = trend_description(3.5)
        assert "rising fast" in result

    def test_rising(self):
        result = trend_description(2.0)
        assert "rising" in result
        assert "fast" not in result
        assert "slowly" not in result

    def test_rising_slowly(self):
        result = trend_description(0.7)
        assert "rising slowly" in result

    def test_stable(self):
        result = trend_description(0.0)
        assert "stable" in result

    def test_falling_slowly(self):
        result = trend_description(-0.7)
        assert "falling slowly" in result

    def test_falling(self):
        result = trend_description(-2.0)
        assert "falling" in result
        assert "fast" not in result
        assert "slowly" not in result

    def test_falling_fast(self):
        result = trend_description(-3.5)
        assert "falling fast" in result

    # Boundary value tests
    def test_boundary_exactly_3_0_is_rising(self):
        result = trend_description(3.0)
        assert "rising" in result
        assert "fast" not in result

    def test_boundary_exactly_1_0_is_rising_slowly(self):
        result = trend_description(1.0)
        assert "rising slowly" in result

    def test_boundary_exactly_0_5_is_stable(self):
        result = trend_description(0.5)
        assert "stable" in result

    def test_boundary_exactly_neg_0_5_is_stable(self):
        result = trend_description(-0.5)
        assert "stable" in result

    def test_boundary_exactly_neg_1_0_is_falling_slowly(self):
        result = trend_description(-1.0)
        assert "falling slowly" in result

    def test_boundary_exactly_neg_3_0_is_falling(self):
        result = trend_description(-3.0)
        assert "falling" in result
        assert "fast" not in result


# ---------------------------------------------------------------------------
# Format alert message tests (pure function)
# ---------------------------------------------------------------------------
class TestFormatAlertMessage:
    """Tests for format_alert_message()."""

    def test_low_urgent_message_structure(self):
        alert = make_alert(AlertType.LOW_URGENT, AlertSeverity.URGENT)
        msg = format_alert_message(alert)
        assert "Urgent Low Glucose" in msg
        assert "55 mg/dL" in msg
        assert "falling" in msg
        assert "fast-acting carbs" in msg

    def test_high_warning_message_structure(self):
        alert = make_alert(
            AlertType.HIGH_WARNING,
            AlertSeverity.WARNING,
            current_value=220.0,
            trend_rate=1.5,
        )
        msg = format_alert_message(alert)
        assert "High Glucose Warning" in msg
        assert "220 mg/dL" in msg
        assert "rising" in msg
        assert "insulin dosing" in msg

    def test_iob_warning_includes_iob_value(self):
        alert = make_alert(
            AlertType.IOB_WARNING,
            AlertSeverity.WARNING,
            iob_value=5.3,
        )
        msg = format_alert_message(alert)
        assert "Insulin on Board" in msg
        assert "5.3 units" in msg

    def test_predictive_alert_includes_prediction(self):
        alert = make_alert(predicted_value=42.0, prediction_minutes=20)
        msg = format_alert_message(alert)
        assert "Predicted" in msg
        assert "42 mg/dL" in msg
        assert "20 min" in msg

    def test_current_alert_omits_prediction(self):
        alert = make_alert(predicted_value=None, prediction_minutes=None)
        msg = format_alert_message(alert)
        assert "Predicted" not in msg

    def test_acknowledge_command_includes_alert_id(self):
        alert = make_alert()
        msg = format_alert_message(alert)
        assert f"/acknowledge_{alert.id}" in msg

    def test_message_uses_html_bold(self):
        alert = make_alert()
        msg = format_alert_message(alert)
        assert "<b>" in msg
        assert "</b>" in msg

    def test_all_severity_levels_have_emoji(self):
        for severity in AlertSeverity:
            alert = make_alert(severity=severity)
            msg = format_alert_message(alert)
            emoji = SEVERITY_EMOJI[severity]
            assert emoji in msg

    def test_renders_mmol_unit(self):
        """Current (55->3.1) and predicted (45->2.5) render in the patient's
        unit; mg/dL never appears."""
        alert = make_alert(current_value=55.0, predicted_value=45.0)
        msg = format_alert_message(alert, GlucoseUnit.MMOL)
        assert "3.1 mmol/L" in msg
        assert "2.5 mmol/L" in msg
        assert "mg/dL" not in msg


# ---------------------------------------------------------------------------
# Format escalation contact message tests (pure function)
# ---------------------------------------------------------------------------
class TestFormatEscalationContactMessage:
    """Tests for format_escalation_contact_message()."""

    def test_includes_user_email(self):
        alert = make_alert()
        msg = format_escalation_contact_message(alert, "user@test.com", "Primary")
        assert "user@test.com" in msg

    def test_includes_tier_label(self):
        alert = make_alert()
        msg = format_escalation_contact_message(alert, "u@t.com", "Emergency Alert")
        assert "Emergency Alert" in msg

    def test_includes_glucose_and_trend(self):
        alert = make_alert(current_value=180.0, trend_rate=2.0)
        msg = format_escalation_contact_message(alert, "u@t.com", "Tier")
        assert "180 mg/dL" in msg
        assert "rising" in msg

    def test_contact_sees_patient_unit(self):
        """The contact reads the patient's glucose in the PATIENT's unit
        (180 -> 10.0 mmol/L), never the contact's own."""
        alert = make_alert(current_value=180.0, trend_rate=2.0)
        msg = format_escalation_contact_message(
            alert, "u@t.com", "Tier", GlucoseUnit.MMOL
        )
        assert "10.0 mmol/L" in msg
        assert "mg/dL" not in msg


# ---------------------------------------------------------------------------
# Notify user of alerts tests (async with mocks)
# ---------------------------------------------------------------------------
class TestNotifyUserOfAlerts:
    """Tests for notify_user_of_alerts()."""

    @pytest.mark.asyncio
    @patch("src.services.alert_notifier.send_message", new_callable=AsyncMock)
    @patch("src.services.alert_notifier.get_telegram_link", new_callable=AsyncMock)
    async def test_sends_to_linked_user(self, mock_get_link, mock_send):
        """Should send formatted message to linked user."""
        link = MagicMock()
        link.chat_id = 12345
        link.is_verified = True
        mock_get_link.return_value = link
        mock_send.return_value = True

        user_id = uuid.uuid4()
        alerts = [make_alert()]
        db = AsyncMock()

        result = await notify_user_of_alerts(db, user_id, alerts)

        assert result == 1
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[0][0] == 12345
        assert "Urgent Low Glucose" in call_args[0][1]

    @pytest.mark.asyncio
    @patch("src.services.alert_notifier.send_message", new_callable=AsyncMock)
    @patch("src.services.alert_notifier.get_telegram_link", new_callable=AsyncMock)
    async def test_skips_unlinked_user(self, mock_get_link, mock_send):
        """Should return 0 and not send if no Telegram link."""
        mock_get_link.return_value = None

        result = await notify_user_of_alerts(AsyncMock(), uuid.uuid4(), [make_alert()])

        assert result == 0
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.services.alert_notifier.send_message", new_callable=AsyncMock)
    @patch("src.services.alert_notifier.get_telegram_link", new_callable=AsyncMock)
    async def test_skips_unverified_link(self, mock_get_link, mock_send):
        """Should return 0 if link exists but is not verified."""
        link = MagicMock()
        link.is_verified = False
        mock_get_link.return_value = link

        result = await notify_user_of_alerts(AsyncMock(), uuid.uuid4(), [make_alert()])

        assert result == 0
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_alerts_returns_zero(self):
        """Should return 0 for empty alert list without DB query."""
        result = await notify_user_of_alerts(AsyncMock(), uuid.uuid4(), [])
        assert result == 0

    @pytest.mark.asyncio
    @patch("src.services.alert_notifier.send_message", new_callable=AsyncMock)
    @patch("src.services.alert_notifier.get_telegram_link", new_callable=AsyncMock)
    async def test_telegram_error_does_not_raise(self, mock_get_link, mock_send):
        """TelegramBotError should be caught and logged, not raised."""
        link = MagicMock()
        link.chat_id = 12345
        link.is_verified = True
        mock_get_link.return_value = link
        mock_send.side_effect = TelegramBotError("API error")

        result = await notify_user_of_alerts(AsyncMock(), uuid.uuid4(), [make_alert()])

        assert result == 0

    @pytest.mark.asyncio
    @patch("src.services.alert_notifier.send_message", new_callable=AsyncMock)
    @patch("src.services.alert_notifier.get_telegram_link", new_callable=AsyncMock)
    async def test_sends_multiple_alerts(self, mock_get_link, mock_send):
        """Should send one message per alert."""
        link = MagicMock()
        link.chat_id = 12345
        link.is_verified = True
        mock_get_link.return_value = link
        mock_send.return_value = True

        alerts = [make_alert(), make_alert(), make_alert()]
        result = await notify_user_of_alerts(AsyncMock(), uuid.uuid4(), alerts)

        assert result == 3
        assert mock_send.call_count == 3

    @pytest.mark.asyncio
    @patch("src.services.alert_notifier.send_message", new_callable=AsyncMock)
    @patch("src.services.alert_notifier.get_telegram_link", new_callable=AsyncMock)
    async def test_partial_failure_continues(self, mock_get_link, mock_send):
        """First send fails, second succeeds — should return 1."""
        link = MagicMock()
        link.chat_id = 12345
        link.is_verified = True
        mock_get_link.return_value = link
        mock_send.side_effect = [
            TelegramBotError("fail"),
            True,
        ]

        alerts = [make_alert(), make_alert()]
        result = await notify_user_of_alerts(AsyncMock(), uuid.uuid4(), alerts)

        assert result == 1
        assert mock_send.call_count == 2

    @pytest.mark.asyncio
    @patch("src.services.alert_notifier.send_message", new_callable=AsyncMock)
    @patch("src.services.alert_notifier.get_telegram_link", new_callable=AsyncMock)
    async def test_generic_exception_does_not_raise(self, mock_get_link, mock_send):
        """Non-TelegramBotError exceptions should be caught and logged."""
        link = MagicMock()
        link.chat_id = 12345
        link.is_verified = True
        mock_get_link.return_value = link
        mock_send.side_effect = ConnectionError("network failure")

        result = await notify_user_of_alerts(AsyncMock(), uuid.uuid4(), [make_alert()])

        assert result == 0


# ---------------------------------------------------------------------------
# HTML escaping tests
# ---------------------------------------------------------------------------
class TestHTMLEscaping:
    """Tests for HTML injection prevention in messages."""

    def test_escalation_message_escapes_email(self):
        alert = make_alert()
        msg = format_escalation_contact_message(alert, "<b>evil</b>@test.com", "Tier")
        assert "<b>evil</b>@test.com" not in msg
        assert "&lt;b&gt;evil&lt;/b&gt;@test.com" in msg

    def test_escalation_message_escapes_tier_label(self):
        alert = make_alert()
        msg = format_escalation_contact_message(
            alert, "user@test.com", "<script>alert(1)</script>"
        )
        assert "<script>" not in msg
        assert "&lt;script&gt;" in msg
