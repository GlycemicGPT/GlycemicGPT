"""Add glucose unit preference provenance.

Tracks whether a user's ``glucose_unit`` was set by a smart default (``seed``)
or an explicit user choice (``user``), so a region/Nightscout seed never
overrides a manual choice and the one-time confirmation notice never recurs
(Story 53.10). Nullable: existing rows stay NULL (seed-neutral); no backfill.
Display-preference only -- no stored glucose value or bound changes.

Revision ID: 076_glucose_unit_source
Revises: 075_user_glucose_unit
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "076_glucose_unit_source"
down_revision: str | None = "075_user_glucose_unit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    glucose_unit_source = postgresql.ENUM(
        "seed", "user", name="glucoseunitsource"
    )
    glucose_unit_source.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "users",
        sa.Column(
            "glucose_unit_source",
            postgresql.ENUM(
                "seed", "user", name="glucoseunitsource", create_type=False
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "glucose_unit_source")

    glucose_unit_source = postgresql.ENUM(
        "seed", "user", name="glucoseunitsource"
    )
    glucose_unit_source.drop(op.get_bind(), checkfirst=True)
