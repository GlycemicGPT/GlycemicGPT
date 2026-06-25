"""Create food_records table for meal-photo carb estimation.

Net-new first-class table for photographed-meal carb estimates: a low/high carb
range, a confidence signal, visible nutrition, provenance, and the photo
reference. Distinct from pump_events.carbs_grams and meal_analyses.

Carb values carry DB-level CHECK constraints mirroring the reject-not-clamp
bounds in src.vision.carb_contract (defense-in-depth, matching safety_limits).

Revision ID: 066_food_records
Revises: 065_glooko_cgm_sync_enabled
Create Date: 2026-06-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "066_food_records"
down_revision = "065_glooko_cgm_sync_enabled"
branch_labels = None
depends_on = None

# Keep in sync with src.vision.carb_contract.CARB_GRAMS_MIN / CARB_GRAMS_MAX.
CARB_GRAMS_MIN = 0
CARB_GRAMS_MAX = 1000


def upgrade() -> None:
    conn = op.get_bind()

    # Create the provenance enum idempotently (a re-run / shared dev DB may
    # already carry it), matching the pattern used by the pump-event enum.
    result = conn.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = 'foodrecordsource'")
    )
    if not result.fetchone():
        food_record_source = postgresql.ENUM(
            "ai_estimate",
            "user_corrected",
            "external_grounded",
            name="foodrecordsource",
        )
        food_record_source.create(conn)

    op.create_table(
        "food_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Photo reference (mirrors user_documents).
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=20), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column(
            "meal_timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Original AI estimate (immutable once written).
        sa.Column("food_description", sa.Text(), nullable=True),
        sa.Column("carbs_low", sa.Float(), nullable=False),
        sa.Column("carbs_high", sa.Float(), nullable=False),
        sa.Column("confidence", sa.String(length=10), nullable=True),
        sa.Column("nutrition_json", postgresql.JSONB(), nullable=True),
        sa.Column("ai_model", sa.String(length=100), nullable=True),
        sa.Column("ai_provider", sa.String(length=50), nullable=True),
        sa.Column(
            "source",
            postgresql.ENUM(
                "ai_estimate",
                "user_corrected",
                "external_grounded",
                name="foodrecordsource",
                create_type=False,
            ),
            nullable=False,
            server_default="ai_estimate",
        ),
        # Correction seam (populated by the later correction flow); original
        # estimate above is preserved.
        sa.Column("corrected_carbs_low", sa.Float(), nullable=True),
        sa.Column("corrected_carbs_high", sa.Float(), nullable=True),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True),
        # Optional common-food link. A later change creates common_foods and
        # adds the FK; stored now as a plain nullable UUID so the seam exists.
        sa.Column("common_food_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_food_records_user_id",
        "food_records",
        ["user_id"],
    )
    op.create_index(
        "ix_food_records_user_meal_timestamp",
        "food_records",
        ["user_id", "meal_timestamp"],
    )

    # Defense-in-depth carb bounds (reject-not-clamp enforced upstream in the
    # estimation service; these stop any ORM/raw insert from storing an
    # out-of-range or inverted range).
    op.create_check_constraint(
        "ck_food_records_carb_range",
        "food_records",
        f"carbs_low >= {CARB_GRAMS_MIN} AND carbs_high <= {CARB_GRAMS_MAX} "
        "AND carbs_low <= carbs_high",
    )
    op.create_check_constraint(
        "ck_food_records_corrected_carb_range",
        "food_records",
        "(corrected_carbs_low IS NULL AND corrected_carbs_high IS NULL) OR "
        f"(corrected_carbs_low >= {CARB_GRAMS_MIN} "
        f"AND corrected_carbs_high <= {CARB_GRAMS_MAX} "
        "AND corrected_carbs_low <= corrected_carbs_high)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_food_records_corrected_carb_range", "food_records")
    op.drop_constraint("ck_food_records_carb_range", "food_records")
    op.drop_index("ix_food_records_user_meal_timestamp", table_name="food_records")
    op.drop_index("ix_food_records_user_id", table_name="food_records")
    op.drop_table("food_records")
    sa.Enum(name="foodrecordsource").drop(op.get_bind(), checkfirst=True)
