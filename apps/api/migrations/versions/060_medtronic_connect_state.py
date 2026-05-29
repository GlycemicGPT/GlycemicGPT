"""Per-user Medtronic CareLink CarePartner (Connect) autonomous-sync state.

Adds ``medtronic_connect_state`` -- a per-user single-row table for the
autonomous Medtronic follower sync (Tandem parity). Self-contained: unlike
Tandem there is no pre-existing Medtronic ``integration_credentials`` row, so
this table holds both the encrypted Auth0 refresh token + CareLink username +
region (to mint access tokens and call display/message) AND the control +
freshness fields. One-to-one with ``users`` via a UNIQUE on ``user_id``.

Absence of a row means "not connected" -- the user must complete the one-time
CarePartner login first; the scheduler skips users without a row.

Revision ID: 060_medtronic_connect_state
Revises: 059_tandem_sync_state
Create Date: 2026-05-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "060_medtronic_connect_state"
down_revision: str | None = "059_tandem_sync_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "medtronic_connect_state",
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
        # Fernet-encrypted CareLink username + Auth0 refresh token. The refresh
        # token rotates on each refresh grant (the row is updated in place).
        sa.Column("encrypted_username", sa.Text(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default="patient",
        ),
        sa.Column("encrypted_patient_id", sa.Text(), nullable=True),
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
            name="ck_medtronic_connect_state_interval_bounds",
        ),
    )
    op.create_index(
        "ix_medtronic_connect_state_user_id",
        "medtronic_connect_state",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_medtronic_connect_state_user_id",
        table_name="medtronic_connect_state",
    )
    op.drop_table("medtronic_connect_state")
