"""Per-user Tandem cloud-sync (download) control state.

Holds each user's toggle + cadence for the Tandem t:connect event sync.
Only *control* fields live here; sync freshness (`last_sync_at`,
`last_error`, `status`) stays on ``IntegrationCredential``, which
``sync_tandem_for_user`` already maintains -- this row must not duplicate
that, to avoid two sources of truth.

Absence of a row is meaningful: a connected Tandem user with NO row is
treated as **enabled at the default interval** (backward compatible with
the pre-existing global sync, which synced every connected user). The row
exists only to let a user change their interval or opt out.
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
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin

# Per-user sync cadence bounds. Floor of 15 min is deliberate: t:connect
# itself only refreshes the cloud roughly hourly, so sub-15-min polling
# cannot surface fresher data and just wastes upstream calls. Ceiling of
# one day covers "only pull occasionally" users.
SYNC_INTERVAL_MIN_MINUTES = 15
SYNC_INTERVAL_MAX_MINUTES = 1440
SYNC_INTERVAL_DEFAULT_MINUTES = 60


class TandemSyncState(Base, TimestampMixin):
    """User-specific Tandem cloud-sync control. One-to-one with User."""

    __tablename__ = "tandem_sync_state"

    # Declared here too (not just in the migration) so metadata-built test
    # DBs enforce it and `alembic --autogenerate` doesn't propose dropping it.
    __table_args__ = (
        CheckConstraint(
            f"sync_interval_minutes BETWEEN {SYNC_INTERVAL_MIN_MINUTES} "
            f"AND {SYNC_INTERVAL_MAX_MINUTES}",
            name="ck_tandem_sync_state_interval_bounds",
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

    # Cumulative count of events stored across all syncs for this user,
    # surfaced in the UI. Display-only; not used for any sync decision.
    events_pulled_total: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )

    # Last time the scheduler ATTEMPTED a sync for this user (success OR
    # failure). The scheduler paces retries by this, NOT by the credential's
    # ``last_sync_at`` (which only advances on success) -- otherwise a
    # persistently-failing user would be retried on every short tick instead
    # of once per their interval. NULL until the first scheduled attempt.
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    user = relationship("User", back_populates="tandem_sync_state")

    def __repr__(self) -> str:
        return (
            f"<TandemSyncState(user_id={self.user_id}, "
            f"enabled={self.enabled}, interval={self.sync_interval_minutes}m)>"
        )
