"""Device-status snapshot model.

Periodic snapshots of the user's closed-loop state, written by the
Nightscout translator on each devicestatus fetch. Captures IOB / COB,
pump battery + reservoir, the current closed-loop dosing decision
(suggested/enacted blocks preserved verbatim including the `reason`
free-text string), and the loop's predicted-BG arrays.

Downstream consumers (AI chat for rich context, advanced web views
for closed-loop analysis) read recent rows. Translator never modifies
the verbatim subtree blobs and never strips `predBGs` -- those are the
high-signal artifacts the AI uses to explain "why did my loop dose what
it dosed at 14:30?".

Per-connection dedupe by Nightscout-assigned `_id`; same record across
sync cycles upserts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class DeviceStatusSnapshot(Base):
    """A single point-in-time snapshot of the closed-loop state."""

    __tablename__ = "device_status_snapshots"

    __table_args__ = (
        # Per-connection dedupe by Nightscout-assigned ns_id.
        Index(
            "ix_devicestatus_connection_nsid",
            "nightscout_connection_id",
            "ns_id",
            unique=True,
        ),
        # Time-window query index: "give me the latest IOB for this
        # user" / "snapshots in the last 30 min".
        Index(
            "ix_devicestatus_user_timestamp",
            "user_id",
            "snapshot_timestamp",
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
    )

    nightscout_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nightscout_connections.id", ondelete="CASCADE"),
        nullable=False,
    )

    snapshot_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # ---- Source attribution ---------------------------------------------

    source_uploader: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_device: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ns_id: Mapped[str] = mapped_column(Text, nullable=False)

    # ---- Extracted scalars (frequently queried) -------------------------

    iob_units: Mapped[float | None] = mapped_column(Float, nullable=True)
    cob_grams: Mapped[float | None] = mapped_column(Float, nullable=True)
    pump_battery_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pump_reservoir_units: Mapped[float | None] = mapped_column(Float, nullable=True)
    pump_suspended: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    loop_failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- Verbatim subtree blobs -----------------------------------------
    # Translator preserves these as-is; never modify, never parse the
    # `reason` free-text strings here, never strip `predBGs`. AI and
    # advanced analytics layers do the parsing work.

    loop_subtree_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    openaps_subtree_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    pump_subtree_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    uploader_subtree_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )

    # ---- Relationships ---------------------------------------------------

    user = relationship("User")
    connection = relationship("NightscoutConnection")

    def __repr__(self) -> str:
        return (
            f"<DeviceStatusSnapshot(user_id={self.user_id}, "
            f"uploader={self.source_uploader!r}, "
            f"snapshot_timestamp={self.snapshot_timestamp})>"
        )
