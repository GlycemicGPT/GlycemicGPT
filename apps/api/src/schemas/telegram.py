"""Story 7.1: Telegram bot schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TelegramBotConfigRequest(BaseModel):
    """Token submitted for validation and encrypted persistence."""

    token: str = Field(min_length=1, max_length=512)


class TelegramBotConfigResponse(BaseModel):
    """Safe Telegram bot configuration metadata."""

    configured: bool
    can_manage: bool
    bot_username: str | None = None
    configured_at: datetime | None = None


class TelegramBotValidateResponse(BaseModel):
    """Successful Telegram token validation response."""

    valid: bool
    bot_username: str


class TelegramLinkResponse(BaseModel):
    """Response schema for an existing Telegram link."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    chat_id: int
    username: str | None
    is_verified: bool
    linked_at: datetime


class TelegramStatusResponse(BaseModel):
    """Response schema for GET /api/telegram/status."""

    linked: bool
    link: TelegramLinkResponse | None = None
    bot_username: str


class TelegramVerificationCodeResponse(BaseModel):
    """Response schema for POST /api/telegram/link (generate code)."""

    code: str
    expires_at: datetime
    bot_username: str


class TelegramUnlinkResponse(BaseModel):
    """Response schema for DELETE /api/telegram/link."""

    success: bool
    message: str


class TelegramTestMessageResponse(BaseModel):
    """Response schema for POST /api/telegram/test."""

    success: bool
    message: str
