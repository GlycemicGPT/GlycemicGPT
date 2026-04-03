"""Bolus validation audit log model.

Every bolus validation request (approved or rejected) is logged for
audit trail and safety review.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin


class BolusValidationLog(Base, TimestampMixin):
    """Audit log for bolus validation requests."""

    __tablename__ = "bolus_validation_logs"

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

    requested_dose_milliunits: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    glucose_at_request_mgdl: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    user_confirmed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    approved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    validated_dose_milliunits: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    check_results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    rejection_reasons: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    request_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    user = relationship("User")
