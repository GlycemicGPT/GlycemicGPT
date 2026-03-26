"""Story 35.9: Research source model for configurable knowledge sources.

Stores per-user allowlisted URLs that the AI research pipeline can
fetch clinical documentation from.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class ResearchSource(Base):
    """A user-configurable URL for AI-driven clinical research.

    Users add sources based on their specific devices, medications, and
    CGMs. The research pipeline fetches content from these URLs and
    updates the knowledge base with diff-based change detection.
    """

    __tablename__ = "research_sources"

    __table_args__ = (Index("ix_research_user_active", "user_id", "is_active"),)

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

    url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    category: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    last_researched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_content_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<ResearchSource(id={self.id}, name={self.name}, url={self.url[:50]})>"
