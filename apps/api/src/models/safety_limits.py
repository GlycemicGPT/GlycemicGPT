"""Phase 3: Safety limits model.

Stores user-configured safety limits for data validation and (future) bolus
delivery enforcement. Values are synced to the mobile app and used by parsers
to reject implausible readings.
"""

import uuid

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin


class SafetyLimits(Base, TimestampMixin):
    """User-specific safety limits configuration.

    One-to-one with User. Stores glucose validity bounds and maximum
    insulin delivery rates used by the mobile app's data parsers.
    """

    __tablename__ = "safety_limits"

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
    )

    min_glucose_mgdl: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=20,
    )

    max_glucose_mgdl: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=500,
    )

    max_basal_rate_milliunits: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=15000,
    )

    max_bolus_dose_milliunits: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=25000,
    )

    user = relationship("User", back_populates="safety_limits")

    def __repr__(self) -> str:
        return (
            f"<SafetyLimits(user_id={self.user_id}, "
            f"glucose={self.min_glucose_mgdl}-{self.max_glucose_mgdl}, "
            f"basal_max={self.max_basal_rate_milliunits}, "
            f"bolus_max={self.max_bolus_dose_milliunits})>"
        )
