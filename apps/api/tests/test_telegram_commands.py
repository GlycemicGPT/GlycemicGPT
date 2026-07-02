"""Stories 7.4, 7.5 & 7.6: Tests for Telegram command handlers."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.units import GlucoseUnit
from src.models.alert import Alert, AlertSeverity, AlertType
from src.models.daily_brief import DailyBrief
from src.models.glucose import GlucoseReading, TrendDirection
from src.services.iob_projection import IoBProjection
from src.services.telegram_commands import (
    _handle_acknowledge,
    _handle_brief,
    _handle_help,
    _handle_status,
    _handle_unknown,
    _reading_age,
    get_user_id_by_chat_id,
    handle_command,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def make_reading(
    value: int = 120,
    trend_rate: float = 0.5,
    minutes_ago: int = 3,
    trend: TrendDirection = TrendDirection.FLAT,
) -> MagicMock:
    """Create a mock GlucoseReading."""
    reading = MagicMock(spec=GlucoseReading)
    reading.value = value
    reading.trend_rate = trend_rate
    reading.trend = trend
    reading.reading_timestamp = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    reading.user_id = uuid.uuid4()
    return reading


def make_alert(
    acknowledged: bool = False,
    alert_type: AlertType = AlertType.LOW_WARNING,
    message: str = "Low glucose detected",
) -> MagicMock:
    """Create a mock Alert."""
    alert = MagicMock(spec=Alert)
    alert.id = uuid.uuid4()
    alert.user_id = uuid.uuid4()
    alert.alert_type = alert_type
    alert.severity = AlertSeverity.WARNING
    alert.acknowledged = acknowledged
    alert.message = message
    return alert


def make_brief(
    tir: float = 78.0,
    avg: float = 132.0,
    lows: int = 2,
    highs: int = 5,
) -> MagicMock:
    """Create a mock DailyBrief."""
    brief = MagicMock(spec=DailyBrief)
    brief.id = uuid.uuid4()
    brief.user_id = uuid.uuid4()
    brief.time_in_range_pct = tir
    brief.average_glucose = avg
    brief.low_count = lows
    brief.high_count = highs
    brief.readings_count = 288
    brief.correction_count = 3
    brief.total_insulin = 42.5
    brief.ai_summary = "Good day overall."
    brief.period_start = datetime.now(UTC) - timedelta(hours=24)
    brief.period_end = datetime.now(UTC)
    return brief


def make_iob(
    projected_iob: float = 2.5,
    is_stale: bool = False,
) -> IoBProjection:
    """Create a real IoBProjection dataclass."""
    now = datetime.now(UTC)
    return IoBProjection(
        confirmed_iob=3.0,
        confirmed_at=now - timedelta(minutes=30),
        projected_iob=projected_iob,
        projected_at=now,
        projected_30min=1.8,
        projected_60min=0.9,
        minutes_since_confirmed=30,
        is_stale=is_stale,
        stale_warning="IoB data is stale" if is_stale else None,
    )


# ---------------------------------------------------------------------------
# Reading age helper tests
# ---------------------------------------------------------------------------
class TestReadingAge:
    """Tests for _reading_age helper."""

    def test_just_now(self):
        ts = datetime.now(UTC) - timedelta(seconds=30)
        assert _reading_age(ts) == "just now"

    def test_one_minute(self):
        ts = datetime.now(UTC) - timedelta(minutes=1, seconds=10)
        assert _reading_age(ts) == "1 min ago"

    def test_multiple_minutes(self):
        ts = datetime.now(UTC) - timedelta(minutes=7)
        assert _reading_age(ts) == "7 min ago"

    def test_one_hour(self):
        ts = datetime.now(UTC) - timedelta(hours=1, minutes=5)
        assert _reading_age(ts) == "1 hour ago"

    def test_multiple_hours(self):
        ts = datetime.now(UTC) - timedelta(hours=3, minutes=20)
        assert _reading_age(ts) == "3 hours ago"

    def test_future_timestamp_returns_just_now(self):
        """Future timestamps (clock skew) should not produce negative output."""
        ts = datetime.now(UTC) + timedelta(minutes=5)
        assert _reading_age(ts) == "just now"


# ---------------------------------------------------------------------------
# get_user_id_by_chat_id tests
# ---------------------------------------------------------------------------
class TestGetUserIdByChatId:
    """Tests for get_user_id_by_chat_id."""

    @pytest.mark.asyncio
    async def test_linked_user_returns_uuid(self):
        user_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user_id
        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await get_user_id_by_chat_id(db, 12345)
        assert result == user_id

    @pytest.mark.asyncio
    async def test_unlinked_returns_none(self):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await get_user_id_by_chat_id(db, 99999)
        assert result is None

    @pytest.mark.asyncio
    async def test_unverified_link_returns_none(self):
        """Unverified links should not resolve to a user ID."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # query filters is_verified
        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await get_user_id_by_chat_id(db, 12345)
        assert result is None


# ---------------------------------------------------------------------------
# /status command tests
# ---------------------------------------------------------------------------
class TestHandleStatus:
    """Tests for _handle_status."""

    @pytest.fixture(autouse=True)
    def _stub_empty_cgm_exclusion(self):
        # _handle_status now reads the latest reading through the shared
        # primary-source funnel (GLY-123). These tests mock the DB and set no
        # CGM sources, so stub the exclusion to empty to avoid the funnel's
        # list_cgm_sources queries against the single-result execute mock.
        with patch(
            "src.services.cgm_source.get_excluded_cgm_sources",
            new=AsyncMock(return_value=[]),
        ):
            yield

    @pytest.fixture(autouse=True)
    def _mgdl_unit(self):
        # _handle_status resolves the patient's unit before rendering; default it
        # to mg/dL so the existing assertions check a real resolved unit rather
        # than passing on MagicMock truthiness. The mmol test overrides this.
        with patch(
            "src.services.telegram_commands.resolve_glucose_unit",
            new=AsyncMock(return_value=GlucoseUnit.MGDL),
        ):
            yield

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_dia",
        new_callable=AsyncMock,
        return_value=4.0,
    )
    @patch("src.services.telegram_commands.get_iob_projection", new_callable=AsyncMock)
    async def test_with_glucose_and_iob(self, mock_iob, mock_dia):
        mock_iob.return_value = make_iob(projected_iob=2.5)

        reading = make_reading(value=120, trend_rate=0.5)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = reading

        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await _handle_status(db, uuid.uuid4())

        assert "120 mg/dL" in msg
        assert "<b>Current Status</b>" in msg
        assert "2.5 units" in msg

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_dia",
        new_callable=AsyncMock,
        return_value=4.0,
    )
    @patch("src.services.telegram_commands.get_iob_projection", new_callable=AsyncMock)
    async def test_no_glucose_data(self, mock_iob, mock_dia):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await _handle_status(db, uuid.uuid4())

        assert "No glucose data" in msg
        mock_iob.assert_not_called()

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_dia",
        new_callable=AsyncMock,
        return_value=4.0,
    )
    @patch("src.services.telegram_commands.get_iob_projection", new_callable=AsyncMock)
    async def test_stale_iob_shows_warning(self, mock_iob, mock_dia):
        mock_iob.return_value = make_iob(is_stale=True)

        reading = make_reading()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = reading
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await _handle_status(db, uuid.uuid4())

        assert "stale" in msg.lower()

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_dia",
        new_callable=AsyncMock,
        return_value=4.0,
    )
    @patch("src.services.telegram_commands.get_iob_projection", new_callable=AsyncMock)
    async def test_no_iob_data(self, mock_iob, mock_dia):
        mock_iob.return_value = None

        reading = make_reading(value=95)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = reading
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await _handle_status(db, uuid.uuid4())

        assert "95 mg/dL" in msg
        assert "IoB" not in msg

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_dia",
        new_callable=AsyncMock,
        return_value=4.0,
    )
    @patch("src.services.telegram_commands.get_iob_projection", new_callable=AsyncMock)
    async def test_trend_description_included(self, mock_iob, mock_dia):
        mock_iob.return_value = None

        reading = make_reading(trend_rate=-2.0)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = reading
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await _handle_status(db, uuid.uuid4())

        assert "falling" in msg.lower()

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.resolve_glucose_unit",
        new=AsyncMock(return_value=GlucoseUnit.MMOL),
    )
    @patch(
        "src.services.telegram_commands.get_user_dia",
        new_callable=AsyncMock,
        return_value=4.0,
    )
    @patch("src.services.telegram_commands.get_iob_projection", new_callable=AsyncMock)
    async def test_renders_mmol_unit(self, mock_iob, mock_dia):
        """An mmol/L patient's /status renders glucose in mmol (120 -> 6.7);
        mg/dL must not appear."""
        mock_iob.return_value = None

        reading = make_reading(value=120, trend_rate=0.5)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = reading
        db = AsyncMock()
        db.execute.return_value = mock_result

        msg = await _handle_status(db, uuid.uuid4())

        assert "6.7 mmol/L" in msg
        assert "mg/dL" not in msg


# ---------------------------------------------------------------------------
# /acknowledge command tests
# ---------------------------------------------------------------------------
class TestHandleAcknowledge:
    """Tests for _handle_acknowledge."""

    @pytest.mark.asyncio
    @patch("src.services.telegram_commands.acknowledge_alert", new_callable=AsyncMock)
    @patch("src.services.telegram_commands.get_active_alerts", new_callable=AsyncMock)
    async def test_acknowledge_most_recent(self, mock_get, mock_ack):
        alert = make_alert(message="Low glucose detected")
        mock_get.return_value = [alert]
        mock_ack.return_value = alert

        msg = await _handle_acknowledge(AsyncMock(), uuid.uuid4(), "")

        assert "acknowledged" in msg.lower()
        assert "Low glucose detected" in msg

    @pytest.mark.asyncio
    @patch("src.services.telegram_commands.acknowledge_alert", new_callable=AsyncMock)
    async def test_acknowledge_specific_id(self, mock_ack):
        alert_id = uuid.uuid4()
        alert = make_alert(message="High glucose warning")
        mock_ack.return_value = alert

        msg = await _handle_acknowledge(AsyncMock(), uuid.uuid4(), str(alert_id))

        assert "acknowledged" in msg.lower()
        mock_ack.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.services.telegram_commands.get_active_alerts", new_callable=AsyncMock)
    async def test_no_active_alerts(self, mock_get):
        mock_get.return_value = []

        msg = await _handle_acknowledge(AsyncMock(), uuid.uuid4(), "")

        assert "No active alerts" in msg

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_error(self):
        msg = await _handle_acknowledge(AsyncMock(), uuid.uuid4(), "not-a-uuid")

        assert "Invalid alert ID" in msg

    @pytest.mark.asyncio
    @patch("src.services.telegram_commands.acknowledge_alert", new_callable=AsyncMock)
    async def test_alert_not_found(self, mock_ack):
        mock_ack.return_value = None

        msg = await _handle_acknowledge(AsyncMock(), uuid.uuid4(), str(uuid.uuid4()))

        assert "not found" in msg.lower() or "already acknowledged" in msg.lower()

    @pytest.mark.asyncio
    @patch("src.services.telegram_commands.get_active_alerts", new_callable=AsyncMock)
    @patch("src.services.telegram_commands.acknowledge_alert", new_callable=AsyncMock)
    async def test_race_condition_message(self, mock_ack, mock_get):
        """When acknowledge returns None for most-recent path (race), message is clear."""
        alert = make_alert()
        mock_get.return_value = [alert]
        mock_ack.return_value = None  # Race: already acknowledged

        msg = await _handle_acknowledge(AsyncMock(), uuid.uuid4(), "")

        assert "already acknowledged" in msg.lower()

    @pytest.mark.asyncio
    @patch("src.services.telegram_commands.acknowledge_alert", new_callable=AsyncMock)
    async def test_html_in_message_is_escaped(self, mock_ack):
        """Alert messages containing HTML are escaped."""
        alert = make_alert(message="<b>injected</b> html")
        mock_ack.return_value = alert

        msg = await _handle_acknowledge(AsyncMock(), uuid.uuid4(), str(alert.id))

        assert "<b>injected</b>" not in msg
        assert "&lt;b&gt;" in msg


# ---------------------------------------------------------------------------
# /brief command tests
# ---------------------------------------------------------------------------
class TestHandleBrief:
    """Tests for _handle_brief."""

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.resolve_glucose_unit",
        new=AsyncMock(return_value=GlucoseUnit.MGDL),
    )
    @patch("src.services.telegram_commands.list_briefs", new_callable=AsyncMock)
    @patch("src.services.telegram_commands.format_brief_message")
    async def test_latest_brief_returned(self, mock_format, mock_list):
        brief = make_brief()
        mock_list.return_value = ([brief], 1)
        mock_format.return_value = "<b>Daily Brief</b>\nFormatted"

        msg = await _handle_brief(AsyncMock(), uuid.uuid4())

        assert "Daily Brief" in msg
        mock_format.assert_called_once_with(brief, GlucoseUnit.MGDL)

    @pytest.mark.asyncio
    @patch("src.services.telegram_commands.list_briefs", new_callable=AsyncMock)
    async def test_no_briefs_available(self, mock_list):
        mock_list.return_value = ([], 0)

        msg = await _handle_brief(AsyncMock(), uuid.uuid4())

        assert "No daily briefs" in msg

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.resolve_glucose_unit",
        new=AsyncMock(return_value=GlucoseUnit.MGDL),
    )
    @patch("src.services.telegram_commands.list_briefs", new_callable=AsyncMock)
    @patch("src.services.telegram_commands.format_brief_message")
    async def test_reuses_format_brief_message(self, mock_format, mock_list):
        brief = make_brief()
        mock_list.return_value = ([brief], 1)
        mock_format.return_value = "formatted"

        await _handle_brief(AsyncMock(), uuid.uuid4())

        mock_format.assert_called_once_with(brief, GlucoseUnit.MGDL)


# ---------------------------------------------------------------------------
# /help command tests
# ---------------------------------------------------------------------------
class TestHandleHelp:
    """Tests for _handle_help."""

    def test_contains_all_commands(self):
        msg = _handle_help()
        assert "/status" in msg
        assert "/acknowledge" in msg
        assert "/brief" in msg
        assert "/help" in msg

    def test_is_html_formatted(self):
        msg = _handle_help()
        assert "<b>" in msg

    def test_mentions_ai_chat(self):
        """Story 7.5: Help text mentions AI chat for non-command messages."""
        msg = _handle_help()
        assert "question" in msg.lower() or "chat" in msg.lower()


# ---------------------------------------------------------------------------
# Unknown command tests
# ---------------------------------------------------------------------------
class TestHandleUnknown:
    """Tests for _handle_unknown."""

    def test_returns_guidance(self):
        msg = _handle_unknown()
        assert "Unrecognized" in msg

    def test_mentions_help(self):
        msg = _handle_unknown()
        assert "/help" in msg


# ---------------------------------------------------------------------------
# Command router tests
# ---------------------------------------------------------------------------
class TestHandleCommand:
    """Tests for handle_command routing."""

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id", new_callable=AsyncMock
    )
    @patch("src.services.telegram_commands._handle_status", new_callable=AsyncMock)
    async def test_routes_status(self, mock_status, mock_user):
        mock_user.return_value = uuid.uuid4()
        mock_status.return_value = "status response"

        result = await handle_command(AsyncMock(), 12345, "/status")

        assert result == "status response"
        mock_status.assert_called_once()

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id", new_callable=AsyncMock
    )
    @patch("src.services.telegram_commands._handle_acknowledge", new_callable=AsyncMock)
    async def test_routes_acknowledge(self, mock_ack, mock_user):
        mock_user.return_value = uuid.uuid4()
        mock_ack.return_value = "ack response"

        result = await handle_command(AsyncMock(), 12345, "/acknowledge")

        assert result == "ack response"
        mock_ack.assert_called_once()

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id", new_callable=AsyncMock
    )
    @patch("src.services.telegram_commands._handle_acknowledge", new_callable=AsyncMock)
    async def test_routes_acknowledge_with_id(self, mock_ack, mock_user):
        mock_user.return_value = uuid.uuid4()
        mock_ack.return_value = "ack specific"
        alert_id = str(uuid.uuid4())

        result = await handle_command(AsyncMock(), 12345, f"/acknowledge_{alert_id}")

        assert result == "ack specific"
        mock_ack.assert_called_once()
        # Verify the args contain the alert ID
        call_args = mock_ack.call_args
        assert call_args[0][2] == alert_id

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id", new_callable=AsyncMock
    )
    @patch("src.services.telegram_commands._handle_acknowledge", new_callable=AsyncMock)
    async def test_acknowledge_trailing_underscore_no_id(self, mock_ack, mock_user):
        """Finding #8: /acknowledge_ (empty suffix) falls through to most-recent."""
        mock_user.return_value = uuid.uuid4()
        mock_ack.return_value = "ack response"

        await handle_command(AsyncMock(), 12345, "/acknowledge_")

        mock_ack.assert_called_once()
        # Should pass empty string args (treat as "acknowledge most recent")
        call_args = mock_ack.call_args
        assert call_args[0][2] == ""

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id", new_callable=AsyncMock
    )
    @patch("src.services.telegram_commands.acknowledge_alert", new_callable=AsyncMock)
    async def test_routes_acknowledge_not_found(self, mock_ack, mock_user):
        """Routing-level test: valid UUID that doesn't match any alert."""
        mock_user.return_value = uuid.uuid4()
        mock_ack.return_value = None  # Alert not found

        alert_id = str(uuid.uuid4())
        result = await handle_command(AsyncMock(), 12345, f"/acknowledge_{alert_id}")

        assert "not found" in result.lower() or "already acknowledged" in result.lower()

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id", new_callable=AsyncMock
    )
    @patch("src.services.telegram_commands._handle_brief", new_callable=AsyncMock)
    async def test_routes_brief(self, mock_brief, mock_user):
        mock_user.return_value = uuid.uuid4()
        mock_brief.return_value = "brief response"

        result = await handle_command(AsyncMock(), 12345, "/brief")

        assert result == "brief response"
        mock_brief.assert_called_once()

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id", new_callable=AsyncMock
    )
    async def test_routes_help(self, mock_user):
        mock_user.return_value = uuid.uuid4()

        result = await handle_command(AsyncMock(), 12345, "/help")

        assert "/status" in result
        assert "/acknowledge" in result

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id", new_callable=AsyncMock
    )
    async def test_routes_unknown(self, mock_user):
        mock_user.return_value = uuid.uuid4()

        result = await handle_command(AsyncMock(), 12345, "/foobar")

        assert "Unrecognized" in result
        assert "/help" in result

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id", new_callable=AsyncMock
    )
    async def test_unlinked_user_gets_error(self, mock_user):
        mock_user.return_value = None

        result = await handle_command(AsyncMock(), 99999, "/status")

        assert "not linked" in result.lower()

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id", new_callable=AsyncMock
    )
    @patch("src.services.telegram_commands._handle_status", new_callable=AsyncMock)
    async def test_case_insensitive(self, mock_status, mock_user):
        mock_user.return_value = uuid.uuid4()
        mock_status.return_value = "status"

        result = await handle_command(AsyncMock(), 12345, "/STATUS")

        assert result == "status"
        mock_status.assert_called_once()

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id", new_callable=AsyncMock
    )
    @patch("src.services.telegram_commands._handle_status", new_callable=AsyncMock)
    async def test_whitespace_trimmed(self, mock_status, mock_user):
        mock_user.return_value = uuid.uuid4()
        mock_status.return_value = "status"

        result = await handle_command(AsyncMock(), 12345, "  /status  ")

        assert result == "status"

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id", new_callable=AsyncMock
    )
    @patch(
        "src.services.telegram_commands._handle_chat_message", new_callable=AsyncMock
    )
    async def test_plain_text_routed_to_ai_chat(self, mock_chat, mock_user):
        """Story 7.5: Plain text routes to AI chat, not unknown handler."""
        mock_user.return_value = uuid.uuid4()
        mock_chat.return_value = "AI response here"

        result = await handle_command(AsyncMock(), 12345, "hello there")

        assert result == "AI response here"
        mock_chat.assert_called_once()
        # Verify the stripped text was passed as the third argument
        call_args = mock_chat.call_args
        assert call_args[0][2] == "hello there"

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id", new_callable=AsyncMock
    )
    @patch(
        "src.services.telegram_commands._handle_chat_message", new_callable=AsyncMock
    )
    async def test_whitespace_only_text_routes_to_chat_as_empty(
        self, mock_chat, mock_user
    ):
        """Edge case: whitespace-only messages route to AI chat as empty string."""
        mock_user.return_value = uuid.uuid4()
        mock_chat.return_value = "AI response"

        result = await handle_command(AsyncMock(), 12345, "   ")

        assert result == "AI response"
        call_args = mock_chat.call_args
        assert call_args[0][2] == ""

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id", new_callable=AsyncMock
    )
    async def test_import_error_in_chat_returns_unavailable(self, mock_user):
        """Finding #9: ImportError in lazy import returns friendly message."""
        mock_user.return_value = uuid.uuid4()

        with patch(
            "src.services.telegram_commands._handle_chat_message",
            new_callable=AsyncMock,
        ) as mock_chat:
            mock_chat.side_effect = ImportError("No module")
            # ImportError propagates to handle_command's catch-all
            result = await handle_command(AsyncMock(), 12345, "hello")

        assert "Something went wrong" in result

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id", new_callable=AsyncMock
    )
    async def test_exception_returns_error_message(self, mock_user):
        """Finding #2: handle_command catches exceptions and returns error string."""
        mock_user.side_effect = RuntimeError("DB connection lost")

        result = await handle_command(AsyncMock(), 12345, "/status")

        assert "Something went wrong" in result


# ---------------------------------------------------------------------------
# Polling loop command routing tests (Finding #10)
# ---------------------------------------------------------------------------
class TestPollAndHandleMessages:
    """Tests for the command-routing branch in poll_and_handle_messages."""

    @pytest.mark.asyncio
    @patch("src.services.telegram_bot.send_message", new_callable=AsyncMock)
    @patch("src.services.telegram_bot.get_updates", new_callable=AsyncMock)
    async def test_routes_non_start_command(self, mock_updates, mock_send):
        """Non-/start messages are routed through handle_command."""
        from src.services.telegram_bot import poll_and_handle_messages, reset_bot_cache

        reset_bot_cache()

        mock_updates.return_value = [
            {
                "update_id": 100,
                "message": {
                    "text": "/help",
                    "chat": {"id": 12345},
                    "from": {"username": "testuser"},
                },
            }
        ]
        mock_send.return_value = True

        with patch(
            "src.services.telegram_commands.get_user_id_by_chat_id",
            new_callable=AsyncMock,
        ) as mock_user:
            mock_user.return_value = uuid.uuid4()
            result = await poll_and_handle_messages(AsyncMock())

        assert result == 1
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "/status" in sent_text  # help response contains commands

    @pytest.mark.asyncio
    @patch("src.services.telegram_bot.send_message", new_callable=AsyncMock)
    @patch("src.services.telegram_bot.get_updates", new_callable=AsyncMock)
    async def test_send_failure_does_not_crash(self, mock_updates, mock_send):
        """TelegramBotError on send_message is caught gracefully."""
        from src.services.telegram_bot import (
            TelegramBotError,
            poll_and_handle_messages,
            reset_bot_cache,
        )

        reset_bot_cache()

        mock_updates.return_value = [
            {
                "update_id": 101,
                "message": {
                    "text": "/status",
                    "chat": {"id": 12345},
                    "from": {"username": "testuser"},
                },
            }
        ]
        mock_send.side_effect = TelegramBotError("Bot blocked")

        with patch(
            "src.services.telegram_commands.get_user_id_by_chat_id",
            new_callable=AsyncMock,
        ) as mock_user:
            mock_user.return_value = uuid.uuid4()
            with patch(
                "src.services.telegram_commands._handle_status",
                new_callable=AsyncMock,
            ) as mock_status:
                mock_status.return_value = "status response"
                result = await poll_and_handle_messages(AsyncMock())

        # Should not crash, but processed count stays 0
        assert result == 0

    @pytest.mark.asyncio
    @patch("src.services.telegram_bot.send_message", new_callable=AsyncMock)
    @patch("src.services.telegram_bot.get_updates", new_callable=AsyncMock)
    async def test_backward_compat_alias(self, mock_updates, mock_send):
        """poll_for_verifications is an alias for poll_and_handle_messages."""
        from src.services.telegram_bot import (
            poll_and_handle_messages,
            poll_for_verifications,
        )

        assert poll_for_verifications is poll_and_handle_messages


# ---------------------------------------------------------------------------
# Caregiver routing tests (Story 7.6)
# ---------------------------------------------------------------------------
class TestCaregiverRouting:
    """Tests for caregiver role detection and routing."""

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id",
        new_callable=AsyncMock,
    )
    @patch(
        "src.services.telegram_commands.get_user_role",
        new_callable=AsyncMock,
    )
    async def test_caregiver_dispatched_to_caregiver_handler(
        self, mock_role, mock_user
    ):
        """Caregiver users are routed to handle_caregiver_command."""
        from src.models.user import UserRole

        mock_user.return_value = uuid.uuid4()
        mock_role.return_value = UserRole.CAREGIVER

        with patch(
            "src.services.telegram_caregiver.handle_caregiver_command",
            new_callable=AsyncMock,
        ) as mock_cg_handler:
            mock_cg_handler.return_value = "caregiver response"
            result = await handle_command(AsyncMock(), 12345, "/status")

        assert result == "caregiver response"

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id",
        new_callable=AsyncMock,
    )
    @patch(
        "src.services.telegram_commands.get_user_role",
        new_callable=AsyncMock,
    )
    @patch("src.services.telegram_commands._handle_status", new_callable=AsyncMock)
    async def test_diabetic_not_dispatched_to_caregiver(
        self, mock_status, mock_role, mock_user
    ):
        """Diabetic users go through normal routing, not caregiver handler."""
        from src.models.user import UserRole

        mock_user.return_value = uuid.uuid4()
        mock_role.return_value = UserRole.DIABETIC
        mock_status.return_value = "diabetic status"

        result = await handle_command(AsyncMock(), 12345, "/status")

        assert result == "diabetic status"
        mock_status.assert_called_once()

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id",
        new_callable=AsyncMock,
    )
    @patch(
        "src.services.telegram_commands.get_user_role",
        new_callable=AsyncMock,
    )
    @patch("src.services.telegram_commands._handle_status", new_callable=AsyncMock)
    async def test_none_role_uses_normal_routing(
        self, mock_status, mock_role, mock_user
    ):
        """Users with None role (shouldn't happen) still go through normal routing."""
        mock_user.return_value = uuid.uuid4()
        mock_role.return_value = None
        mock_status.return_value = "status"

        result = await handle_command(AsyncMock(), 12345, "/status")

        assert result == "status"
        mock_status.assert_called_once()

    @pytest.mark.asyncio
    @patch(
        "src.services.telegram_commands.get_user_id_by_chat_id",
        new_callable=AsyncMock,
    )
    @patch(
        "src.services.telegram_commands.get_user_role",
        new_callable=AsyncMock,
    )
    @patch("src.services.telegram_commands._handle_status", new_callable=AsyncMock)
    async def test_admin_role_uses_normal_routing(
        self, mock_status, mock_role, mock_user
    ):
        """Admin users fall through to normal diabetic routing."""
        from src.models.user import UserRole

        mock_user.return_value = uuid.uuid4()
        mock_role.return_value = UserRole.ADMIN
        mock_status.return_value = "admin status"

        result = await handle_command(AsyncMock(), 12345, "/status")

        assert result == "admin status"
        mock_status.assert_called_once()
