"""Add the food_record_audits provenance table (Story 50.H3).

Makes a meal-photo estimate auditable after the fact: per food record, the raw
per-sample vision outputs (50.H1), the empirical dispersion summary, and the
precedence decision + identity used (50.H2). 1:1 with food_records, owner-scoped,
and ON DELETE CASCADE on both the record and the user so deleting either (single
delete or a retention purge) drops the audit trail automatically -- no raw image
bytes are duplicated (the photo reference stays on the food record). The grounding
attribution itself reuses the existing food_records.grounding_* columns (50.E1);
this table adds only the new raw-sample + precedence provenance.

Revision ID: 071_food_record_audit_provenance
Revises: 070_food_record_identity
Create Date: 2026-06-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "071_food_record_audit_provenance"
down_revision = "070_food_record_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "food_record_audits",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("food_record_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("samples_json", JSONB(), nullable=True),
        sa.Column("dispersion_json", JSONB(), nullable=True),
        sa.Column("precedence_json", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["food_record_id"], ["food_records.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # 1:1 with the food record.
        sa.UniqueConstraint(
            "food_record_id", name="uq_food_record_audits_food_record_id"
        ),
    )
    op.create_index("ix_food_record_audits_user_id", "food_record_audits", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_food_record_audits_user_id", table_name="food_record_audits")
    op.drop_table("food_record_audits")
