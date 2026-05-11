"""Story 43.1: Create nightscout_connections table.

Per-user Nightscout / Nocturne instance configuration. Multiple per
user permitted; soft-delete via is_active=false rather than hard delete
so historical per-source attribution survives.

Revision ID: 051_nightscout_connections
Revises: 050_knowledge_chunk_unique_hash
Create Date: 2026-05-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "051_nightscout_connections"
down_revision = "050_knowledge_chunk_unique_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nightscout_connections",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column(
            "auth_type",
            sa.Enum(
                "secret",
                "token",
                "auto",
                name="nightscoutauthtype",
                create_type=True,
            ),
            nullable=False,
            server_default="auto",
        ),
        sa.Column("encrypted_credential", sa.Text(), nullable=False),
        sa.Column(
            "api_version",
            sa.Enum(
                "v1",
                "v3",
                "auto",
                name="nightscoutapiversion",
                create_type=True,
            ),
            nullable=False,
            server_default="auto",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "sync_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
        sa.Column(
            "initial_sync_window_days",
            sa.Integer(),
            nullable=False,
            server_default="7",
        ),
        sa.Column(
            "last_sync_status",
            sa.Enum(
                "never",
                "ok",
                "error",
                "auth_failed",
                "rate_limited",
                "network",
                "unreachable",
                name="nightscoutsyncstatus",
                create_type=True,
            ),
            nullable=False,
            server_default="never",
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column(
            "detected_uploaders_json",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
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

    # Composite index for the scheduler's per-user-active lookup
    # (Story 43.4 will run "WHERE user_id = ? AND is_active = true").
    op.create_index(
        "ix_nightscout_connections_user_active",
        "nightscout_connections",
        ["user_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_nightscout_connections_user_active",
        table_name="nightscout_connections",
    )
    op.drop_table("nightscout_connections")
    # Drop the enum types last; they were created with the table.
    # Use postgresql.ENUM (not sa.Enum) to ensure the dialect-specific
    # DROP TYPE statement is emitted regardless of Alembic version.
    postgresql.ENUM(name="nightscoutsyncstatus").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="nightscoutapiversion").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="nightscoutauthtype").drop(op.get_bind(), checkfirst=True)
