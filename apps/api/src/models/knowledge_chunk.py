"""Story 35.9: Knowledge chunk model for RAG system.

Stores chunked content from clinical documents, AI research, and user
uploads with vector embeddings for semantic retrieval.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class KnowledgeChunk(Base):
    """A single chunk of knowledge content with an embedding vector.

    Trust tiers:
    - AUTHORITATIVE: FDA labels, ADA guidelines (highest trust)
    - RESEARCHED: AI-fetched from user-configured sources
    - USER_PROVIDED: User-uploaded documents (per-user scoped)
    - EXTRACTED: Facts extracted from user conversations
    """

    __tablename__ = "knowledge_chunks"

    __table_args__ = (
        Index("ix_knowledge_user_valid", "user_id", "valid_to"),
        Index("ix_knowledge_trust", "trust_tier", "valid_to"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )

    # NULL = shared (system knowledge), non-NULL = per-user
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    trust_tier: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    source_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    source_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    embedding: Mapped[list | None] = mapped_column(
        Vector(768),
        nullable=True,
    )

    metadata_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    content_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
            f"<KnowledgeChunk(id={self.id}, tier={self.trust_tier}, "
            f"source={self.source_name})>"
        )
