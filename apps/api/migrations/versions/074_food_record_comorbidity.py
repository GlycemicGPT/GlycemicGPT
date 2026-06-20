"""Add the grounding-backed comorbidity nutrition column to food_records.

Saturated fat, sugars/added sugars, and sodium aren't reliably estimable from a
plated-food photo and their value is comorbidity (blood-pressure / cardiovascular)
awareness, so they are grounding-only: populated from an authoritative published
source (USDA / Open Food Facts / restaurant) ONLY after identity confirmation,
never asserted from the photo. This stores those grounded values in their own
JSONB column, kept deliberately separate from the AI's ``nutrition_json`` (the
photo-estimated macros) so a photo can never assert a comorbidity value.

One nullable JSONB column: NULL for every existing row (no backfill needed) and
for any record that has no grounded comorbidity data. Descriptive comorbidity
awareness only -- never read by IoB / treatment_safety / carb-ratio math.

Revision ID: 074_food_record_comorbidity
Revises: 073_food_record_assumptions
Create Date: 2026-06-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "074_food_record_comorbidity"
down_revision = "073_food_record_assumptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "food_records",
        sa.Column("grounding_nutrition_json", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("food_records", "grounding_nutrition_json")
