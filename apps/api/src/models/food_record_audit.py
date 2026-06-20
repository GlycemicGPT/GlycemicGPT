"""Audit & provenance trail for a meal-photo estimate (Story 50.H3).

Traditional healthcare ML is auditable because it is deterministic; an LLM is
not, but the *pipeline* around it can still be made answerable. This stores, per
food record, what the model actually returned and how the estimate resolved, so
"why did it say this" has an answer after the fact:

  * the raw per-sample vision outputs from the multi-sample run (50.H1) -- each
    sample's carb range, identified food, and the model's own self-reported
    confidence (retained as INTERNAL-only audit/eval data, never surfaced as a
    user-facing safety signal),
  * the empirical dispersion summary that produced the shown confidence, and
  * the precedence decision -- which grounding source won (or vision-only) and
    the identity it was keyed on (50.H2).

Owner-scoped and 1:1 with a ``food_records`` row. ``ON DELETE CASCADE`` on both
the food record and the user means deleting either drops the audit trail with no
extra code (AC5: deleting a record deletes its audit; retention/purge of records
cascades here). No raw image bytes are duplicated -- the photo reference stays on
the food record. Nothing here is read by IoB / treatment_safety / carb-ratio
math; this is descriptive provenance only.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class FoodRecordAudit(Base):
    """The provenance trail for one food record's estimate (1:1, owner-scoped)."""

    __tablename__ = "food_record_audits"

    __table_args__ = (
        # 1:1 with the food record (the unique constraint also serves lookups).
        UniqueConstraint("food_record_id", name="uq_food_record_audits_food_record_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )

    # 1:1 with the food record. CASCADE so deleting the record (single delete or
    # retention purge) drops the audit row automatically.
    food_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("food_records.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Denormalized owner for direct owner-scoped retrieval (IDOR defence) and so a
    # user deletion cascades here independently of the food-record path.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Lean raw per-sample outputs (50.H1): a list of
    # {carbs_low, carbs_high, identity, self_reported_confidence, parse_ok}.
    # self_reported_confidence is INTERNAL-only -- kept for eval/Sentry triage,
    # not exposed as a user-facing safety signal.
    samples_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # The empirical dispersion summary that produced the shown confidence band
    # (cv, samples requested/used, identity agreement, wide-spread).
    dispersion_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # The precedence decision: which source won (or vision-only), its trust tier,
    # the identity it was keyed on, and whether identity was confirmed.
    precedence_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<FoodRecordAudit(id={self.id}, food_record_id={self.food_record_id})>"
