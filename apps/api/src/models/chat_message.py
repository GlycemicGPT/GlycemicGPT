"""Story 35.3: Chat message model for conversation memory.

Persists user and assistant messages so AI chat has multi-turn context.
Messages are grouped into conversations by conversation_id.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class ChatRole(str, enum.Enum):
    """Role of a chat message sender."""

    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(Base):
    """Stores individual chat messages for conversation memory.

    Messages are grouped by conversation_id. A new conversation starts
    when the user's last message is older than the inactivity threshold
    (default 30 minutes) or when they explicitly clear the chat.
    """

    __tablename__ = "chat_messages"

    __table_args__ = (
        Index("ix_chat_messages_user_conv", "user_id", "conversation_id"),
        Index(
            "ix_chat_messages_user_created",
            "user_id",
            "created_at",
            postgresql_using="btree",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    role: Mapped[ChatRole] = mapped_column(
        Enum(ChatRole, native_enum=False, length=20),
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Token count for this message (estimated or from provider)
    token_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # Which AI model generated this (null for user messages)
    model: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<ChatMessage(id={self.id}, user_id={self.user_id}, "
            f"role={self.role.value}, conv={self.conversation_id})>"
        )
