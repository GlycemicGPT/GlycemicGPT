"""Add user glucose unit preference.

Revision ID: 075_user_glucose_unit
Revises: 074_food_record_comorbidity
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "075_user_glucose_unit"
down_revision: str | None = "074_food_record_comorbidity"
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
