"""Story 35.10: Add audit columns to knowledge_chunks for Knowledge Base viewer.

Revision ID: 049_knowledge_audit_columns
Revises: 048_rag_infrastructure
Create Date: 2026-03-27
"""

from alembic import op
import sqlalchemy as sa

revision = "049_knowledge_audit_columns"
down_revision = "048_rag_infrastructure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "added_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column("update_source", sa.String(50), nullable=True),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column("change_summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_chunks", "change_summary")
    op.drop_column("knowledge_chunks", "update_source")
    op.drop_column("knowledge_chunks", "updated_at")
    op.drop_column("knowledge_chunks", "added_by_user_id")
