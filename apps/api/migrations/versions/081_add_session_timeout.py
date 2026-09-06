"""Add session_timeout_minutes column to users (per-user web-session lifetime).

The web session lifetime was a single deployment-wide setting
(``SESSION_EXPIRE_HOURS``, 24h) baked into the JWT ``exp`` and the session
cookie ``max-age`` at login. This makes it a per-user preference: each user can
choose how long their browser session stays valid (bounded 15 min .. 7 days),
set from Settings and applied at the next login.

The column is NOT NULL with a server default of 1440 (24h), so every existing
row keeps exactly today's behaviour with no backfill and no re-prompt.

Revision ID: 081_add_session_timeout
Revises: 080_add_no_data_alert_type
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op

revision = "081_add_session_timeout"
down_revision = "080_add_no_data_alert_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default "1440" (24h) preserves the historical SESSION_EXPIRE_HOURS
    # lifetime for every existing user; the app default and the User model
    # default match this literal.
    op.add_column(
        "users",
        sa.Column(
            "session_timeout_minutes",
            sa.Integer(),
            nullable=False,
            server_default="1440",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "session_timeout_minutes")
