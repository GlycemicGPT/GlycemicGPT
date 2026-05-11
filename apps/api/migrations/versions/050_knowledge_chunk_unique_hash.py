"""Issue #563 follow-up: prevent duplicate knowledge chunks across replicas.

Adds a partial UNIQUE index on (content_hash, user_id) so concurrent
replica startups cannot double-insert bootstrap content even if the
advisory lock in seed_knowledge_base() were ever bypassed (defense in
depth). The index is partial -- only rows with a non-null content_hash
participate -- because legacy chunks may have NULL content_hash and we
do not want to retroactively block multiple NULLs from coexisting.

Tested at migration time against an existing dev DB: zero duplicate
(content_hash, user_id) tuples were found, so the index can be created
without a pre-cleanup step. If the migration ever fails on a deployed
DB with duplicates, run::

    DELETE FROM knowledge_chunks a USING knowledge_chunks b
    WHERE a.id < b.id
      AND a.content_hash = b.content_hash
      AND a.user_id IS NOT DISTINCT FROM b.user_id
      AND a.content_hash IS NOT NULL;

before re-running.

Revision ID: 050_knowledge_chunk_unique_hash
Revises: 049_knowledge_audit_columns
Create Date: 2026-05-04
"""

from alembic import op

revision = "050_knowledge_chunk_unique_hash"
down_revision = "049_knowledge_audit_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Partial unique index keyed on (content_hash, user_id). NULLS NOT
    # DISTINCT (requires Postgres 16, per the project's documented
    # minimum) makes the user_id IS NULL case equal so shared bootstrap
    # chunks (user_id NULL) cannot duplicate either. Using a real
    # (non-functional) index keeps ON CONFLICT inference straightforward
    # in pg_insert(...).on_conflict_do_nothing().
    op.execute(
        """
        CREATE UNIQUE INDEX ix_knowledge_chunks_content_hash_unique
        ON knowledge_chunks (content_hash, user_id) NULLS NOT DISTINCT
        WHERE content_hash IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_content_hash_unique")
