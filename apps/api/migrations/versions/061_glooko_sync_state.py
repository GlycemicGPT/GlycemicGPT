"""Per-user Glooko (Omnipod Cloud Sync) autonomous-sync state.

Adds ``glooko_sync_state`` -- a per-user single-row table for the autonomous
Glooko follower sync (Tandem/Medtronic parity). Self-contained: like Medtronic
(and unlike Tandem) there is no pre-existing Glooko ``integration_credentials``
row, so this table holds both the encrypted credentials (Glooko email + password,
replayed via the web Devise login each sync) AND the control + freshness fields.

Two columns differ from the Medtronic sibling, driven by the Glooko protocol:
``stream_cursors`` (JSONB) tracks the per-``/api/v2/*``-stream keyset cursor
(they advance independently), and ``last_cgm_window_end`` tracks the date-windowed
``/api/v3/graph`` CGM path. One-to-one with ``users`` via a UNIQUE on ``user_id``.

Absence of a row means "not connected" -- the user must complete the one-time
connect first; the scheduler skips users without a row.

Revision ID: 061_glooko_sync_state
Revises: 060_medtronic_connect_state
Create Date: 2026-05-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "061_glooko_sync_state"
down_revision: str | None = "060_medtronic_connect_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "glooko_sync_state",
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
            "region",
            sa.String(length=10),
            nullable=False,
            server_default="US",
        ),
        # Fernet-encrypted Glooko email + password. NOT rotated (unlike the
        # Medtronic refresh token): the web session cookie is ephemeral and
        # re-minted from these on each sync / 401.
        sa.Column("encrypted_email", sa.Text(), nullable=False),
        sa.Column("encrypted_password", sa.Text(), nullable=False),
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
            server_default="30",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        # Last scheduled-sync ATTEMPT (success or failure); the scheduler paces
        # by this, not by the success-only last_sync_at.
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "readings_synced_total",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        # Patient identifiers discovered at login (glookoCode slug + Mongo OID).
        sa.Column("patient_slug", sa.String(length=64), nullable=True),
        sa.Column("patient_oid", sa.String(length=24), nullable=True),
        # Per-stream keyset cursor for the /api/v2/* pump streams:
        # {<stream>: {"last_updated_at": <iso>, "last_guid": <uuid>}}.
        sa.Column("stream_cursors", postgresql.JSONB(), nullable=True),
        # High-water mark for the date-windowed CGM (/api/v3/graph) path.
        sa.Column("last_cgm_window_end", sa.DateTime(timezone=True), nullable=True),
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
        # keeps a manual SQL update from making the scheduler hammer upstream
        # (0) or stall forever.
        sa.CheckConstraint(
            "sync_interval_minutes BETWEEN 15 AND 1440",
            name="ck_glooko_sync_state_interval_bounds",
        ),
    )
    op.create_index(
        "ix_glooko_sync_state_user_id",
        "glooko_sync_state",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_glooko_sync_state_user_id",
        table_name="glooko_sync_state",
    )
    op.drop_table("glooko_sync_state")
