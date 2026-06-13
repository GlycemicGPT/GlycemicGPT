"""Add glooko_sync_state.cgm_sync_enabled (doses-only toggle).

Per-connection switch to skip Glooko CGM ingestion (issue #727) so a user with a
direct CGM source can run Glooko as a doses-only integration. Server default true
preserves current behavior for existing connections.

Revision ID: 065_glooko_cgm_sync_enabled
Revises: 064_cgm_role
Create Date: 2026-06-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "065_glooko_cgm_sync_enabled"
down_revision: str | None = "064_cgm_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "glooko_sync_state",
        sa.Column(
            "cgm_sync_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("glooko_sync_state", "cgm_sync_enabled")
