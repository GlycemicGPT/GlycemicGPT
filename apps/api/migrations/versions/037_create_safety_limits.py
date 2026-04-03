"""Create safety_limits table.

Stores per-user safety limits for data validation and (future) bolus
delivery enforcement. Synced to mobile app.

Revision ID: 037_safety_limits
Revises: 036_battery_reservoir
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "037_safety_limits"
down_revision = "036_battery_reservoir"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safety_limits",
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
            unique=True,
        ),
        sa.Column(
            "min_glucose_mgdl",
            sa.Integer(),
            nullable=False,
            server_default="20",
        ),
        sa.Column(
            "max_glucose_mgdl",
            sa.Integer(),
            nullable=False,
            server_default="500",
        ),
        sa.Column(
            "max_basal_rate_milliunits",
            sa.Integer(),
            nullable=False,
            server_default="15000",
        ),
        sa.Column(
            "max_bolus_dose_milliunits",
            sa.Integer(),
            nullable=False,
            server_default="25000",
        ),
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
    # Database-level CHECK constraints as defense-in-depth.
    # These match the absolute hardware bounds enforced by SafetyLimits.safeOf().
    op.create_check_constraint(
        "ck_safety_limits_min_glucose_range",
        "safety_limits",
        "min_glucose_mgdl >= 20 AND min_glucose_mgdl <= 500",
    )
    op.create_check_constraint(
        "ck_safety_limits_max_glucose_range",
        "safety_limits",
        "max_glucose_mgdl >= 20 AND max_glucose_mgdl <= 500",
    )
    op.create_check_constraint(
        "ck_safety_limits_glucose_ordering",
        "safety_limits",
        "min_glucose_mgdl < max_glucose_mgdl",
    )
    op.create_check_constraint(
        "ck_safety_limits_basal_range",
        "safety_limits",
        "max_basal_rate_milliunits >= 1 AND max_basal_rate_milliunits <= 15000",
    )
    op.create_check_constraint(
        "ck_safety_limits_bolus_range",
        "safety_limits",
        "max_bolus_dose_milliunits >= 1 AND max_bolus_dose_milliunits <= 25000",
    )


def downgrade() -> None:
    op.drop_constraint("ck_safety_limits_bolus_range", "safety_limits")
    op.drop_constraint("ck_safety_limits_basal_range", "safety_limits")
    op.drop_constraint("ck_safety_limits_glucose_ordering", "safety_limits")
    op.drop_constraint("ck_safety_limits_max_glucose_range", "safety_limits")
    op.drop_constraint("ck_safety_limits_min_glucose_range", "safety_limits")
    op.drop_table("safety_limits")
