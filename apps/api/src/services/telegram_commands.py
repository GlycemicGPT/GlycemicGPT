"""Stories 7.4, 7.5 & 7.6: Telegram command and chat handlers.

Routes incoming Telegram messages to the appropriate handler and
returns HTML-formatted response strings. The caller is responsible
for sending the response via ``send_message``.

Supported commands (diabetic users):
  /status      – Current glucose, trend, and IoB
  /acknowledge – Acknowledge the most recent (or a specific) alert
  /brief       – Latest daily brief summary
  /help        – List available commands

Non-command messages are routed to the AI chat handler (Story 7.5).

Caregiver users are routed to caregiver-specific handlers (Story 7.6).
"""

import html
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.units import format_glucose
from src.logging_config import get_logger
from src.models.glucose import GlucoseReading
from src.models.telegram_link import TelegramLink
from src.models.user import User, UserRole
from src.services.alert_notifier import trend_description
from src.services.brief_notifier import format_brief_message
from src.services.daily_brief import list_briefs
from src.services.glucose_unit import resolve_glucose_unit
from src.services.iob_projection import get_iob_projection, get_user_dia
from src.services.predictive_alerts import acknowledge_alert, get_active_alerts

logger = get_logger(__name__)


async def get_user_id_by_chat_id(
    db: AsyncSession,
    chat_id: int,
) -> uuid.UUID | None:
    """Look up a user ID from a Telegram chat ID.

    Args:
        db: Database session.
        chat_id: Telegram chat ID.

    Returns:
        The user's UUID, or None if no verified link exists.
    """
    result = await db.execute(
        select(TelegramLink.user_id).where(
            TelegramLink.chat_id == chat_id,
            TelegramLink.is_verified.is_(True),
        )
    )
    row = result.scalar_one_or_none()
    return row


async def get_user_role(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> UserRole | None:
    """Look up a user's role by their UUID.

    Args:
        db: Database session.
        user_id: User's UUID.

    Returns:
        The user's role, or None if user not found.
    """
    result = await db.execute(select(User.role).where(User.id == user_id))
    return result.scalar_one_or_none()


def _reading_age(reading_timestamp: datetime) -> str:
    """Return a human-friendly age string for a glucose reading."""
    delta = datetime.now(UTC) - reading_timestamp
    total_seconds = delta.total_seconds()
    if total_seconds < 0:
        return "just now"
    minutes = int(total_seconds / 60)
    if minutes < 1:
        return "just now"
    if minutes == 1:
        return "1 min ago"
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours == 1:
        return "1 hour ago"
    return f"{hours} hours ago"


async def _handle_status(db: AsyncSession, user_id: uuid.UUID) -> str:
    """Build a glucose status message.

    Includes current glucose, trend, IoB, and reading age.
    """
    # Latest glucose reading
    result = await db.execute(
        select(GlucoseReading)
        .where(GlucoseReading.user_id == user_id)
        .order_by(GlucoseReading.reading_timestamp.desc())
        .limit(1)
    )
    reading = result.scalar_one_or_none()

    if reading is None:
        return "\u2139\ufe0f No glucose data available yet."

    unit = await resolve_glucose_unit(db, user_id)
    lines = [
        "\U0001f4ca <b>Current Status</b>",
        "",
        f"\U0001f3af <b>Glucose:</b> {format_glucose(reading.value, unit)}",
        f"\U0001f4c8 <b>Trend:</b> {trend_description(reading.trend_rate)}",
        f"\U0001f551 <b>Reading:</b> {_reading_age(reading.reading_timestamp)}",
    ]

    # IoB projection
    dia = await get_user_dia(db, user_id)
    iob = await get_iob_projection(db, user_id, dia_hours=dia)
    if iob is not None:
        lines.append(f"\U0001f489 <b>IoB:</b> {iob.projected_iob:.1f} units")
        if iob.is_stale:
            lines.append("\u26a0\ufe0f IoB data is stale (>2 hours old)")

    return "\n".join(lines)


async def _handle_acknowledge(
    db: AsyncSession,
    user_id: uuid.UUID,
    args: str,
) -> str:
    """Acknowledge an active alert.

    If *args* contains an alert ID, acknowledge that specific alert.
    Otherwise acknowledge the most recent active alert.
    """
    if args:
        # Try to parse as UUID
        try:
            alert_id = uuid.UUID(args)
        except ValueError:
            return "\u274c Invalid alert ID. Use /acknowledge or /acknowledge_{id}"

        alert = await acknowledge_alert(db, user_id, alert_id)
        if alert is None:
            return "\u274c Alert not found or already acknowledged."
        return f"\u2705 Alert acknowledged: {html.escape(alert.message)}"

    # No specific ID — acknowledge most recent active alert
    active = await get_active_alerts(db, user_id, limit=1)
    if not active:
        return "\u2705 No active alerts to acknowledge."

    alert = await acknowledge_alert(db, user_id, active[0].id)
    if alert is None:
        return "\u274c Alert was already acknowledged."
    return f"\u2705 Alert acknowledged: {html.escape(alert.message)}"


async def _handle_brief(db: AsyncSession, user_id: uuid.UUID) -> str:
    """Return the latest daily brief."""
    briefs, _total = await list_briefs(user_id, db, limit=1, offset=0)

    if not briefs:
        return "\u2139\ufe0f No daily briefs available yet."

    unit = await resolve_glucose_unit(db, user_id)
    return format_brief_message(briefs[0], unit)


def _handle_help() -> str:
    """Return a help message listing all available commands."""
    return (
        "\U0001f4cb <b>Available Commands</b>\n"
        "\n"
        "/status \u2013 Current glucose, trend &amp; IoB\n"
        "/acknowledge \u2013 Acknowledge latest alert\n"
        "/brief \u2013 Latest daily brief\n"
        "/help \u2013 Show this help message\n"
        "\n"
        "\U0001f4ac Or just type a question to chat with your AI assistant."
    )


def _handle_unknown() -> str:
    """Return guidance for an unrecognized command."""
    return "\u2753 Unrecognized command.\nSend /help to see available commands."


async def _handle_chat_message(
    db: AsyncSession,
    user_id: uuid.UUID,
    text: str,
) -> str:
    """Route a non-command message to the AI chat handler.

    Uses lazy import to avoid pulling in AI dependencies at module level.
    """
    try:
        from src.services.telegram_chat import handle_chat
    except ImportError:
        logger.error("Failed to import telegram_chat module", exc_info=True)
        return (
            "\u26a0\ufe0f AI chat is temporarily unavailable. Please try again later."
        )

    return await handle_chat(db, user_id, text)


async def handle_command(
    db: AsyncSession,
    chat_id: int,
    text: str,
) -> str:
    """Route a Telegram message to the appropriate command handler.

    Always returns a response string — exceptions are caught and
    converted to user-friendly error messages.

    Args:
        db: Database session.
        chat_id: Telegram chat ID of the sender.
        text: Raw message text.

    Returns:
        HTML-formatted response string.
    """
    try:
        return await _route_command(db, chat_id, text)
    except Exception:
        logger.error(
            "Unexpected error in command handler",
            chat_id=chat_id,
            exc_info=True,
        )
        return "\u26a0\ufe0f Something went wrong. Please try again later."


async def _route_command(
    db: AsyncSession,
    chat_id: int,
    text: str,
) -> str:
    """Internal command router (may raise)."""
    # Look up user
    user_id = await get_user_id_by_chat_id(db, chat_id)
    if user_id is None:
        return (
            "\u26d4 Your Telegram account is not linked to GlycemicGPT.\n"
            "Link your account from the web app first."
        )

    # Story 7.6: Route caregiver users to caregiver-specific handlers
    user_role = await get_user_role(db, user_id)
    if user_role == UserRole.CAREGIVER:
        from src.services.telegram_caregiver import handle_caregiver_command

        return await handle_caregiver_command(db, user_id, text)

    # Normalize and parse command
    stripped = text.strip()
    lower = stripped.lower()

    if lower == "/status":
        return await _handle_status(db, user_id)

    if lower == "/acknowledge":
        return await _handle_acknowledge(db, user_id, "")

    # /acknowledge_{uuid} pattern — require non-empty args
    if lower.startswith("/acknowledge_"):
        args = stripped[13:]  # len("/acknowledge_") == 13
        if not args:
            return await _handle_acknowledge(db, user_id, "")
        return await _handle_acknowledge(db, user_id, args)

    if lower == "/brief":
        return await _handle_brief(db, user_id)

    if lower == "/help":
        return _handle_help()

    # Unrecognized /commands get unknown handler; plain text goes to AI chat
    if stripped.startswith("/"):
        return _handle_unknown()

    # Story 7.5: Route non-command messages to AI chat
    return await _handle_chat_message(db, user_id, stripped)
