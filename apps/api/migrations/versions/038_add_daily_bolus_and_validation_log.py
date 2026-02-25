"""Add daily bolus limit column and bolus validation audit log table.

Revision ID: 038_daily_bolus_validation
Revises: 037_safety_limits
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "038_daily_bolus_validation"
down_revision = "037_safety_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add max_daily_bolus_milliunits to safety_limits
    op.add_column(
        "safety_limits",
        sa.Column(
            "max_daily_bolus_milliunits",
            sa.Integer(),
            nullable=False,
            server_default="100000",
        ),
    )
    op.create_check_constraint(
        "ck_safety_limits_daily_bolus_range",
        "safety_limits",
        "max_daily_bolus_milliunits >= 1 AND max_daily_bolus_milliunits <= 200000",
    )

    # Create bolus validation audit log table
    op.create_table(
        "bolus_validation_logs",
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
        sa.Column("requested_dose_milliunits", sa.Integer(), nullable=False),
        sa.Column("glucose_at_request_mgdl", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column(
            "user_confirmed", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column(
            "validated_dose_milliunits",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "check_results",
            postgresql.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "rejection_reasons",
            postgresql.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "request_timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
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
        # CHECK constraints -- placed after all column definitions
        sa.CheckConstraint(
            "requested_dose_milliunits >= 0 AND requested_dose_milliunits <= 25000",
            name="ck_bolus_log_dose_range",
        ),
        sa.CheckConstraint(
            "glucose_at_request_mgdl >= 20 AND glucose_at_request_mgdl <= 500",
            name="ck_bolus_log_glucose_range",
        ),
        sa.CheckConstraint(
            "validated_dose_milliunits >= 0 AND validated_dose_milliunits <= 25000",
            name="ck_bolus_log_validated_dose_range",
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'ai_suggested', 'automated')",
            name="ck_bolus_log_source_values",
        ),
    )
    # Alembic ignores index=True in op.create_table -- explicit create_index required.
    op.create_index(
        "ix_bolus_validation_logs_user_id",
        "bolus_validation_logs",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_bolus_validation_logs_user_id",
        table_name="bolus_validation_logs",
    )
    op.drop_table("bolus_validation_logs")
    op.drop_constraint("ck_safety_limits_daily_bolus_range", "safety_limits")
    op.drop_column("safety_limits", "max_daily_bolus_milliunits")
