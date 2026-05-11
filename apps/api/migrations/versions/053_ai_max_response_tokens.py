"""Add max_response_tokens to ai_provider_configs.

Lets users override the default per-response token budget used by AI
chat (web and Telegram). Critical for "thinking" models like Qwen3 and
DeepSeek where internal `<think>...</think>` reasoning tokens count
against the same budget as the visible response -- a 1200-token cap
gets exhausted by the thinking phase, leaving the user with truncated
or empty output (issue #554).

NULL = use the per-context default (1200 web, 800 Telegram). Existing
rows are not migrated; they keep the historical behavior.

Bounds: 256-32768. The lower bound rules out values that can't fit a
useful response; the upper bound matches the largest output context
window the supported providers ship today.

Revision ID: 053_ai_max_response_tokens
Revises: 052_nightscout_translator
Create Date: 2026-05-10
"""

import sqlalchemy as sa
from alembic import op

revision = "053_ai_max_response_tokens"
down_revision = "052_nightscout_translator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_provider_configs",
        sa.Column("max_response_tokens", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_ai_provider_max_response_tokens_range",
        "ai_provider_configs",
        "max_response_tokens IS NULL OR (max_response_tokens BETWEEN 256 AND 32768)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ai_provider_max_response_tokens_range",
        "ai_provider_configs",
        type_="check",
    )
    op.drop_column("ai_provider_configs", "max_response_tokens")
