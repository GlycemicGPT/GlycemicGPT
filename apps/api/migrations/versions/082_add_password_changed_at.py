"""Add password_changed_at column to users (session/refresh revocation).

Changing a password previously only blacklisted the access token used for the
request; other sessions and refresh tokens stayed valid (CWE-613). This adds a
per-user revocation timestamp: on password change it is stamped with the change
time, and any access or refresh token whose ``iat`` predates it is rejected, so
the change evicts every outstanding session and refresh token.

The column is nullable with no default. Existing rows read NULL, meaning "never
changed" -- no restriction -- so the migration forces no re-login and preserves
today's behaviour until the user's first password change.

Revision ID: 082_add_password_changed_at
Revises: 081_add_session_timeout
Create Date: 2026-09-12
"""

import sqlalchemy as sa
from alembic import op

revision = "082_add_password_changed_at"
down_revision = "081_add_session_timeout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "password_changed_at")
