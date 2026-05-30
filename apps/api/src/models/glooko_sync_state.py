"""Per-user Glooko (Omnipod Cloud Sync) autonomous-sync state.

The Glooko follower sync (Tandem/Medtronic parity) stores everything it needs in
this one self-contained row. Unlike Tandem there is no pre-existing Glooko
``IntegrationCredential``, so -- mirroring ``MedtronicConnectState`` -- this table
holds both the encrypted credentials AND the control + freshness fields.

Two things differ from the Medtronic sibling, driven by the Glooko protocol
(``glooko-reverse-engineering.md``, Story 47.A):

  * **Credentials are the user's email + password**, replayed via the web Devise
    login on every sync (the ``_logbook-web_session`` cookie is ephemeral and
    re-minted on 401), NOT a rotating refresh token. Both are Fernet-encrypted.
  * **Two retrieval paths need two kinds of cursor.** Pump data uses a keyset
    cursor (``lastUpdatedAt`` + ``lastGuid``) that advances *independently per
    ``/api/v2/*`` stream*, so we persist them together as a JSONB map
    (``stream_cursors``) rather than a column pair per stream. CGM glucose comes
    from the date-windowed ``/api/v3/graph`` path, so it tracks a single
    ``last_cgm_window_end`` instead.

Absence of a row means "not connected" -- the user must complete the one-time
connect first; the scheduler skips users without a row or with ``enabled = false``.
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

# Glooko refreshes its cloud snapshot on the order of minutes; a 15-min floor
# avoids hammering upstream for no fresher data. One-day ceiling covers
# "occasional pull" users. Mirrors the Medtronic/Tandem bounds.
SYNC_INTERVAL_MIN_MINUTES = 15
SYNC_INTERVAL_MAX_MINUTES = 1440
SYNC_INTERVAL_DEFAULT_MINUTES = 30

# Status values (plain strings, matching the Medtronic sibling -- not coupled to
# the ``integrationstatus`` Postgres enum).
STATUS_PENDING = "pending"
STATUS_CONNECTED = "connected"
STATUS_ERROR = "error"
STATUS_DISCONNECTED = "disconnected"


class GlookoSyncState(Base, TimestampMixin):
    """User-specific Glooko autonomous-sync state. One-to-one with User."""

    __tablename__ = "glooko_sync_state"

    __table_args__ = (
        CheckConstraint(
            f"sync_interval_minutes BETWEEN {SYNC_INTERVAL_MIN_MINUTES} "
            f"AND {SYNC_INTERVAL_MAX_MINUTES}",
            name="ck_glooko_sync_state_interval_bounds",
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

    # Region key ("US" / "EU") -- selects the region-prefixed web + API hosts.
    # See services.integrations.glooko.auth.REGIONS.
    region: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="US",
        server_default="US",
    )

    # Fernet-encrypted Glooko account email + password. Replayed via the web
    # Devise login on each sync (the session cookie is ephemeral, re-minted on
    # 401), so -- unlike the Medtronic refresh token -- these are NOT rotated.
    encrypted_email: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_password: Mapped[str] = mapped_column(Text, nullable=False)

    # When the user explicitly acknowledged the Glooko ToS / account-ban risk at
    # connect time. Stamped server-side with the connect timestamp (never a
    # client-supplied value); NULL means consent was never recorded. Lives on the
    # row it governs, so disconnect (row delete) clears it and reconnecting
    # re-requires consent.
    consent_acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

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

    # Last SUCCESSFUL incremental sync. A one-time historical import does NOT
    # bump this (it backfills the past, it doesn't make the connection fresher).
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

    # Patient identifiers discovered at login (``/api/v3/session/users``): the
    # ``glookoCode`` slug every data call keys on, plus the Mongo OID. Persisted
    # for visibility/debugging; the live session re-discovers them each login.
    patient_slug: Mapped[str | None] = mapped_column(String(64), nullable=True)
    patient_oid: Mapped[str | None] = mapped_column(String(24), nullable=True)

    # Per-stream keyset cursor for the ``/api/v2/*`` pump streams. Shape:
    # ``{<stream>: {"last_updated_at": <iso>, "last_guid": <uuid>}}``. The
    # streams advance independently, so one JSONB map beats a column pair each.
    # Reassigned (never mutated in place) so SQLAlchemy flushes the change.
    stream_cursors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # High-water mark for the date-windowed CGM (``/api/v3/graph``) path. The
    # next incremental sync fetches from here (minus a small overlap) to now.
    last_cgm_window_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    user = relationship("User", back_populates="glooko_sync_state")

    def __repr__(self) -> str:
        return (
            f"<GlookoSyncState(user_id={self.user_id}, "
            f"region={self.region}, enabled={self.enabled}, status={self.status})>"
        )
