"""Deployment-wide Telegram bot configuration."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class TelegramBotConfig(Base):
    """Stores the encrypted token for the shared Telegram bot."""

    __tablename__ = "telegram_bot_configs"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_telegram_bot_configs_singleton"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bot_username: Mapped[str] = mapped_column(String(64), nullable=False)
    configured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
