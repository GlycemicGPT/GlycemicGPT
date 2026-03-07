"""Plugin declaration model.

Stores the active pump plugin's metadata and category mappings per user.
One-to-one with User. Mobile pushes declarations on plugin
activate/deactivate; backend stores passively; web reads to display.
"""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin


class PluginDeclaration(Base, TimestampMixin):
    """Per-user active pump plugin declaration.

    One-to-one with User via unique constraint on user_id.
    Upserted by mobile when a pump plugin activates; deleted when it deactivates.
    """

    __tablename__ = "plugin_declarations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    plugin_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    plugin_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    plugin_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    declared_categories: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
    )

    category_mappings: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    user = relationship("User", back_populates="plugin_declaration")

    def __repr__(self) -> str:
        return (
            f"<PluginDeclaration(user_id={self.user_id}, plugin_id={self.plugin_id})>"
        )
