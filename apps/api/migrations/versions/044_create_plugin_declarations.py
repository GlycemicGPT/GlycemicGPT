"""Create plugin_declarations table.

Stores per-user active pump plugin metadata and category mappings
so the backend/web can display plugin-aware category information
without requiring code changes for new pump plugins.

Revision ID: 044_create_plugin_declarations
Revises: 043_add_category_labels
"""

import sqlalchemy as sa
from alembic import op

revision = "044_create_plugin_declarations"
down_revision = "043_add_category_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plugin_declarations",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("plugin_id", sa.String(128), nullable=False),
        sa.Column("plugin_name", sa.String(64), nullable=False),
        sa.Column("plugin_version", sa.String(32), nullable=False),
        sa.Column(
            "declared_categories",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "category_mappings",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_plugin_declarations_user_id",
        "plugin_declarations",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_plugin_declarations_user_id")
    op.drop_table("plugin_declarations")
