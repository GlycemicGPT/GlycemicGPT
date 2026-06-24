"""Stories 7.4, 7.5 & 7.6: Telegram command and chat handlers.

Routes incoming Telegram messages to the appropriate handler and
returns HTML-formatted response strings. The caller is responsible
for sending the response via ``send_message``.

Supported commands (diabetic users):
  /status          – Current glucose, trend, and IoB
  /acknowledge     – Acknowledge the most recent (or a specific) alert
  /brief           – Latest daily brief summary
  /chronicle tips  – Personalised tips from session history
  /help            – List available commands

Non-command messages are routed to the AI chat handler (Story 7.5).

Caregiver users are routed to caregiver-specific handlers (Story 7.6).
"""

import html
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.glucose import GlucoseReading
from src.models.telegram_link import TelegramLink
from src.models.user import User, UserRole
from src.services.alert_notifier import trend_description
from src.services.brief_notifier import format_brief_message
from src.services.chat_history import get_recent_user_messages
from src.services.daily_brief import list_briefs
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

    lines = [
        "\U0001f4ca <b>Current Status</b>",
        "",
        f"\U0001f3af <b>Glucose:</b> {reading.value:.0f} mg/dL",
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

    return format_brief_message(briefs[0])


def _handle_help() -> str:
    """Return a help message listing all available commands."""
    return (
        "\U0001f4cb <b>Available Commands</b>\n"
        "\n"
        "/status \u2013 Current glucose, trend &amp; IoB\n"
        "/acknowledge \u2013 Acknowledge latest alert\n"
        "/brief \u2013 Latest daily brief\n"
        "/chronicle tips \u2013 Personalised tips from your session history\n"
        "/help \u2013 Show this help message\n"
        "\n"
        "\U0001f4ac Or just type a question to chat with your AI assistant."
    )


def _handle_unknown() -> str:
    """Return guidance for an unrecognized command."""
    return "\u2753 Unrecognized command.\nSend /help to see available commands."


# ── /chronicle tips ──────────────────────────────────────────────────────────

_CHRONICLE_TIPS_SYSTEM_PROMPT = """\
You are a supportive diabetes management assistant integrated with GlycemicGPT. \
Based on a user's recent session history, identify patterns in the topics they ask about \
and recommend personalised, actionable tips.

Guidelines:
- Recommend 3\u20135 concise, practical tips
- Reference specific topics the user has asked about where possible
- Suggest GlycemicGPT features or follow-up actions they may find helpful
- Be supportive and non-judgmental
- Use plain text, avoid markdown (Telegram uses HTML)
- Do NOT prescribe specific insulin doses
- Frame health observations as things to discuss with their endocrinologist
"""

_CHRONICLE_SAFETY_DISCLAIMER = (
    "\n\n\u26a0\ufe0f <i>Not medical advice. Consult your healthcare provider.</i>"
)

_CHRONICLE_MAX_RESPONSE_TOKENS = 600
# Telegram's hard per-message character limit
_CHRONICLE_TELEGRAM_MAX_LENGTH = 4096


async def _handle_chronicle_tips(db: AsyncSession, user_id: uuid.UUID) -> str:
    """Generate personalised tips based on the user's session history.

    Fetches recent user messages across all conversations, then calls the
    user's configured AI provider to identify usage patterns and recommend
    actionable tips.
    """
    try:
        from fastapi import HTTPException
        from src.schemas.ai_response import AIMessage
        from src.services.ai_client import (
            get_ai_client,
            get_user_max_response_tokens,
            resolve_max_response_tokens,
        )
    except ImportError:
        logger.error("Failed to import dependencies for /chronicle tips", exc_info=True)
        return "\u26a0\ufe0f AI chat is temporarily unavailable. Please try again later."

    # Fetch User object (needed by get_ai_client)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        logger.error("User not found for /chronicle tips", user_id=str(user_id))
        return "\u26a0\ufe0f Something went wrong. Please try again later."

    # Fetch recent user messages across all conversations
    recent_messages = await get_recent_user_messages(db, user_id)
    if not recent_messages:
        return (
            "\u2139\ufe0f No session history yet.\n"
            "Start chatting with GlycemicGPT and then use /chronicle tips "
            "to receive personalised recommendations based on your usage."
        )

    # Build the prompt from the user's history
    numbered = "\n".join(
        f"{i + 1}. {msg}" for i, msg in enumerate(recent_messages)
    )
    user_message = (
        "Here are my recent questions and messages from my GlycemicGPT sessions:\n\n"
        f"{numbered}\n\n"
        "Based on these patterns, please recommend 3\u20135 personalised tips "
        "to help me better manage my diabetes and get more value from GlycemicGPT."
    )

    # Get AI client
    try:
        ai_client = await get_ai_client(user, db)
    except HTTPException as exc:
        if exc.status_code == 404:
            return (
                "\u2139\ufe0f No AI provider configured.\n"
                "Set up your AI provider in the GlycemicGPT web app "
                "under Settings to use /chronicle tips."
            )
        logger.error(
            "AI provider configuration error for /chronicle tips",
            user_id=str(user_id),
            detail=exc.detail,
        )
        return (
            "\u26a0\ufe0f There is an issue with your AI provider configuration. "
            "Please check Settings or try again later."
        )

    # Resolve per-user token budget
    try:
        override = await get_user_max_response_tokens(user, db)
        max_tokens = resolve_max_response_tokens(override, _CHRONICLE_MAX_RESPONSE_TOKENS)
    except Exception:
        max_tokens = _CHRONICLE_MAX_RESPONSE_TOKENS

    # Generate tips
    try:
        ai_response = await ai_client.generate(
            messages=[AIMessage(role="user", content=user_message)],
            system_prompt=_CHRONICLE_TIPS_SYSTEM_PROMPT,
            max_tokens=max_tokens,
        )
    except Exception:
        logger.error(
            "AI provider error in /chronicle tips",
            user_id=str(user_id),
            exc_info=True,
        )
        return (
            "\u26a0\ufe0f Unable to get a response from the AI provider. "
            "Please try again later."
        )

    content = ai_response.content.strip()
    if not content:
        return (
            "\u2139\ufe0f The AI returned an empty response. Please try again."
        )

    safe_content = html.escape(content)

    # Truncate to fit Telegram message length limit
    max_content_length = _CHRONICLE_TELEGRAM_MAX_LENGTH - len(_CHRONICLE_SAFETY_DISCLAIMER)
    if len(safe_content) > max_content_length:
        safe_content = safe_content[: max_content_length - 3] + "..."

    logger.info(
        "/chronicle tips response generated",
        user_id=str(user_id),
        model=ai_response.model,
        history_count=len(recent_messages),
    )

    return safe_content + _CHRONICLE_SAFETY_DISCLAIMER


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

    if lower in ("/chronicle", "/chronicle tips"):
        return await _handle_chronicle_tips(db, user_id)

    if lower == "/help":
        return _handle_help()

    # Unrecognized /commands get unknown handler; plain text goes to AI chat
    if stripped.startswith("/"):
        return _handle_unknown()

    # Story 7.5: Route non-command messages to AI chat
    return await _handle_chat_message(db, user_id, stripped)
