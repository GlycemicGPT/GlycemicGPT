"""Create common_foods table + wire food_records correction/link seams.

Meal-intelligence correction loop + common foods. Adds:
  * ``common_foods`` -- a user-named carb/nutrition baseline for frequently-eaten
    foods, deduped per user on a normalized name.
  * the FK from ``food_records.common_food_id`` to ``common_foods.id``
    (ON DELETE SET NULL, so deleting a baseline unlinks its records).
  * ``food_records.corrected_nutrition_json`` -- the user-corrected-nutrition
    seam, kept separate from the immutable AI ``nutrition_json``.

Carb values carry DB-level CHECK constraints mirroring the reject-not-clamp
bounds in src.vision.carb_contract (defense-in-depth, matching food_records).

Revision ID: 067_common_foods
Revises: 066_food_records
Create Date: 2026-06-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "067_common_foods"
down_revision = "066_food_records"
branch_labels = None
depends_on = None

# Keep in sync with src.vision.carb_contract.CARB_GRAMS_MIN / CARB_GRAMS_MAX.
CARB_GRAMS_MIN = 0
CARB_GRAMS_MAX = 1000


def upgrade() -> None:
    op.create_table(
        "common_foods",
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
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalized_name", sa.String(length=120), nullable=False),
        sa.Column("carbs_low", sa.Float(), nullable=False),
        sa.Column("carbs_high", sa.Float(), nullable=False),
        sa.Column("nutrition_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_common_foods_user_id", "common_foods", ["user_id"])
    op.create_index(
        "ix_common_foods_user_name", "common_foods", ["user_id", "normalized_name"]
    )
    # Dedupe: one baseline per (user, normalized name).
    op.create_unique_constraint(
        "uq_common_foods_user_normalized_name",
        "common_foods",
        ["user_id", "normalized_name"],
    )
    # Defense-in-depth carb bounds (reject-not-clamp enforced upstream).
    op.create_check_constraint(
        "ck_common_foods_carb_range",
        "common_foods",
        f"carbs_low >= {CARB_GRAMS_MIN} AND carbs_high <= {CARB_GRAMS_MAX} "
        "AND carbs_low <= carbs_high",
    )

    # User-corrected nutrition seam on food_records (the AI ``nutrition_json``
    # stays immutable; corrections land here).
    op.add_column(
        "food_records",
        sa.Column("corrected_nutrition_json", postgresql.JSONB(), nullable=True),
    )

    # Promote the food_records.common_food_id seam (a plain nullable UUID since
    # migration 066) to a real FK now that common_foods exists.
    op.create_index(
        "ix_food_records_common_food_id", "food_records", ["common_food_id"]
    )
    op.create_foreign_key(
        "fk_food_records_common_food_id",
        "food_records",
        "common_foods",
        ["common_food_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_food_records_common_food_id", "food_records", type_="foreignkey"
    )
    op.drop_index("ix_food_records_common_food_id", table_name="food_records")
    op.drop_column("food_records", "corrected_nutrition_json")

    op.drop_constraint("ck_common_foods_carb_range", "common_foods")
    op.drop_constraint("uq_common_foods_user_normalized_name", "common_foods")
    op.drop_index("ix_common_foods_user_name", table_name="common_foods")
    op.drop_index("ix_common_foods_user_id", table_name="common_foods")
    op.drop_table("common_foods")
