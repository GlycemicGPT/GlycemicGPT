"""Add user glucose unit preference.

Revision ID: 073_user_glucose_unit
Revises: 072_add_user_disclaimer_version
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "073_user_glucose_unit"
down_revision: str | None = "072_add_user_disclaimer_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    glucose_unit = postgresql.ENUM("mgdl", "mmol", name="glucoseunit")
    glucose_unit.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "users",
        sa.Column(
            "glucose_unit",
            postgresql.ENUM("mgdl", "mmol", name="glucoseunit", create_type=False),
            nullable=False,
            server_default="mgdl",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "glucose_unit")

    glucose_unit = postgresql.ENUM("mgdl", "mmol", name="glucoseunit")
    glucose_unit.drop(op.get_bind(), checkfirst=True)
