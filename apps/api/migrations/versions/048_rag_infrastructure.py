"""Story 35.9: RAG infrastructure -- pgvector extension and knowledge tables.

Revision ID: 048_rag_infrastructure
Revises: 047_create_chat_messages
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa

revision = "048_rag_infrastructure"
down_revision = "047_create_chat_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Knowledge chunks with vector embeddings
    op.create_table(
        "knowledge_chunks",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("trust_tier", sa.String(20), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_name", sa.String(200), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        # Vector column added via raw SQL since Alembic doesn't natively support it
        sa.Column("metadata_json", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column(
            "retrieved_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "injection_risk",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Add vector column via raw SQL (pgvector type)
    op.execute(
        "ALTER TABLE knowledge_chunks ADD COLUMN embedding vector(768)"
    )

    op.create_index(
        "ix_knowledge_user_valid",
        "knowledge_chunks",
        ["user_id", "valid_to"],
    )
    op.create_index(
        "ix_knowledge_trust",
        "knowledge_chunks",
        ["trust_tier", "valid_to"],
    )

    # HNSW index for fast vector similarity search
    op.execute(
        "CREATE INDEX ix_knowledge_embedding ON knowledge_chunks "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # Research sources (user-configurable)
    op.create_table(
        "research_sources",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.Column(
            "last_researched_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("last_content_hash", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_research_user_active",
        "research_sources",
        ["user_id", "is_active"],
    )

    # User documents
    op.create_table(
        "user_documents",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(20), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column(
            "chunk_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "injection_risk",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("user_documents")
    op.drop_index("ix_research_user_active", table_name="research_sources")
    op.drop_table("research_sources")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_embedding")
    op.drop_index("ix_knowledge_trust", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_user_valid", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.execute("DROP EXTENSION IF EXISTS vector")
