"""Story 3.4 & 3.5: Pump event model.

Models for storing pump data from Tandem t:connect with pump activity tracking.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class PumpEventType(str, enum.Enum):
    """Types of pump events from Tandem t:connect."""

    BASAL = "basal"  # Basal insulin delivery
    BOLUS = "bolus"  # Manual bolus
    CORRECTION = "correction"  # Control-IQ automated correction
    SUSPEND = "suspend"  # Insulin delivery suspended
    RESUME = "resume"  # Insulin delivery resumed
    BG_READING = "bg_reading"  # CGM reading from pump (has IoB)
    BATTERY = "battery"  # Battery percentage from pump
    RESERVOIR = "reservoir"  # Reservoir insulin units remaining


class PumpActivityMode(str, enum.Enum):
    """Pump activity modes -- pump-level feature, independent of automation.

    Sleep and Exercise are pump activity modes that adjust target ranges
    and basal profiles. They exist on all Tandem pumps regardless of
    whether Control-IQ is enabled. NONE means normal operation.
    """

    NONE = "none"
    SLEEP = "sleep"
    EXERCISE = "exercise"


# Backwards-compat alias -- remove once all consumers migrate
ControlIQMode = PumpActivityMode


class PumpEvent(Base):
    """Stores pump events from Tandem t:connect.

    Each event represents an insulin delivery action including basal rates,
    boluses, and Control-IQ automated corrections.
    """

    __tablename__ = "pump_events"

    __table_args__ = (
        # Index for querying recent events for a user
        Index("ix_pump_events_user_timestamp", "user_id", "event_timestamp"),
        # Unique constraint to prevent duplicate events
        Index(
            "ix_pump_events_user_event_unique",
            "user_id",
            "event_timestamp",
            "event_type",
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
        index=True,
    )

    event_type: Mapped[PumpEventType] = mapped_column(
        Enum(
            PumpEventType,
            name="pumpeventtype",
            create_type=False,
            values_callable=lambda e: [member.value for member in e],
        ),
        nullable=False,
    )

    event_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Insulin data
    units: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    duration_minutes: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # Control-IQ flags
    is_automated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    control_iq_reason: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # Pump activity mode active during event (sleep/exercise/none)
    pump_activity_mode: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    # For basal adjustments: percentage change from profile rate
    # Positive = increase, Negative = decrease (Story 3.5)
    basal_adjustment_pct: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    # Context at time of event
    iob_at_event: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    cob_at_event: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    bg_at_event: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # When we received/stored this event
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Source integration
    source: Mapped[str] = mapped_column(
        String(50),
        default="tandem",
        nullable=False,
    )

    # Relationship to user
    user = relationship("User", back_populates="pump_events")

    def __repr__(self) -> str:
        return (
            f"<PumpEvent(user_id={self.user_id}, type={self.event_type.value}, "
            f"units={self.units}, automated={self.is_automated}, "
            f"timestamp={self.event_timestamp})>"
        )
