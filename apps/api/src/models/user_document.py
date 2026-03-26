"""Story 35.9: User document model for uploaded files.

Stores metadata for user-uploaded documents (lab results, doctor's notes,
care plans) that are processed and chunked into knowledge_chunks.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class UserDocument(Base):
    """Metadata for a user-uploaded document.

    The actual file is stored on disk (uploads volume). The extracted
    text is chunked and embedded into knowledge_chunks with
    trust_tier=USER_PROVIDED and user_id scoping.
    """

    __tablename__ = "user_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    file_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    file_size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    storage_path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    extracted_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    chunk_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    injection_risk: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<UserDocument(id={self.id}, filename={self.filename}, "
            f"type={self.file_type})>"
        )
