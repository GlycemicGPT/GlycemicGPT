"""Add stable Telegram bot identity.

Revision ID: 082_add_telegram_bot_identity
Revises: 081_create_telegram_bot_config
"""

import sqlalchemy as sa
from alembic import op

revision = "082_add_telegram_bot_identity"
down_revision = "081_create_telegram_bot_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telegram_bot_configs",
        sa.Column("bot_id", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telegram_bot_configs", "bot_id")
