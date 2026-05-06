"""Story 3.2: Glucose reading model.

Models for storing CGM glucose readings from Dexcom.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class TrendDirection(str, enum.Enum):
    """Glucose trend direction from CGM."""

    DOUBLE_UP = "double_up"  # Rising fast (>3 mg/dL/min)
    SINGLE_UP = "single_up"  # Rising (1-3 mg/dL/min)
    FORTY_FIVE_UP = "forty_five_up"  # Rising slowly
    FLAT = "flat"  # Stable (-1 to +1 mg/dL/min)
    FORTY_FIVE_DOWN = "forty_five_down"  # Falling slowly
    SINGLE_DOWN = "single_down"  # Falling (-1 to -3 mg/dL/min)
    DOUBLE_DOWN = "double_down"  # Falling fast (<-3 mg/dL/min)
    NOT_COMPUTABLE = "not_computable"  # Unable to determine
    RATE_OUT_OF_RANGE = "rate_out_of_range"  # Rate outside normal range


# Map pydexcom trend values to our enum
PYDEXCOM_TREND_MAP = {
    "doubleUp": TrendDirection.DOUBLE_UP,
    "singleUp": TrendDirection.SINGLE_UP,
    "fortyFiveUp": TrendDirection.FORTY_FIVE_UP,
    "flat": TrendDirection.FLAT,
    "fortyFiveDown": TrendDirection.FORTY_FIVE_DOWN,
    "singleDown": TrendDirection.SINGLE_DOWN,
    "doubleDown": TrendDirection.DOUBLE_DOWN,
    "notComputable": TrendDirection.NOT_COMPUTABLE,
    "rateOutOfRange": TrendDirection.RATE_OUT_OF_RANGE,
    # Also handle numeric trends from pydexcom
    1: TrendDirection.DOUBLE_UP,
    2: TrendDirection.SINGLE_UP,
    3: TrendDirection.FORTY_FIVE_UP,
    4: TrendDirection.FLAT,
    5: TrendDirection.FORTY_FIVE_DOWN,
    6: TrendDirection.SINGLE_DOWN,
    7: TrendDirection.DOUBLE_DOWN,
    8: TrendDirection.NOT_COMPUTABLE,
    9: TrendDirection.RATE_OUT_OF_RANGE,
}


class GlucoseReading(Base):
    """Stores glucose readings from CGM devices.

    Each reading includes the glucose value, timestamp from the CGM,
    and trend direction. Readings are linked to a user.
    """

    __tablename__ = "glucose_readings"

    __table_args__ = (
        # Index for querying recent readings for a user
        Index("ix_glucose_readings_user_timestamp", "user_id", "reading_timestamp"),
        # Index for finding duplicates
        Index(
            "ix_glucose_readings_user_reading",
            "user_id",
            "reading_timestamp",
            unique=True,
        ),
        # Per-source partial unique index for Nightscout-relayed
        # readings; mirrors the migration's
        # `ix_glucose_readings_source_nsid` so SQLAlchemy is aware of
        # it. Only fires when ns_id IS NOT NULL -- direct-integration
        # rows (Dexcom, etc.) leave ns_id NULL and use the natural-key
        # dedupe via the `(user_id, reading_timestamp)` index above.
        Index(
            "ix_glucose_readings_source_nsid",
            "source",
            "ns_id",
            unique=True,
            postgresql_where=text("ns_id IS NOT NULL"),
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

    # Glucose value in mg/dL
    value: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Timestamp from the CGM device (when the reading was taken)
    reading_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Trend direction
    trend: Mapped[TrendDirection] = mapped_column(
        Enum(
            TrendDirection,
            name="trenddirection",
            create_type=False,
            values_callable=lambda e: [member.value for member in e],
        ),
        nullable=False,
    )

    # Rate of change in mg/dL/min (if available)
    trend_rate: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    # When we received/stored this reading
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Source device/integration
    source: Mapped[str] = mapped_column(
        default="dexcom",
        nullable=False,
    )

    # Nightscout-server-assigned `_id` (or client-generated
    # `identifier`). Used as the per-connection dedupe key when
    # re-fetching the same record across sync cycles. NULL for
    # direct-integration readings (Dexcom, etc.); the partial unique
    # index `ix_glucose_readings_source_nsid` on (source, ns_id)
    # WHERE ns_id IS NOT NULL handles the dedupe.
    ns_id: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Relationship to user
    user = relationship("User", back_populates="glucose_readings")

    def __repr__(self) -> str:
        return f"<GlucoseReading(user_id={self.user_id}, value={self.value}, trend={self.trend.value}, timestamp={self.reading_timestamp})>"
