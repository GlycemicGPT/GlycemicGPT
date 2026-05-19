"""Story 3.1: Integration credentials model.

Models for storing encrypted third-party API credentials.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin


class IntegrationType(str, enum.Enum):
    """Supported integration types."""

    DEXCOM = "dexcom"
    TANDEM = "tandem"


class IntegrationStatus(str, enum.Enum):
    """Integration connection status."""

    PENDING = "pending"  # Credentials saved but not validated
    CONNECTED = "connected"  # Successfully validated
    ERROR = "error"  # Validation failed
    DISCONNECTED = "disconnected"  # User disconnected


class IntegrationCredential(Base, TimestampMixin):
    """Stores encrypted credentials for third-party integrations.

    Each user can have one credential per integration type.
    Credentials are encrypted using Fernet symmetric encryption.
    """

    __tablename__ = "integration_credentials"

    __table_args__ = (
        UniqueConstraint("user_id", "integration_type", name="uq_user_integration"),
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

    integration_type: Mapped[IntegrationType] = mapped_column(
        Enum(
            IntegrationType,
            name="integrationtype",
            create_type=False,
            values_callable=lambda e: [member.value for member in e],
        ),
        nullable=False,
    )

    # Encrypted credentials (email/username)
    encrypted_username: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Encrypted password
    encrypted_password: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Connection status
    status: Mapped[IntegrationStatus] = mapped_column(
        Enum(
            IntegrationStatus,
            name="integrationstatus",
            create_type=False,
            values_callable=lambda e: [member.value for member in e],
        ),
        nullable=False,
        default=IntegrationStatus.PENDING,
    )

    # Last successful sync timestamp
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Last error message (if any)
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Per-integration region/country selector.
    # - Tandem: ISO-3166-1 alpha-2 country code (US, GB, DE, CA, ...) used to
    #   resolve the per-country upload config and cloud bucket. Legacy rows may
    #   still hold "EU" -- src.core.tandem_regions.is_legacy_tandem_region()
    #   detects these and the upload service forces the user to re-select.
    # - Dexcom: pydexcom region ("US", "OUS", or "JP") for Share API routing.
    region: Mapped[str] = mapped_column(
        String(10),
        default="US",
        nullable=False,
        server_default="US",
    )

    # Relationship to user
    user = relationship("User", back_populates="integrations")

    def __repr__(self) -> str:
        return f"<IntegrationCredential(user_id={self.user_id}, type={self.integration_type.value}, status={self.status.value})>"
