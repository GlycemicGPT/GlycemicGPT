"""Add CHECK constraints on build_type columns.

Ensures build_type can only be 'debug' or 'release', preventing
arbitrary strings from bypassing policy assumptions.

Revision ID: 040_build_type_check
Revises: 039_device_binding_api_keys
"""

from alembic import op

revision = "040_build_type_check"
down_revision = "039_device_binding_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_device_registrations_build_type",
        "device_registrations",
        "build_type IN ('debug', 'release')",
    )
    op.create_check_constraint(
        "ck_api_keys_build_type",
        "api_keys",
        "build_type IN ('debug', 'release')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_api_keys_build_type", "api_keys", type_="check")
    op.drop_constraint(
        "ck_device_registrations_build_type", "device_registrations", type_="check"
    )
