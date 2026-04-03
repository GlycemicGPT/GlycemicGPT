"""Story 7.1: Telegram bot service.

Handles all Telegram Bot API interactions: bot info, messaging,
verification code generation, and account linking via polling.
"""

import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.logging_config import get_logger
from src.models.telegram_link import TelegramLink
from src.models.telegram_verification import TelegramVerificationCode

logger = get_logger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot"

# Verification code config
CODE_LENGTH = 6
CODE_EXPIRY_MINUTES = 10
# Exclude ambiguous characters (0/O, 1/I/l)
CODE_ALPHABET = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"

# Module-level state for polling offset (single-process)
_last_update_offset: int | None = None

# Cached bot info
_bot_username: str | None = None


class TelegramBotError(Exception):
    """Error communicating with the Telegram Bot API."""


def _get_api_url(method: str) -> str:
    """Build Telegram Bot API URL for a given method."""
    return f"{TELEGRAM_API_BASE}{settings.telegram_bot_token}/{method}"


async def get_bot_info() -> str:
    """Get the bot's username by calling Telegram getMe.

    Returns:
        The bot's username (without @).

    Raises:
        TelegramBotError: If the bot token is invalid or API call fails.
    """
    global _bot_username

    if _bot_username is not None:
        return _bot_username

    if not settings.telegram_bot_token:
        raise TelegramBotError("Telegram bot token is not configured")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(_get_api_url("getMe"))

    if response.status_code != 200:
        raise TelegramBotError(
            f"Telegram API error: {response.status_code} {response.text}"
        )

    data = response.json()
    if not data.get("ok"):
        raise TelegramBotError(
            f"Telegram API returned error: {data.get('description', 'Unknown')}"
        )

    _bot_username = data["result"]["username"]
    return _bot_username


async def send_message(chat_id: int, text: str) -> bool:
    """Send a message to a Telegram chat.

    Args:
        chat_id: Telegram chat ID to send to.
        text: Message text (HTML formatting supported).

    Returns:
        True if message was sent successfully.

    Raises:
        TelegramBotError: If the API call fails.
    """
    if not settings.telegram_bot_token:
        raise TelegramBotError("Telegram bot token is not configured")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            _get_api_url("sendMessage"),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            },
        )

    if response.status_code != 200:
        raise TelegramBotError(
            f"Failed to send message: {response.status_code} {response.text}"
        )

    data = response.json()
    if not data.get("ok"):
        raise TelegramBotError(
            f"Send message failed: {data.get('description', 'Unknown')}"
        )

    return True


async def get_updates(offset: int | None = None) -> list[dict]:
    """Get updates from Telegram using long polling.

    Args:
        offset: Offset for the next batch of updates.

    Returns:
        List of update objects from Telegram.

    Raises:
        TelegramBotError: If the API call fails.
    """
    if not settings.telegram_bot_token:
        raise TelegramBotError("Telegram bot token is not configured")

    params: dict = {"timeout": 1, "allowed_updates": '["message"]'}
    if offset is not None:
        params["offset"] = offset

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            _get_api_url("getUpdates"),
            params=params,
        )

    if response.status_code != 200:
        raise TelegramBotError(
            f"Failed to get updates: {response.status_code} {response.text}"
        )

    data = response.json()
    if not data.get("ok"):
        raise TelegramBotError(
            f"Get updates failed: {data.get('description', 'Unknown')}"
        )

    return data.get("result", [])


def _generate_code() -> str:
    """Generate a random verification code."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


async def generate_verification_code(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> tuple[str, datetime]:
    """Generate a verification code for Telegram linking.

    Upsert semantics: replaces any existing code for the user.

    Args:
        db: Database session.
        user_id: User's UUID.

    Returns:
        Tuple of (code, expires_at).
    """
    # Delete any existing code for this user
    await db.execute(
        delete(TelegramVerificationCode).where(
            TelegramVerificationCode.user_id == user_id
        )
    )

    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=CODE_EXPIRY_MINUTES)

    # Retry on code collision (astronomically unlikely but defensive)
    for _attempt in range(3):
        code = _generate_code()
        verification = TelegramVerificationCode(
            user_id=user_id,
            code=code,
            expires_at=expires_at,
        )
        db.add(verification)
        try:
            await db.commit()
            break
        except (IntegrityError, OperationalError):
            await db.rollback()
            # Delete again in case rollback restored the old row
            await db.execute(
                delete(TelegramVerificationCode).where(
                    TelegramVerificationCode.user_id == user_id
                )
            )
    else:
        raise TelegramBotError("Failed to generate unique verification code")

    logger.info(
        "Verification code generated",
        user_id=str(user_id),
        expires_at=expires_at.isoformat(),
    )

    return code, expires_at


async def verify_telegram_link(
    db: AsyncSession,
    code: str,
    chat_id: int,
    username: str | None,
) -> bool:
    """Verify a Telegram linking code and create the link.

    Args:
        db: Database session.
        code: Verification code from /start message.
        chat_id: Telegram chat ID of the user.
        username: Telegram username (if available).

    Returns:
        True if verification succeeded, False otherwise.
    """
    now = datetime.now(UTC)

    # Look up the verification code
    result = await db.execute(
        select(TelegramVerificationCode).where(
            TelegramVerificationCode.code == code,
            TelegramVerificationCode.expires_at > now,
        )
    )
    verification = result.scalar_one_or_none()

    if verification is None:
        logger.debug("Invalid or expired verification code", code=code)
        return False

    user_id = verification.user_id

    # Delete the verification code (consumed)
    await db.delete(verification)

    # Check if user already has a link (shouldn't happen, but be safe)
    existing = await db.execute(
        select(TelegramLink).where(TelegramLink.user_id == user_id)
    )
    if existing.scalar_one_or_none() is not None:
        await db.commit()
        logger.warning("User already has Telegram link", user_id=str(user_id))
        return False

    # Check if this chat_id is already linked to another user
    existing_chat = await db.execute(
        select(TelegramLink).where(TelegramLink.chat_id == chat_id)
    )
    if existing_chat.scalar_one_or_none() is not None:
        await db.commit()
        logger.warning(
            "Chat ID already linked to another user",
            chat_id=chat_id,
        )
        return False

    # Create the link
    link = TelegramLink(
        user_id=user_id,
        chat_id=chat_id,
        username=username,
        is_verified=True,
        linked_at=now,
    )
    db.add(link)
    await db.commit()

    logger.info(
        "Telegram account linked",
        user_id=str(user_id),
        chat_id=chat_id,
        username=username,
    )

    # Send confirmation message
    try:
        await send_message(
            chat_id,
            "Your Telegram account has been linked to GlycemicGPT! "
            "You will now receive glucose alerts and notifications here.",
        )
    except TelegramBotError:
        logger.warning(
            "Failed to send confirmation message",
            chat_id=chat_id,
        )

    return True


async def poll_and_handle_messages(db: AsyncSession) -> int:
    """Poll Telegram for messages and route to appropriate handlers.

    Handles /start verification messages directly, and dispatches all
    other commands to ``telegram_commands.handle_command``.

    Args:
        db: Database session.

    Returns:
        Number of messages processed (verifications + commands).
    """
    # Lazy import to avoid circular dependency
    # (telegram_commands -> alert_notifier -> telegram_bot)
    from src.services.telegram_commands import handle_command

    global _last_update_offset

    updates = await get_updates(_last_update_offset)

    if not updates:
        return 0

    processed = 0

    for update in updates:
        # Update the offset to acknowledge this update
        update_id = update.get("update_id", 0)
        _last_update_offset = update_id + 1

        message = update.get("message", {})
        text = message.get("text", "")
        chat = message.get("chat", {})
        from_user = message.get("from", {})

        chat_id = chat.get("id")
        username = from_user.get("username")

        if not chat_id or not text:
            continue

        # Parse /start <code> command (handled locally for verification)
        if text.startswith("/start "):
            code = text[7:].strip()
            if code:
                success = await verify_telegram_link(db, code, chat_id, username)
                if success:
                    processed += 1
                else:
                    try:
                        await send_message(
                            chat_id,
                            "Invalid or expired verification code. "
                            "Please generate a new code from the GlycemicGPT web app.",
                        )
                    except TelegramBotError:
                        pass
        elif text == "/start":
            try:
                await send_message(
                    chat_id,
                    "Welcome to GlycemicGPT! To link your account, "
                    "please generate a verification code from the web app "
                    "and send: /start YOUR_CODE",
                )
            except TelegramBotError:
                pass
        else:
            # Story 7.4: Route all other messages to command handlers
            try:
                response = await handle_command(db, chat_id, text)
                await send_message(chat_id, response)
                processed += 1
            except TelegramBotError:
                logger.warning(
                    "Failed to send command response",
                    chat_id=chat_id,
                    exc_info=True,
                )
            except Exception:
                logger.error(
                    "Unexpected error handling command",
                    chat_id=chat_id,
                    exc_info=True,
                )

    return processed


# Backward-compatible alias
poll_for_verifications = poll_and_handle_messages


async def get_telegram_link(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> TelegramLink | None:
    """Get the Telegram link for a user.

    Args:
        db: Database session.
        user_id: User's UUID.

    Returns:
        TelegramLink or None if not linked.
    """
    result = await db.execute(
        select(TelegramLink).where(TelegramLink.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def unlink_telegram(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> bool:
    """Unlink a user's Telegram account.

    Args:
        db: Database session.
        user_id: User's UUID.

    Returns:
        True if unlinked, False if not linked.
    """
    result = await db.execute(
        select(TelegramLink).where(TelegramLink.user_id == user_id)
    )
    link = result.scalar_one_or_none()

    if link is None:
        return False

    chat_id = link.chat_id
    await db.delete(link)

    # Also clean up any pending verification codes
    await db.execute(
        delete(TelegramVerificationCode).where(
            TelegramVerificationCode.user_id == user_id
        )
    )

    await db.commit()

    logger.info("Telegram account unlinked", user_id=str(user_id))

    # Send farewell message
    try:
        await send_message(
            chat_id,
            "Your Telegram account has been unlinked from GlycemicGPT. "
            "You will no longer receive notifications here.",
        )
    except TelegramBotError:
        pass

    return True


def reset_bot_cache() -> None:
    """Reset cached bot info. Used for testing."""
    global _bot_username, _last_update_offset
    _bot_username = None
    _last_update_offset = None
