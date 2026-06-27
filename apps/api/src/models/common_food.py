"""Common-food model: a user-named baseline for foods eaten often.

A ``common_food`` is the personalization seed of the meal-intelligence feature.
When a user corrects an estimate or saves a meal they eat regularly, they can
promote it to a named baseline so the platform remembers it instead of
re-guessing every time. ``food_records.common_food_id`` links a logged meal back
to the baseline it came from.

Safety posture (NON-NEGOTIABLE, inherited from food_records): a common food is a
descriptive baseline, never a dose. Carbs are stored as a low/high range, and
nothing in this model is ever read by IoB, treatment_safety, or carb-ratio math.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base
from src.vision.carb_contract import CARB_GRAMS_MAX, CARB_GRAMS_MIN


def normalize_common_food_name(name: str) -> str:
    """Return the dedupe key for a common-food name.

    Case-insensitive and whitespace-collapsed so "Oatmeal", " oatmeal " and
    "oatmeal  bowl" don't fragment into near-duplicate baselines. The user's
    original casing/spacing is preserved separately in ``name``.
    """
    return " ".join(name.strip().lower().split())


class CommonFood(Base):
    """A user-named carb/nutrition baseline for a frequently-eaten food.

    Deduped per user on ``normalized_name`` (a unique constraint) so promoting
    "the same" food twice updates one baseline rather than creating duplicates.
    """

    __tablename__ = "common_foods"

    __table_args__ = (
        # Dedupe: one baseline per (user, normalized name). Promotion of a
        # same-named food updates this row instead of fragmenting.
        UniqueConstraint(
            "user_id", "normalized_name", name="uq_common_foods_user_normalized_name"
        ),
        Index("ix_common_foods_user_name", "user_id", "normalized_name"),
        # Defense-in-depth carb bounds, mirroring food_records (reject-not-clamp
        # is enforced upstream; this stops any raw insert from storing an
        # out-of-range or inverted baseline).
        CheckConstraint(
            f"carbs_low >= {CARB_GRAMS_MIN:g} AND carbs_high <= {CARB_GRAMS_MAX:g} "
            "AND carbs_low <= carbs_high",
            name="ck_common_foods_carb_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # User-facing label, exactly as the user typed it.
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Dedupe key derived from ``name`` (see ``normalize_common_food_name``).
    normalized_name: Mapped[str] = mapped_column(String(120), nullable=False)

    # Baseline carbohydrate range (reject-not-clamp bounds, like food_records).
    carbs_low: Mapped[float] = mapped_column(Float, nullable=False)
    carbs_high: Mapped[float] = mapped_column(Float, nullable=False)
    nutrition_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

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
        return (
            f"<CommonFood(id={self.id}, user_id={self.user_id}, "
            f"name={self.name!r}, carbs={self.carbs_low}-{self.carbs_high}g)>"
        )
