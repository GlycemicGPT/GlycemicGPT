"""Add token_version column to users (session-generation token revocation).

Revocation on password change is driven by a per-user session generation rather
than an iat-vs-timestamp comparison: every access/refresh token embeds this
value as its ``ver`` claim, and a change increments it, so tokens minted with an
older value are rejected. Unlike the timestamp approach this has no sub-second
boundary and cannot be laundered by a refresh that races the change (the newly
minted token carries the pre-change version). password_changed_at (migration
082) is retained as an audit field.

The column is NOT NULL with a server default of 1. Existing rows read 1, and
tokens minted before this field existed carry no ``ver`` claim and are treated
as version 1, so the migration forces no re-login.

Revision ID: 083_add_user_token_version
Revises: 082_add_password_changed_at
Create Date: 2026-09-12
"""

import sqlalchemy as sa
from alembic import op

revision = "083_add_user_token_version"
down_revision = "082_add_password_changed_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
