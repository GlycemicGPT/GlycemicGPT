"""Story 43.1: Nightscout connection model.

Stores per-user configuration for Nightscout / Nocturne (and connected
platforms) integrations. Multiple connections per user allowed (no
unique constraint on user_id) so users can register test instances or
fallback URLs alongside their primary instance.

The actual HTTP client lives in `src/services/integrations/nightscout/`
(Story 43.2). This model just holds the credentials, sync configuration,
and discovery metadata.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin


class NightscoutAuthType(str, enum.Enum):
    """Auth modes Nightscout supports.

    - secret: legacy v1 auth -- SHA-1 hash of API_SECRET in `api-secret` header
    - token: v3 JWT bearer token in Authorization header
    - auto: client auto-detects which the instance accepts
    """

    SECRET = "secret"
    TOKEN = "token"
    AUTO = "auto"


class NightscoutApiVersion(str, enum.Enum):
    """Which Nightscout API version to target.

    - v1: cgm-remote-monitor v1 (most widely deployed)
    - v3: modern Nightscout v3 (Nocturne also implements this)
    - auto: client tries v1 first (more widely deployed), falls back
      to v3 if the v1 status endpoint returns 404
    """

    V1 = "v1"
    V3 = "v3"
    AUTO = "auto"


class NightscoutSyncStatus(str, enum.Enum):
    """Last sync outcome for monitoring + UI display."""

    NEVER = "never"  # Connection created, no sync attempted yet
    OK = "ok"
    ERROR = "error"  # Generic transient failure
    AUTH_FAILED = "auth_failed"  # 401/403 -- user must re-authenticate
    RATE_LIMITED = "rate_limited"  # 429 from upstream
    NETWORK = "network"  # DNS / TCP / TLS failure
    UNREACHABLE = "unreachable"  # Repeated failures, polling paused


# Sync interval bounds (server-enforced; matches Story 43.4 AC2).
SYNC_INTERVAL_MIN_MINUTES = 1
SYNC_INTERVAL_MAX_MINUTES = 24 * 60  # 24 hours
SYNC_INTERVAL_DEFAULT_MINUTES = 5  # Matches CGM cadence + existing Dexcom sync

# Initial-sync window options (Story 43.7 wizard surfaces these).
INITIAL_SYNC_WINDOW_DAYS_DEFAULT = 7
INITIAL_SYNC_WINDOW_DAYS_OPTIONS = (1, 7, 30, 90, 0)  # 0 means "All available"


class NightscoutConnection(Base, TimestampMixin):
    """A user's link to a Nightscout (or Nocturne) instance.

    Multiple per user permitted -- a user might have a primary instance,
    a backup, and a personal test instance.

    Lifecycle semantics:

    - **Soft-delete** (DELETE endpoint): sets is_active=false. Historical
      data ingested through the connection retains its
      "nightscout:<connection_id>" source attribution; the row stays
      queryable so the dashboard can render past per-source freshness.
    - **Account deletion**: User has cascade="all, delete-orphan" on
      this relationship + the FK uses ondelete=CASCADE. When the user
      is deleted (account erasure / GDPR right-to-be-forgotten), all
      their NightscoutConnection rows hard-delete along with the rest
      of their data. This is intentional: when a user disappears,
      preserving an attribution string for data that no longer exists
      isn't useful.
    """

    __tablename__ = "nightscout_connections"

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

    # Human-readable name shown in dashboards (user-supplied)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    # Base URL of the Nightscout instance (e.g. https://my-ns.example.com)
    # No trailing slash; validated at the schema layer.
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)

    # Auth configuration. The credential itself is encrypted via
    # src.core.encryption.encrypt_credential() before persisting.
    auth_type: Mapped[NightscoutAuthType] = mapped_column(
        Enum(
            NightscoutAuthType,
            name="nightscoutauthtype",
            values_callable=lambda e: [member.value for member in e],
            create_type=False,  # Created by migration 051
        ),
        nullable=False,
        default=NightscoutAuthType.AUTO,
    )

    # Encrypted secret (v1) OR encrypted token (v3). Never plaintext.
    encrypted_credential: Mapped[str] = mapped_column(Text, nullable=False)

    api_version: Mapped[NightscoutApiVersion] = mapped_column(
        Enum(
            NightscoutApiVersion,
            name="nightscoutapiversion",
            values_callable=lambda e: [member.value for member in e],
            create_type=False,  # Created by migration 051
        ),
        nullable=False,
        default=NightscoutApiVersion.AUTO,
    )

    # Soft-delete flag. False rather than DELETE to preserve historical
    # per-source attribution on chunks the connection ingested.
    # No standalone index here -- the composite index
    # (user_id, is_active) created in migration 051 covers the
    # primary access path: "user's active connections."
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    # Sync configuration (resolved decisions 2026-05-05).
    sync_interval_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=SYNC_INTERVAL_DEFAULT_MINUTES,
    )
    initial_sync_window_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=INITIAL_SYNC_WINDOW_DAYS_DEFAULT,
    )

    # Last sync outcome (Story 43.4 writes; Story 43.5 reads for UI badges).
    last_sync_status: Mapped[NightscoutSyncStatus] = mapped_column(
        Enum(
            NightscoutSyncStatus,
            name="nightscoutsyncstatus",
            values_callable=lambda e: [member.value for member in e],
            create_type=False,  # Created by migration 051
        ),
        nullable=False,
        default=NightscoutSyncStatus.NEVER,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Discovery metadata (set by Story 43.7 evaluate endpoint).
    # Stores: detected_uploaders, has_treatments, has_profile, etc.
    detected_uploaders_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationship back to the owning user.
    user = relationship("User", back_populates="nightscout_connections")

    @property
    def has_credential(self) -> bool:
        """For response serialization -- never expose the credential itself."""
        return bool(self.encrypted_credential)

    def __repr__(self) -> str:
        return (
            f"<NightscoutConnection(id={self.id}, user_id={self.user_id}, "
            f"name={self.name!r}, active={self.is_active}, "
            f"status={self.last_sync_status.value})>"
        )
