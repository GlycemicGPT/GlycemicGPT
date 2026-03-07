"""Add custom_categories column to analytics_configs.

Schema-ready column for future user-defined bolus categories.
No web UI in this story -- just the database and schema support.

Revision ID: 045_add_custom_categories
Revises: 044_create_plugin_declarations
"""

import sqlalchemy as sa
from alembic import op

revision = "045_add_custom_categories"
down_revision = "044_create_plugin_declarations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analytics_configs",
        sa.Column(
            "custom_categories",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("analytics_configs", "custom_categories")
