"""Food record model for meal-photo carb estimation.

A ``food_record`` is a persistent, structured log of a photographed meal: the
AI's carbohydrate *range* estimate, a confidence signal, visible nutrition, and
the photo reference. It is net-new and deliberately distinct from
``pump_events.carbs_grams`` (pump-sourced delivery data) and ``meal_analyses``
(post-hoc carb-ratio pattern analysis).

Safety posture (NON-NEGOTIABLE): a food record is a descriptive observation,
never a dose. Carbs are stored as a low/high range plus confidence, never a
confident point integer, and nothing in this model is ever read by IoB,
treatment_safety, or carb-ratio math.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base
from src.vision.carb_contract import CARB_GRAMS_MAX, CARB_GRAMS_MIN


class FoodRecordSource(str, enum.Enum):
    """Provenance of a food record's carbohydrate values.

    Kept explicit so later changes can distinguish an untouched model estimate
    from a user-corrected one and from an externally-grounded one without a
    schema rewrite.
    """

    AI_ESTIMATE = "ai_estimate"  # Raw vision-model estimate (default).
    USER_CORRECTED = "user_corrected"  # User fixed the estimate.
    # Reserved. Grounding (Story 50.E1) is *attribution only* -- it records the
    # source in the grounding_* columns but never changes the persisted carb
    # values, so `source` correctly stays AI_ESTIMATE/USER_CORRECTED. This member
    # is kept for a hypothetical future where grounding overwrites the estimate.
    EXTERNAL_GROUNDED = "external_grounded"


class FoodRecord(Base):
    """A logged meal photo plus its structured carb/nutrition estimate.

    The AI estimate columns (``carbs_low`` / ``carbs_high`` / ``confidence`` /
    ``nutrition_json``) are the *original* model output and are never overwritten
    by a correction: the later correction flow writes the user's values into the
    separate ``corrected_*`` columns and flips ``source`` to ``USER_CORRECTED``,
    so the original estimate is always preserved for accuracy tracking and
    grounding.
    """

    __tablename__ = "food_records"

    __table_args__ = (
        Index("ix_food_records_user_meal_timestamp", "user_id", "meal_timestamp"),
        # Defense-in-depth bounds mirroring the reject-not-clamp validation in
        # `vision.carb_contract` so an ORM insert can never store an out-of-range
        # or inverted range. (See `schemas/safety_limits.py` for the convention.)
        CheckConstraint(
            f"carbs_low >= {CARB_GRAMS_MIN:g} AND carbs_high <= {CARB_GRAMS_MAX:g} "
            "AND carbs_low <= carbs_high",
            name="ck_food_records_carb_range",
        ),
        CheckConstraint(
            "(corrected_carbs_low IS NULL AND corrected_carbs_high IS NULL) OR "
            f"(corrected_carbs_low >= {CARB_GRAMS_MIN:g} "
            f"AND corrected_carbs_high <= {CARB_GRAMS_MAX:g} "
            "AND corrected_carbs_low <= corrected_carbs_high)",
            name="ck_food_records_corrected_carb_range",
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

    # --- Photo reference (mirrors user_documents; file lives on the uploads
    # volume, is owner-scoped, and is never web-served) ---
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)

    # When the meal was eaten / logged (defaults to upload time).
    meal_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # --- Original AI estimate (immutable once written) ---
    food_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    carbs_low: Mapped[float] = mapped_column(Float, nullable=False)
    carbs_high: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    nutrition_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    ai_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ai_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)

    source: Mapped[FoodRecordSource] = mapped_column(
        Enum(
            FoodRecordSource,
            name="foodrecordsource",
            create_type=False,
            values_callable=lambda e: [member.value for member in e],
        ),
        nullable=False,
        default=FoodRecordSource.AI_ESTIMATE,
        server_default=FoodRecordSource.AI_ESTIMATE.value,
    )

    # --- Correction seam (the correction flow populates these; the original
    # estimate above is preserved for transparency/eval) ---
    corrected_carbs_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    corrected_carbs_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    # User-corrected nutrition. Kept separate from ``nutrition_json`` (the AI
    # original) so a correction never discards the model's estimate.
    corrected_nutrition_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    corrected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Optional link to a saved common food (the personalization baseline this
    # record was promoted to / linked against). ON DELETE SET NULL so deleting a
    # common food unlinks its records rather than cascading their deletion.
    common_food_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("common_foods.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # --- Food-identity confirmation (Story 50.H2) ---
    # The AI-identified name lives in ``food_description`` (preserved, like the
    # original carb estimate). These record the user's confirmation/correction of
    # *what the food is*, kept separate from the carb correction (50.C1). External
    # authoritative grounding (USDA / OFF / restaurant) is applied ONLY when
    # ``identity_confirmed`` is True, so a misidentified label is never certified
    # with an authoritative citation. Never read by IoB / treatment_safety.
    confirmed_food_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    identity_confirmed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    # --- Grounding attribution (Story 50.E1) ---
    # Which source grounded this estimate, recorded for citation. Attribution
    # only: the carb values stay in ``carbs_low`` / ``carbs_high`` (vision) and
    # ``corrected_*`` (user truth). NULL = pure vision (ungrounded). These are
    # never read by IoB / treatment_safety / carb-ratio math.
    grounding_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    grounding_source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Trust-tier marker mirroring knowledge_chunks.trust_tier: USER_PROVIDED
    # (own history) / RESEARCHED / AUTHORITATIVE (published nutrition facts).
    grounding_trust_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # NOTE: the estimation pipeline (food_vision) attaches a transient, non-mapped
    # ``grounding`` attribute (a schemas.food_record.GroundingDetail) to a freshly
    # created instance so the create response can carry the grounded range + note +
    # disclaimer. It is never persisted -- only the flat grounding_* columns above
    # are -- and is absent on instances loaded from the DB.

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<FoodRecord(id={self.id}, user_id={self.user_id}, "
            f"carbs={self.carbs_low}-{self.carbs_high}g, source={self.source.value})>"
        )
