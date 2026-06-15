"""Story 7.3: Daily brief delivery via Telegram.

Formats and sends a concise daily brief summary to users who have
a verified Telegram link. Messages are kept under 500 characters.
"""

import html
import math
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.brief_delivery_config import DeliveryChannel
from src.models.daily_brief import DailyBrief
from src.services.brief_delivery_config import get_or_create_config
from src.services.telegram_bot import (
    TelegramBotError,
    get_telegram_link,
    send_message,
)

logger = get_logger(__name__)

# TIR thresholds for emoji selection
_TIR_GOOD = 70.0  # >= 70% green
_TIR_OK = 50.0  # >= 50% yellow


def _tir_emoji(pct: float) -> str:
    """Return a colored circle emoji based on time-in-range percentage."""
    if not math.isfinite(pct):
        return "\U0001f534"  # red circle for NaN/Inf
    if pct >= _TIR_GOOD:
        return "\U0001f7e2"  # green circle
    if pct >= _TIR_OK:
        return "\U0001f7e1"  # yellow circle
    return "\U0001f534"  # red circle


def _truncate(text: str, max_len: int = 150) -> str:
    """Truncate text to max_len, appending ellipsis if trimmed."""
    max_len = max(max_len, 2)  # ensure room for at least 1 char + ellipsis
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"


def format_brief_message(brief: DailyBrief) -> str:
    """Format a DailyBrief into a concise HTML Telegram message.

    The message is kept under 500 characters for readability.

    Args:
        brief: The DailyBrief model instance.

    Returns:
        HTML-formatted message string for Telegram.
    """
    emoji = _tir_emoji(brief.time_in_range_pct)

    lines = [
        f"{emoji} <b>Daily Brief</b>",
        "",
        f"\U0001f3af <b>TIR:</b> {brief.time_in_range_pct:.0f}%"
        f"  |  <b>Avg:</b> {brief.average_glucose:.0f} mg/dL",
    ]

    # Low/high counts on one compact line
    parts = []
    if brief.low_count > 0:
        parts.append(f"\u2b07 {brief.low_count} low")
    if brief.high_count > 0:
        parts.append(f"\u2b06 {brief.high_count} high")
    if parts:
        lines.append("  |  ".join(parts))

    # Truncated AI summary (escape first, then truncate to keep under budget)
    if brief.ai_summary:
        safe_summary = _truncate(html.escape(brief.ai_summary))
        lines.extend(["", f"\U0001f4dd {safe_summary}"])

    # Note: /brief_ command will be added once Story 7.4 (Telegram Command
    # Handlers) implements bot-side handling. Omitted to avoid user confusion.

    return "\n".join(lines)


async def notify_user_of_brief(
    db: AsyncSession,
    user_id: uuid.UUID,
    brief: DailyBrief,
) -> bool:
    """Send a Telegram notification with the daily brief summary.

    Fire-and-forget: Telegram failures are logged but never raised.
    Only sends if the user has a verified TelegramLink.

    Args:
        db: Database session (for looking up TelegramLink).
        user_id: The user's UUID.
        brief: The generated DailyBrief instance.

    Returns:
        True if the message was sent successfully, False otherwise.
    """
    # Respect the user's delivery channel: web_only means no Telegram push
    # (the brief is still persisted and shown in the dashboard).
    cfg = await get_or_create_config(user_id, db)
    if cfg.channel == DeliveryChannel.WEB_ONLY:
        logger.debug(
            "Brief channel is web_only, skipping Telegram notification",
            user_id=str(user_id),
        )
        return False

    link = await get_telegram_link(db, user_id)
    if link is None or not link.is_verified:
        logger.debug(
            "No verified Telegram link, skipping brief notification",
            user_id=str(user_id),
        )
        return False

    try:
        message = format_brief_message(brief)
        await send_message(link.chat_id, message)
        logger.info(
            "Telegram daily brief sent",
            user_id=str(user_id),
            brief_id=str(brief.id),
        )
        return True
    except TelegramBotError:
        logger.warning(
            "Failed to send Telegram daily brief",
            user_id=str(user_id),
            brief_id=str(brief.id),
        )
        return False
    except Exception:
        logger.error(
            "Unexpected error sending Telegram daily brief",
            user_id=str(user_id),
            brief_id=str(brief.id),
        )
        return False
