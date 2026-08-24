"""Story 7.1: Telegram bot setup & configuration router.

Endpoints for linking/unlinking a Telegram account and sending test messages.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.auth import AdminUser, get_current_user
from src.core.encryption import encrypt_credential
from src.database import get_db
from src.models.telegram_bot_config import TelegramBotConfig
from src.models.telegram_link import TelegramLink
from src.models.telegram_verification import TelegramVerificationCode
from src.models.user import User, UserRole
from src.schemas.auth import ErrorResponse
from src.schemas.telegram import (
    TelegramBotConfigRequest,
    TelegramBotConfigResponse,
    TelegramBotValidateResponse,
    TelegramLinkResponse,
    TelegramStatusResponse,
    TelegramTestMessageResponse,
    TelegramUnlinkResponse,
    TelegramVerificationCodeResponse,
)
from src.services.telegram_bot import (
    TelegramBotError,
    generate_verification_code,
    get_bot_identity,
    get_bot_info,
    get_telegram_bot_token,
    get_telegram_link,
    reset_bot_cache,
    send_message,
    unlink_telegram,
)

router = APIRouter(
    prefix="/api/telegram",
    tags=["telegram"],
)


async def _clear_bot_link_state(db: AsyncSession) -> None:
    """Delete link state that belongs to the active shared bot."""
    await db.execute(delete(TelegramVerificationCode))
    await db.execute(delete(TelegramLink))


async def _get_current_bot_id(
    db: AsyncSession,
    config: TelegramBotConfig | None,
) -> str | None:
    """Resolve the stable identity of the currently active shared bot."""
    if config is not None and config.bot_id is not None:
        return config.bot_id

    try:
        current_token = await get_telegram_bot_token(db)
        if not current_token:
            return None
        identity = await get_bot_identity(token=current_token)
    except TelegramBotError:
        return None
    return str(identity.bot_id)


async def _check_bot_configured(db: AsyncSession) -> None:
    """Raise 503 if the Telegram bot token is not configured."""
    if settings.telegram_bot_token:
        return
    try:
        token = await get_telegram_bot_token(db)
    except TelegramBotError:
        token = ""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot is not configured",
        )


@router.get(
    "/bot-config",
    response_model=TelegramBotConfigResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        503: {"model": ErrorResponse, "description": "Bot unavailable"},
    },
)
async def get_bot_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelegramBotConfigResponse:
    """Return safe metadata about the shared Telegram bot configuration."""
    can_manage = user.role == UserRole.ADMIN
    config = await db.get(TelegramBotConfig, 1)
    if config is not None:
        return TelegramBotConfigResponse(
            configured=True,
            can_manage=can_manage,
            bot_username=config.bot_username,
            configured_at=config.configured_at,
        )

    if not settings.telegram_bot_token:
        return TelegramBotConfigResponse(
            configured=False,
            can_manage=can_manage,
        )

    try:
        bot_username = await get_bot_info(db)
    except TelegramBotError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot is temporarily unavailable",
        )

    return TelegramBotConfigResponse(
        configured=True,
        can_manage=can_manage,
        bot_username=bot_username,
    )


@router.post(
    "/bot-config",
    response_model=TelegramBotValidateResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid bot token"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Administrator required"},
    },
)
async def save_bot_config(
    request: TelegramBotConfigRequest,
    _user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> TelegramBotValidateResponse:
    """Validate a Telegram bot token before storing it encrypted."""
    token = request.token.strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram bot token is required",
        )

    try:
        bot_identity = await get_bot_identity(token=token)
    except TelegramBotError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram rejected the bot token",
        )

    config = await db.get(TelegramBotConfig, 1)
    current_bot_id = await _get_current_bot_id(db, config)
    next_bot_id = str(bot_identity.bot_id)
    if current_bot_id != next_bot_id:
        await _clear_bot_link_state(db)

    configured_at = datetime.now(UTC)
    if config is None:
        config = TelegramBotConfig(
            id=1,
            encrypted_token=encrypt_credential(token),
            bot_id=next_bot_id,
            bot_username=bot_identity.username,
            configured_at=configured_at,
        )
        db.add(config)
    else:
        config.encrypted_token = encrypt_credential(token)
        config.bot_id = next_bot_id
        config.bot_username = bot_identity.username
        config.configured_at = configured_at

    await db.commit()
    reset_bot_cache()
    return TelegramBotValidateResponse(
        valid=True,
        bot_username=bot_identity.username,
    )


@router.delete(
    "/bot-config",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Administrator required"},
        409: {"model": ErrorResponse, "description": "Environment-managed bot"},
    },
)
async def delete_bot_config(
    _user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Remove a database-managed bot and its bot-specific link state."""
    config = await db.get(TelegramBotConfig, 1)
    if config is not None:
        await _clear_bot_link_state(db)
        await db.delete(config)
        await db.commit()
        reset_bot_cache()
    elif settings.telegram_bot_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Telegram is configured through TELEGRAM_BOT_TOKEN and must "
                "be removed from the server environment"
            ),
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/status",
    response_model=TelegramStatusResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        503: {"model": ErrorResponse, "description": "Bot unavailable"},
    },
)
async def get_telegram_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelegramStatusResponse:
    """Get the current Telegram link status.

    Returns whether the user has linked their Telegram account
    and the bot's username for linking instructions.
    """
    await _check_bot_configured(db)

    try:
        bot_username = await get_bot_info(db)
    except TelegramBotError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot is temporarily unavailable",
        )

    link = await get_telegram_link(db, user.id)

    return TelegramStatusResponse(
        linked=link is not None,
        link=(
            TelegramLinkResponse(
                id=link.id,
                chat_id=link.chat_id,
                username=link.username,
                is_verified=link.is_verified,
                linked_at=link.linked_at,
            )
            if link
            else None
        ),
        bot_username=bot_username,
    )


@router.post(
    "/link",
    response_model=TelegramVerificationCodeResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        409: {"model": ErrorResponse, "description": "Already linked"},
        503: {"model": ErrorResponse, "description": "Bot unavailable"},
    },
)
async def start_telegram_link(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelegramVerificationCodeResponse:
    """Generate a verification code for Telegram account linking.

    The user should send /start <code> to the bot on Telegram
    to complete the linking process.
    """
    await _check_bot_configured(db)

    # Check if already linked
    existing = await get_telegram_link(db, user.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Telegram account is already linked",
        )

    try:
        bot_username = await get_bot_info(db)
    except TelegramBotError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot is temporarily unavailable",
        )

    code, expires_at = await generate_verification_code(db, user.id)

    return TelegramVerificationCodeResponse(
        code=code,
        expires_at=expires_at,
        bot_username=bot_username,
    )


@router.delete(
    "/link",
    response_model=TelegramUnlinkResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Link not found"},
    },
)
async def remove_telegram_link(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelegramUnlinkResponse:
    """Unlink the user's Telegram account."""
    unlinked = await unlink_telegram(db, user.id)

    if not unlinked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No Telegram account is linked",
        )

    return TelegramUnlinkResponse(
        success=True,
        message="Telegram account has been unlinked",
    )


@router.post(
    "/test",
    response_model=TelegramTestMessageResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Telegram not linked"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        502: {"model": ErrorResponse, "description": "Message delivery failed"},
        503: {"model": ErrorResponse, "description": "Bot unavailable"},
    },
)
async def send_test_message(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelegramTestMessageResponse:
    """Send a test message to the user's linked Telegram account."""
    await _check_bot_configured(db)

    link = await get_telegram_link(db, user.id)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Telegram account is linked",
        )

    try:
        await send_message(
            link.chat_id,
            "This is a test message from Lumose. "
            "Your Telegram notifications are working correctly!",
            db,
        )
    except TelegramBotError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send test message. Please try again later.",
        )

    return TelegramTestMessageResponse(
        success=True,
        message="Test message sent successfully",
    )
