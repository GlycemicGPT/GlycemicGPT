"""Add category_labels column to analytics_configs.

Stores user-customizable display labels for bolus categories as JSONB.
Keys are BolusCategory enum names, values are display strings (max 20 chars).

Revision ID: 043_add_category_labels
Revises: 042_create_analytics_configs
"""

import sqlalchemy as sa
from alembic import op

revision = "043_add_category_labels"
down_revision = "042_create_analytics_configs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analytics_configs",
        sa.Column(
            "category_labels",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("analytics_configs", "category_labels")
