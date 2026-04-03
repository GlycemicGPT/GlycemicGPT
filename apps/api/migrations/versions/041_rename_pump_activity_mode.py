"""Rename control_iq_mode -> pump_activity_mode and migrate 'standard' -> 'none'.

Pump activity modes (sleep/exercise) are pump-level features independent of
Control-IQ automation. This migration corrects the column name and replaces
the misleading 'standard' value with 'none' (no special mode active).

Revision ID: 041_rename_pump_activity_mode
Revises: 040_build_type_check
"""

from alembic import op

revision = "041_rename_pump_activity_mode"
down_revision = "040_build_type_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "pump_events", "control_iq_mode", new_column_name="pump_activity_mode"
    )
    op.execute(
        "UPDATE pump_events SET pump_activity_mode = 'none' "
        "WHERE pump_activity_mode = 'standard'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE pump_events SET pump_activity_mode = 'standard' "
        "WHERE pump_activity_mode = 'none'"
    )
    op.alter_column(
        "pump_events", "pump_activity_mode", new_column_name="control_iq_mode"
    )
