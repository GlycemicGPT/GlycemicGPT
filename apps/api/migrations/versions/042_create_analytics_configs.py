"""Create analytics_configs table.

Stores per-user analytics day boundary hour for aligning analytics
period start times (Insulin Summary, Recent Boluses) with pump resets.

Revision ID: 042_create_analytics_configs
Revises: 041_rename_pump_activity_mode
"""

import sqlalchemy as sa
from alembic import op

revision = "042_create_analytics_configs"
down_revision = "041_rename_pump_activity_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_configs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("day_boundary_hour", sa.Integer(), nullable=False, server_default="0"),
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
        sa.CheckConstraint(
            "day_boundary_hour >= 0 AND day_boundary_hour <= 23",
            name="ck_analytics_configs_boundary_hour_range",
        ),
    )


def downgrade() -> None:
    op.drop_table("analytics_configs")
