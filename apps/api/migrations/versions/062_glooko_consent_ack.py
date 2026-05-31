"""Record Glooko connect-time consent acknowledgment.

Adds ``glooko_sync_state.consent_acknowledged_at`` -- the timestamp at which the
user explicitly acknowledged the unofficial Glooko connection when connecting.
It is stamped server-side at connect time (never a client value);
NULL means consent was never recorded. Kept on the state row (not a separate
audit table -- matching the Medtronic/Tandem "all per-integration state on one
row" convention), so disconnect (row delete) clears it and reconnecting
re-requires consent.

Revision ID: 062_glooko_consent_ack
Revises: 061_glooko_sync_state
Create Date: 2026-05-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "062_glooko_consent_ack"
down_revision: str | None = "061_glooko_sync_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "glooko_sync_state",
        sa.Column("consent_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("glooko_sync_state", "consent_acknowledged_at")
