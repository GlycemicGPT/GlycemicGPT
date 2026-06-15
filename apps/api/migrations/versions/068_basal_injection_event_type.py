"""Add basal_injection pump event type (MDI long-acting injections).

Adds 'basal_injection' to the pumpeventtype enum so the Glooko mapper can record
MDI long-acting (basal) pen injections -- e.g. Lantus, Tresiba -- as a discrete
event. BASAL means a pump rate (U/h) and BOLUS would pollute rapid-acting IoB/TDD,
so neither fits a once-daily injection (issue #728). The new value is added here
but not used until runtime; the Postgres enum requires the value to be committed
before any row can reference it.

Revision ID: 068_basal_injection_event_type
Revises: 067_common_foods
"""

from alembic import op

revision = "068_basal_injection_event_type"
down_revision = "067_common_foods"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE must run outside a transaction in PostgreSQL
    op.execute("COMMIT")
    op.execute("ALTER TYPE pumpeventtype ADD VALUE IF NOT EXISTS 'basal_injection'")


def downgrade() -> None:
    # Cannot remove enum values in PostgreSQL without recreating the type
    pass
