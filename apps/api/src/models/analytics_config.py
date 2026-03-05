"""Analytics configuration model.

Stores user-configured analytics day boundary hour for aligning
analytics periods (Insulin Summary, Recent Boluses) with pump
Delivery Summary reset times.
"""

import uuid

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin


class AnalyticsConfig(Base, TimestampMixin):
    """User-specific analytics configuration.

    One-to-one with User. Stores the day boundary hour used to align
    analytics period start times with pump delivery summary resets.
    """

    __tablename__ = "analytics_configs"

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

    day_boundary_hour: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    user = relationship("User", back_populates="analytics_config")

    def __repr__(self) -> str:
        return (
            f"<AnalyticsConfig(user_id={self.user_id}, "
            f"day_boundary_hour={self.day_boundary_hour})>"
        )
