"""Per-user Tandem cloud-sync (download) control state.

Adds ``tandem_sync_state`` -- a per-user single-row table holding the
toggle + cadence for the Tandem t:connect event sync. Only control fields
live here; sync freshness (``last_sync_at`` / ``last_error`` / ``status``)
remains on ``integration_credentials``, which ``sync_tandem_for_user``
already maintains.

Backward-compat note: a connected Tandem user with NO row is treated by
the scheduler as *enabled at the default interval* (matching the prior
global sync, which synced every connected user). The row exists only to
let a user change their interval or opt out -- so no data backfill is
needed and existing users keep syncing after this migration.

Matches the per-domain config pattern (``insulin_config``,
``data_retention_config``, ``forecast_settings``): one table per concern,
one-to-one with ``users`` via a UNIQUE on ``user_id``.

Revision ID: 059_tandem_sync_state
Revises: 058_drop_tandem_cloud_upload
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "059_tandem_sync_state"
down_revision: str | None = "058_drop_tandem_cloud_upload"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tandem_sync_state",
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
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "sync_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
        sa.Column(
            "events_pulled_total",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        # Last scheduled-sync ATTEMPT (success or failure). The scheduler
        # paces retries by this, not by the credential's success-only
        # last_sync_at, so a failing user is retried once per interval
        # rather than on every short tick.
        sa.Column(
            "last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        # Defensive: the API bounds the interval to [15, 1440], but a CHECK
        # keeps a manual SQL update from storing a value that would make the
        # scheduler either hammer upstream (0) or stall forever.
        sa.CheckConstraint(
            "sync_interval_minutes BETWEEN 15 AND 1440",
            name="ck_tandem_sync_state_interval_bounds",
        ),
    )
    # One-to-one with users; the upsert path in the settings endpoint relies
    # on this UNIQUE so racing inserts land cleanly via ON CONFLICT.
    op.create_index(
        "ix_tandem_sync_state_user_id",
        "tandem_sync_state",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_tandem_sync_state_user_id", table_name="tandem_sync_state")
    op.drop_table("tandem_sync_state")
