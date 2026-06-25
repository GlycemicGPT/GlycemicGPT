"""Add per-user meal-intelligence preference.

Replaces the former global ``MEAL_INTELLIGENCE_ENABLED`` env flag with a
per-user, in-app preference. Defaults ON so the shipped feature is discoverable
without operator intervention; the user can disable it from Settings.

Revision ID: 077_meal_intelligence_enabled
Revises: 076_glucose_unit_source
Create Date: 2026-06-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "077_meal_intelligence_enabled"
down_revision: str | None = "076_glucose_unit_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "meal_intelligence_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "meal_intelligence_enabled")
