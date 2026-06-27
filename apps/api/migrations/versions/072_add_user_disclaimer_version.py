"""Add disclaimer_version column to users (version-aware re-acknowledgment).

The authenticated disclaimer flow previously stored only a boolean
``disclaimer_acknowledged``, so a version bump had to force re-consent with a
one-shot reset migration (see ``056_reset_disclaimer_for_v1_1``, whose own note
recommends adding this column instead). This adds the column so the auth flow
mirrors the session flow: ``has_acknowledged_current`` counts an acknowledgment
only when the stored version equals the current DISCLAIMER_VERSION.

The column is nullable with no backfill: every existing acknowledged user has
``disclaimer_version = NULL``, which does not equal the current version, so they
are re-prompted exactly once for the v1.2 (Story 50.S photo carb-estimate)
wording -- and every future bump re-prompts automatically with no new migration.

Revision ID: 072_add_user_disclaimer_version
Revises: 071_food_record_audit_provenance
Create Date: 2026-06-17
"""

import sqlalchemy as sa
from alembic import op

revision = "072_add_user_disclaimer_version"
down_revision = "071_food_record_audit_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable, no server default: a NULL on existing rows is intentional -- it
    # means "acknowledged an unknown/older version" and re-prompts those users
    # for the current disclaimer. New acknowledgments set it via /acknowledge-auth.
    op.add_column(
        "users",
        sa.Column("disclaimer_version", sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "disclaimer_version")
