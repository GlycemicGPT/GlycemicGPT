"""Add the portion/assumptions column to food_records (Story 50.N1).

The vision contract always asked the model for its portion-size / preparation
``assumptions``, but the parser dropped them and no column held them -- so the
*assumed portion*, which is the dominant error source in photo carb estimation,
was in no API response. This adds the column so the assumed portion can be
surfaced as the estimate's primary sanity-check.

One nullable TEXT column, mirroring ``food_description``: NULL for every existing
row (no backfill needed) and for any estimate where the model stated no
assumption. The value is dosing-scrubbed and length-capped before it is written
(``services.food_vision``). Descriptive only -- never read by IoB /
treatment_safety / carb-ratio math.

Revision ID: 073_food_record_assumptions
Revises: 072_add_user_disclaimer_version
Create Date: 2026-06-19
"""

import sqlalchemy as sa
from alembic import op

revision = "073_food_record_assumptions"
down_revision = "072_add_user_disclaimer_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "food_records",
        sa.Column("assumptions", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("food_records", "assumptions")
