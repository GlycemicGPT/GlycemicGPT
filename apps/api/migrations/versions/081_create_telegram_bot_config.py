"""Create encrypted Telegram bot configuration.

Revision ID: 081_create_telegram_bot_config
Revises: 080_add_no_data_alert_type
"""

import sqlalchemy as sa
from alembic import op

revision = "081_create_telegram_bot_config"
down_revision = "080_add_no_data_alert_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_bot_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("bot_username", sa.String(length=64), nullable=False),
        sa.Column(
            "configured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "id = 1",
            name="ck_telegram_bot_configs_singleton",
        ),
    )


def downgrade() -> None:
    op.drop_table("telegram_bot_configs")
