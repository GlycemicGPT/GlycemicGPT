"""Add device fingerprinting, API keys, and security audit logs.

Revision ID: 039_device_binding_api_keys
Revises: 038_daily_bolus_validation
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "039_device_binding_api_keys"
down_revision = "038_daily_bolus_validation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Enhanced device registration columns ---
    op.add_column(
        "device_registrations",
        sa.Column("device_fingerprint", sa.String(64), nullable=True),
    )
    op.add_column(
        "device_registrations",
        sa.Column("app_version", sa.String(50), nullable=True),
    )
    op.add_column(
        "device_registrations",
        sa.Column(
            "build_type",
            sa.String(20),
            nullable=True,
            server_default="release",
        ),
    )
    op.create_index(
        "ix_device_registrations_fingerprint",
        "device_registrations",
        ["device_fingerprint"],
        unique=True,
        postgresql_where=sa.text("device_fingerprint IS NOT NULL"),
    )

    # --- API keys table ---
    op.create_table(
        "api_keys",
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
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("prefix", sa.String(12), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column(
            "scopes",
            sa.Text(),
            nullable=False,
            server_default="read:glucose",
        ),
        sa.Column(
            "build_type",
            sa.String(20),
            nullable=True,
            server_default="release",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"], unique=True)

    # --- Security audit logs table ---
    op.create_table(
        "security_audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_security_audit_logs_event_type",
        "security_audit_logs",
        ["event_type"],
    )
    op.create_index(
        "ix_security_audit_logs_created_at",
        "security_audit_logs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_security_audit_logs_created_at", "security_audit_logs")
    op.drop_index("ix_security_audit_logs_event_type", "security_audit_logs")
    op.drop_table("security_audit_logs")

    op.drop_index("ix_api_keys_prefix", "api_keys")
    op.drop_index("ix_api_keys_user_id", "api_keys")
    op.drop_table("api_keys")

    op.drop_index("ix_device_registrations_fingerprint", "device_registrations")
    op.drop_column("device_registrations", "build_type")
    op.drop_column("device_registrations", "app_version")
    op.drop_column("device_registrations", "device_fingerprint")
