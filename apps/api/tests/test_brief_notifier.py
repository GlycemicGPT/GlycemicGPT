"""Story 7.3: Tests for daily brief Telegram delivery."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.brief_delivery_config import DeliveryChannel
from src.models.daily_brief import DailyBrief
from src.services.brief_notifier import (
    _tir_emoji,
    _truncate,
    format_brief_message,
    notify_user_of_brief,
)
from src.services.telegram_bot import TelegramBotError


def make_brief(
    tir: float = 78.0,
    avg: float = 132.0,
    lows: int = 2,
    highs: int = 5,
    ai_summary: str = "Overall a solid day with good control.",
) -> MagicMock:
    """Create a mock DailyBrief for testing."""
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
    brief.ai_summary = ai_summary
    brief.period_start = datetime.now(UTC) - timedelta(hours=24)
    brief.period_end = datetime.now(UTC)
    return brief


# ---------------------------------------------------------------------------
# TIR emoji tests
# ---------------------------------------------------------------------------
class TestTirEmoji:
    """Tests for _tir_emoji helper."""

    def test_good_tir_green(self):
        assert _tir_emoji(78.0) == "\U0001f7e2"

    def test_ok_tir_yellow(self):
        assert _tir_emoji(55.0) == "\U0001f7e1"

    def test_low_tir_red(self):
        assert _tir_emoji(40.0) == "\U0001f534"

    def test_boundary_70_is_green(self):
        assert _tir_emoji(70.0) == "\U0001f7e2"

    def test_boundary_50_is_yellow(self):
        assert _tir_emoji(50.0) == "\U0001f7e1"

    def test_boundary_49_is_red(self):
        assert _tir_emoji(49.9) == "\U0001f534"

    def test_nan_returns_red(self):
        assert _tir_emoji(float("nan")) == "\U0001f534"

    def test_inf_returns_red(self):
        assert _tir_emoji(float("inf")) == "\U0001f534"

    def test_negative_inf_returns_red(self):
        assert _tir_emoji(float("-inf")) == "\U0001f534"


# ---------------------------------------------------------------------------
# Truncate helper tests
# ---------------------------------------------------------------------------
class TestTruncate:
    """Tests for _truncate helper."""

    def test_short_text_unchanged(self):
        assert _truncate("hello", 10) == "hello"

    def test_long_text_truncated(self):
        result = _truncate("a" * 200, 150)
        assert len(result) == 150
        assert result.endswith("\u2026")

    def test_exact_length_unchanged(self):
        text = "a" * 150
        assert _truncate(text, 150) == text

    def test_max_len_zero_clamps_to_min(self):
        result = _truncate("hello world", 0)
        assert len(result) == 2  # 1 char + ellipsis

    def test_max_len_one_clamps_to_min(self):
        result = _truncate("hello world", 1)
        assert len(result) == 2  # 1 char + ellipsis


# ---------------------------------------------------------------------------
# Format brief message tests
# ---------------------------------------------------------------------------
class TestFormatBriefMessage:
    """Tests for format_brief_message."""

    def test_message_under_500_chars(self):
        brief = make_brief()
        msg = format_brief_message(brief)
        assert len(msg) < 500

    def test_contains_tir_percentage(self):
        brief = make_brief(tir=82.3)
        msg = format_brief_message(brief)
        assert "82%" in msg

    def test_contains_avg_glucose(self):
        brief = make_brief(avg=145.6)
        msg = format_brief_message(brief)
        assert "146 mg/dL" in msg

    def test_contains_low_count(self):
        brief = make_brief(lows=3, highs=0)
        msg = format_brief_message(brief)
        assert "3 low" in msg

    def test_contains_high_count(self):
        brief = make_brief(lows=0, highs=7)
        msg = format_brief_message(brief)
        assert "7 high" in msg

    def test_no_lows_or_highs_omits_line(self):
        brief = make_brief(lows=0, highs=0)
        msg = format_brief_message(brief)
        assert "low" not in msg
        assert "high" not in msg

    def test_no_dead_command_in_message(self):
        """No /brief_ command until Story 7.4 implements bot-side handling."""
        brief = make_brief()
        msg = format_brief_message(brief)
        assert "/brief_" not in msg

    def test_contains_ai_summary(self):
        brief = make_brief(ai_summary="Your overnight was excellent.")
        msg = format_brief_message(brief)
        assert "Your overnight was excellent." in msg

    def test_long_ai_summary_truncated(self):
        long_summary = "x" * 300
        brief = make_brief(ai_summary=long_summary)
        msg = format_brief_message(brief)
        assert len(msg) < 500
        assert "\u2026" in msg

    def test_html_in_ai_summary_escaped(self):
        brief = make_brief(ai_summary="<b>injected</b> html")
        msg = format_brief_message(brief)
        assert "<b>injected</b>" not in msg
        assert "&lt;b&gt;injected&lt;/b&gt;" in msg

    def test_contains_daily_brief_headline(self):
        brief = make_brief()
        msg = format_brief_message(brief)
        assert "<b>Daily Brief</b>" in msg

    def test_message_with_max_values_under_500(self):
        """Even with large numbers and long summary, stays under 500."""
        brief = make_brief(
            tir=99.9,
            avg=399.9,
            lows=99,
            highs=99,
            ai_summary="A" * 200,
        )
        msg = format_brief_message(brief)
        assert len(msg) < 500

    def test_entity_expansion_stays_under_500(self):
        """HTML entities (e.g. &amp;) expand, but truncation keeps it under 500."""
        brief = make_brief(ai_summary="&" * 300)
        msg = format_brief_message(brief)
        assert len(msg) < 500
        assert "&amp;" in msg

    def test_empty_ai_summary_omits_section(self):
        brief = make_brief(ai_summary="")
        msg = format_brief_message(brief)
        assert "\U0001f4dd" not in msg

    def test_none_ai_summary_omits_section(self):
        brief = make_brief(ai_summary=None)
        msg = format_brief_message(brief)
        assert "\U0001f4dd" not in msg

    def test_combined_lows_and_highs(self):
        brief = make_brief(lows=2, highs=5)
        msg = format_brief_message(brief)
        assert "2 low" in msg
        assert "5 high" in msg
        assert "2 low  |  " in msg  # verify separator format


# ---------------------------------------------------------------------------
# Notify user of brief tests
# ---------------------------------------------------------------------------
class TestNotifyUserOfBrief:
    """Tests for notify_user_of_brief delivery function."""

    @pytest.fixture(autouse=True)
    def channel_config(self):
        """notify_user_of_brief now consults the delivery channel first. Patch it
        to a non-web_only channel by default so the send-path tests proceed; a
        test can flip ``channel_config.channel`` to assert the web_only skip."""
        cfg = MagicMock()
        cfg.channel = DeliveryChannel.BOTH
        with patch(
            "src.services.brief_notifier.get_or_create_config",
            new=AsyncMock(return_value=cfg),
        ):
            yield cfg

    @pytest.mark.asyncio
    @patch("src.services.brief_notifier.send_message", new_callable=AsyncMock)
    @patch("src.services.brief_notifier.get_telegram_link", new_callable=AsyncMock)
    async def test_web_only_channel_skips_telegram(
        self, mock_get_link, mock_send, channel_config
    ):
        channel_config.channel = DeliveryChannel.WEB_ONLY

        result = await notify_user_of_brief(AsyncMock(), uuid.uuid4(), make_brief())

        assert result is False
        mock_get_link.assert_not_called()
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.services.brief_notifier.send_message", new_callable=AsyncMock)
    @patch("src.services.brief_notifier.get_telegram_link", new_callable=AsyncMock)
    async def test_sends_to_verified_link(self, mock_get_link, mock_send):
        link = MagicMock()
        link.chat_id = 12345
        link.is_verified = True
        mock_get_link.return_value = link
        mock_send.return_value = True

        result = await notify_user_of_brief(AsyncMock(), uuid.uuid4(), make_brief())

        assert result is True
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.services.brief_notifier.get_telegram_link", new_callable=AsyncMock)
    async def test_unlinked_user_returns_false(self, mock_get_link):
        mock_get_link.return_value = None

        result = await notify_user_of_brief(AsyncMock(), uuid.uuid4(), make_brief())

        assert result is False

    @pytest.mark.asyncio
    @patch("src.services.brief_notifier.get_telegram_link", new_callable=AsyncMock)
    async def test_unverified_link_returns_false(self, mock_get_link):
        link = MagicMock()
        link.is_verified = False
        mock_get_link.return_value = link

        result = await notify_user_of_brief(AsyncMock(), uuid.uuid4(), make_brief())

        assert result is False

    @pytest.mark.asyncio
    @patch("src.services.brief_notifier.send_message", new_callable=AsyncMock)
    @patch("src.services.brief_notifier.get_telegram_link", new_callable=AsyncMock)
    async def test_telegram_error_returns_false(self, mock_get_link, mock_send):
        link = MagicMock()
        link.chat_id = 12345
        link.is_verified = True
        mock_get_link.return_value = link
        mock_send.side_effect = TelegramBotError("Bot blocked by user")

        result = await notify_user_of_brief(AsyncMock(), uuid.uuid4(), make_brief())

        assert result is False

    @pytest.mark.asyncio
    @patch("src.services.brief_notifier.send_message", new_callable=AsyncMock)
    @patch("src.services.brief_notifier.get_telegram_link", new_callable=AsyncMock)
    async def test_generic_exception_returns_false(self, mock_get_link, mock_send):
        link = MagicMock()
        link.chat_id = 12345
        link.is_verified = True
        mock_get_link.return_value = link
        mock_send.side_effect = ConnectionError("network failure")

        result = await notify_user_of_brief(AsyncMock(), uuid.uuid4(), make_brief())

        assert result is False

    @pytest.mark.asyncio
    @patch("src.services.brief_notifier.send_message", new_callable=AsyncMock)
    @patch("src.services.brief_notifier.get_telegram_link", new_callable=AsyncMock)
    async def test_message_content_is_html(self, mock_get_link, mock_send):
        """Verify the sent message contains expected HTML formatting."""
        link = MagicMock()
        link.chat_id = 12345
        link.is_verified = True
        mock_get_link.return_value = link
        mock_send.return_value = True

        brief = make_brief(tir=80.0)
        await notify_user_of_brief(AsyncMock(), uuid.uuid4(), brief)

        sent_msg = mock_send.call_args[0][1]
        assert "<b>Daily Brief</b>" in sent_msg
        assert "<b>TIR:</b>" in sent_msg
