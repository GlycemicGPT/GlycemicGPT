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
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class PumpEventType(str, enum.Enum):
    """Types of pump events.

    Direct-integration values (basal, bolus, correction, suspend,
    resume, bg_reading, battery, reservoir) are written by direct
    pump drivers (Tandem). The remaining values are written by the
    Nightscout translator to cover events that flow in from
    cloud-mediated integrations (carbs, overrides, profile switches,
    combo boluses, temp targets, notes, device events, APS-offline
    markers); type-specific extras that don't fit the column schema
    land in `metadata_json`.
    """

    BASAL = "basal"  # Basal insulin delivery
    BOLUS = "bolus"  # Manual bolus
    CORRECTION = "correction"  # Control-IQ automated correction
    SUSPEND = "suspend"  # Insulin delivery suspended
    RESUME = "resume"  # Insulin delivery resumed
    BG_READING = "bg_reading"  # CGM reading from pump (has IoB)
    BATTERY = "battery"  # Battery percentage from pump
    RESERVOIR = "reservoir"  # Reservoir insulin units remaining
    # --- Cloud-mediated event types (Nightscout translator) ---
    CARBS = "carbs"  # Carb-only entry (no insulin)
    OVERRIDE = "override"  # Loop/AAPS Temporary Override or Trio Exercise toggle
    PROFILE_SWITCH = "profile_switch"  # Profile change (real or AAPS EPS-as-Note)
    COMBO_BOLUS = "combo_bolus"  # Combo Bolus or AAPS extendedEmulated TBR
    TEMP_TARGET = "temp_target"  # Temporary Target adjustment
    NOTE = "note"  # Free-text note / Announcement
    DEVICE_EVENT = "device_event"  # Site/Sensor/Insulin/Battery change
    APS_OFFLINE = "aps_offline"  # OpenAPS Offline / loop-down marker


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

    # Type-specific extras that don't fit the typed columns above.
    # Examples: override correctionRange / multiplier / remoteAddress;
    # profile-switch tuple (originalProfileName, percentage, timeshift,
    # duration, profileJson); AAPS pump composite dedup triple
    # (pumpId, pumpType, pumpSerial); Loop syncIdentifier; xDrip+ uuid.
    # Nullable -- direct integrations leave this blank.
    metadata_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    # Links the bolus + carb_entry rows produced when an upstream
    # meal-bolus pair (carbs + insulin in one record) is split into
    # two internal events. Both rows share the same meal_event_id so
    # downstream consumers can correlate them. NULL for non-paired
    # events.
    meal_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    # Nightscout-server-assigned `_id` (or client-generated
    # `identifier` / `syncIdentifier`). Used as the per-connection
    # dedupe key when re-fetching the same record across sync cycles.
    # NULL for direct-integration events; the partial unique index
    # `ix_pump_events_source_nsid` on (source, ns_id) WHERE ns_id IS
    # NOT NULL handles the dedupe.
    ns_id: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Relationship to user
    user = relationship("User", back_populates="pump_events")

    def __repr__(self) -> str:
        return (
            f"<PumpEvent(user_id={self.user_id}, type={self.event_type.value}, "
            f"units={self.units}, automated={self.is_automated}, "
            f"timestamp={self.event_timestamp})>"
        )
