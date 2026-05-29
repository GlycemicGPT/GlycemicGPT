"""Per-user Medtronic CareLink CarePartner (Connect) autonomous-sync state.

The autonomous follower sync (Tandem parity) stores everything it needs in this
one self-contained row -- unlike Tandem, there is no pre-existing Medtronic
``IntegrationCredential`` to hang freshness off, so consolidating here keeps a
single source of truth and isolates this opt-in feature behind its own table.

Holds:
  - the encrypted Auth0 **refresh token** (rotated each sync cycle) + CareLink
    username + region needed to mint access tokens and call display/message;
  - the control fields (enabled, interval);
  - sync freshness (status, last_sync_at, last_error, last_attempt_at) +
    a cumulative readings counter for the UI.

Unlike ``TandemSyncState``, absence of a row means "not connected" (the user
must complete the one-time CarePartner login first); the scheduler skips users
without a row or with ``enabled = false``.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

# CarePartner refreshes its cloud snapshot roughly every ~5 min; a 15-min floor
# avoids hammering upstream for no fresher data. One-day ceiling covers
# "occasional pull" users.
SYNC_INTERVAL_MIN_MINUTES = 15
SYNC_INTERVAL_MAX_MINUTES = 1440
SYNC_INTERVAL_DEFAULT_MINUTES = 30

# Status values (kept as plain strings to avoid coupling to the
# ``integrationstatus`` Postgres enum).
STATUS_PENDING = "pending"
STATUS_CONNECTED = "connected"
STATUS_ERROR = "error"
STATUS_DISCONNECTED = "disconnected"


class MedtronicConnectState(Base, TimestampMixin):
    """User-specific Medtronic Connect autonomous-sync state. One-to-one with User."""

    __tablename__ = "medtronic_connect_state"

    __table_args__ = (
        CheckConstraint(
            f"sync_interval_minutes BETWEEN {SYNC_INTERVAL_MIN_MINUTES} "
            f"AND {SYNC_INTERVAL_MAX_MINUTES}",
            name="ck_medtronic_connect_state_interval_bounds",
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
        unique=True,
        index=True,
    )

    # CarePartner region key ("US" / "EU") -- selects the Auth0 tenant + cloud
    # host. See services.integrations.medtronic.connect_auth.REGIONS.
    region: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="US",
        server_default="US",
    )

    # Fernet-encrypted CareLink username (sent in the display/message body).
    encrypted_username: Mapped[str] = mapped_column(Text, nullable=False)

    # Fernet-encrypted Auth0 refresh token. ROTATED: each refresh grant returns
    # a new token that replaces this one (the old one is then dead).
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)

    # "patient" (self-sync) or "carepartner" (follower). patient_id is only set
    # (and encrypted) for follower mode.
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="patient",
        server_default="patient",
    )
    encrypted_patient_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    sync_interval_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=SYNC_INTERVAL_DEFAULT_MINUTES,
        server_default=str(SYNC_INTERVAL_DEFAULT_MINUTES),
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=STATUS_PENDING,
        server_default=STATUS_PENDING,
    )

    # Last SUCCESSFUL sync.
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Last scheduler ATTEMPT (success or failure). The scheduler paces by this,
    # not last_sync_at, so a failing user is retried once per interval rather
    # than on every short tick.
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Cumulative glucose readings stored across all syncs (UI display only).
    readings_synced_total: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )

    user = relationship("User", back_populates="medtronic_connect_state")

    def __repr__(self) -> str:
        return (
            f"<MedtronicConnectState(user_id={self.user_id}, "
            f"region={self.region}, enabled={self.enabled}, status={self.status})>"
        )
