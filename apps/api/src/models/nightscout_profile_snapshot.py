"""Nightscout profile snapshot model.

Read-only mirror of the user's Nightscout profile, written by the
Nightscout translator on each profile fetch and read by the onboarding
wizard to pre-fill the user's canonical settings form. Settings live
in canonical tables (`pump_profiles`, `target_glucose_range`,
`insulin_config`, etc.); this snapshot is a *suggestion source* the
wizard uses to render an initial-fill state for the user to review.

The snapshot is **never** queried by AI, charts, mobile UI, or alerts
-- only the onboarding wizard touches it.

Re-fetch behavior: one latest snapshot per (user_id, connection_id);
new fetches upsert the existing row.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class NightscoutProfileSnapshot(Base):
    """A snapshot of one user's Nightscout-side profile data."""

    __tablename__ = "nightscout_profile_snapshots"

    __table_args__ = (
        # One latest snapshot per (user, connection). Re-fetch upserts.
        Index(
            "ix_nsps_user_connection",
            "user_id",
            "nightscout_connection_id",
            unique=True,
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

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # ---- Source metadata (from Nightscout's profile document) -----------

    source_default_profile_name: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    source_units: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_timezone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_dia_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_start_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ---- Time-segmented schedules (verbatim from Nightscout) -------------
    # Each is a list of {"time": "HH:MM", "value": <number>,
    # "timeAsSeconds": <int>}. Preserved as-emitted; the wizard
    # computes per-entry duration (NS profile entries are (time, value)
    # pairs; duration to next entry is implicit) and handles the
    # midnight-wrap edge case (first entry not at 00:00 means the last
    # entry's value carries back to midnight).

    basal_segments: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    carb_ratio_segments: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    sensitivity_segments: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    target_low_segments: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    target_high_segments: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )

    # ---- Raw blob ---------------------------------------------------------
    # Full profile document for re-parsing if the wizard needs fields we
    # didn't break out into typed columns (e.g., per-store metadata
    # for users with multiple Nightscout profiles).
    profile_json_full: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    # ---- Relationships ----------------------------------------------------

    user = relationship("User")
    connection = relationship("NightscoutConnection")

    def __repr__(self) -> str:
        return (
            f"<NightscoutProfileSnapshot(user_id={self.user_id}, "
            f"connection_id={self.nightscout_connection_id}, "
            f"profile={self.source_default_profile_name!r}, "
            f"fetched_at={self.fetched_at})>"
        )
