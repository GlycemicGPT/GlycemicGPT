"""Story 35.9: Bootstrap seed for clinical knowledge base.

Seeds the knowledge_chunks table with authoritative clinical content
on first startup. Idempotent across restarts and safe under concurrent
replicas via a Postgres advisory lock.

Issue #563 history: this function was previously broken in three ways:
the seed used the tier label "CURATED" (not in the design), the
knowledge directory was never created, and the function was never
invoked from anywhere. All three are fixed; the function now runs from
the FastAPI lifespan in main.py.

Adversarial-review follow-ups (same PR):
- Skip-check is scoped to source_type='bootstrap' so chunks added by
  other paths (AI researcher, user upload) don't suppress seeding.
- Concurrent replicas serialize via pg_try_advisory_xact_lock so the
  skip-check race can't double-insert.
- Skip is per-content-hash so adding new files in a later PR is picked
  up automatically rather than being silently skipped because some
  bootstrap content already exists.
- Content is rejected at seed time if it matches the prompt-injection
  patterns -- AUTHORITATIVE bypasses the runtime injection filter, so
  the safety check has to run at ingest.
"""

import asyncio
import hashlib
import re
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.logging_config import get_logger
from src.models.knowledge_chunk import KnowledgeChunk
from src.services.embedding import embed_texts

logger = get_logger(__name__)

# Directory containing bootstrap knowledge files
KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "knowledge"

# Target chunk size in characters (~512 tokens at ~4 chars/token)
CHUNK_SIZE = 2000
CHUNK_OVERLAP = 200

# source_type marker for chunks inserted by this seed. The skip-check
# and per-hash dedup both filter by this so other AUTHORITATIVE-tier
# content (e.g. ops-inserted clinical references) doesn't interfere.
SOURCE_TYPE_BOOTSTRAP = "bootstrap"

# Postgres advisory lock key for the seed routine. Computed once from a
# stable string so all replicas use the same key. The signed-int64 mask
# is required because pg_try_advisory_xact_lock takes bigint.
SEED_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"glycemicgpt_knowledge_seed").digest()[:8],
    byteorder="big",
    signed=True,
)

# Markdown H1 detector for source_name derivation. Matches "# Heading"
# at the start of the file (allowing leading whitespace/newlines).
_H1_PATTERN = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)

# Patterns that suggest the seed file contains prompt-injection content.
# These are intentionally conservative -- bootstrap content is shipped
# in the Docker image, so the threat model is "compromised contributor
# or upstream copy" rather than "user-controlled input." If any pattern
# matches, the chunk is rejected and a warning is logged so the file
# can be reviewed.
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*:", re.IGNORECASE),
    re.compile(r"override\s+(safety|guidelines|protocol)", re.IGNORECASE),
    re.compile(r"do\s+not\s+mention\s+this", re.IGNORECASE),
]


def _check_injection_risk(content: str) -> bool:
    return any(p.search(content) for p in _INJECTION_PATTERNS)


def _chunk_text(
    text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    """Split text into overlapping chunks by paragraph boundaries.

    Tries to break at paragraph boundaries (double newlines) to keep
    semantic units together. Falls back to character-level splitting
    if paragraphs are too long.
    """
    if overlap >= chunk_size:
        raise ValueError("overlap must be less than chunk_size")

    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current) + len(para) + 2 <= chunk_size:
            current = current + "\n\n" + para if current else para
        else:
            if current:
                chunks.append(current.strip())
            # If a single paragraph exceeds chunk_size, split it
            if len(para) > chunk_size:
                for i in range(0, len(para), chunk_size - overlap):
                    chunks.append(para[i : i + chunk_size].strip())
            else:
                current = para
                continue
            current = ""

    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if len(c) > 50]  # Skip tiny fragments


def _derive_source_name(file_path: Path, content: str) -> str:
    """Use the first markdown H1 as the human-friendly source name.

    Falls back to the filename stem (title-cased) if no H1 is present.
    Title-casing the stem gives ugly results for acronyms (e.g. "Ada"
    instead of "ADA"), so contributors should always include an H1.
    """
    match = _H1_PATTERN.search(content)
    if match:
        return match.group(1).strip()
    return file_path.stem.replace("-", " ").title()


async def _try_acquire_seed_lock(db: AsyncSession) -> bool:
    """Acquire a transaction-scoped advisory lock so only one replica
    seeds at a time. The lock is automatically released when the
    surrounding transaction commits or rolls back."""
    result = await db.execute(
        text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": SEED_LOCK_KEY}
    )
    return bool(result.scalar())


async def seed_knowledge_base(db: AsyncSession) -> int:
    """Seed the knowledge base with bootstrap clinical content.

    Returns the number of chunks newly inserted.

    The function is idempotent: it computes a content_hash for every
    chunk in every file and skips any hash that already exists in the
    DB. Adding new files in a later PR will pick them up automatically.

    Concurrent replicas serialize on a Postgres advisory lock; if a
    different replica is already seeding, this call returns 0 cleanly.
    """
    locked = await _try_acquire_seed_lock(db)
    if not locked:
        logger.info("Knowledge seed lock held by another replica; skipping")
        # Roll back to release the (failed-to-acquire) transaction we
        # opened by issuing pg_try_advisory_xact_lock. Without this,
        # the empty transaction stays open until the surrounding
        # session closes -- harmless but pollutes pg_stat_activity.
        await db.rollback()
        return 0

    # Helper: every early-return path below this point holds the
    # xact-scoped advisory lock. Commit (or roll back) before returning
    # so the lock is released promptly rather than waiting for the
    # surrounding `async with session_maker()` to close.
    async def _release_and_return(value: int) -> int:
        await db.commit()
        return value

    if settings.embedding_offline_only:
        # Air-gapped/firewalled deployments: refuse to download the
        # embedding model. The seed is skipped cleanly so AI chat can
        # still serve user-provided context, just without bootstrap RAG.
        logger.info("Knowledge seed skipped: embedding_offline_only is set")
        return await _release_and_return(0)

    if not KNOWLEDGE_DIR.exists():
        logger.warning("Knowledge directory not found", path=str(KNOWLEDGE_DIR))
        return await _release_and_return(0)

    # Skip README.md and any file starting with "_". README.md documents
    # the editorial conventions (and the injection patterns themselves)
    # and would be rejected; "_" prefix is a conventional way to mark a
    # markdown file as not-for-ingestion (e.g. _draft-foo.md).
    files = sorted(
        f
        for f in KNOWLEDGE_DIR.glob("*.md")
        if f.name != "README.md" and not f.name.startswith("_")
    )
    if not files:
        logger.warning("No knowledge files found", path=str(KNOWLEDGE_DIR))
        return await _release_and_return(0)

    # Get existing bootstrap content_hashes so we can dedup per-chunk.
    # Scoping to source_type='bootstrap' avoids tripping on AUTHORITATIVE
    # rows added by other code paths (e.g. ops imports).
    existing_result = await db.execute(
        select(KnowledgeChunk.content_hash).where(
            KnowledgeChunk.source_type == SOURCE_TYPE_BOOTSTRAP,
            KnowledgeChunk.user_id.is_(None),
        )
    )
    existing_hashes: set[str] = {h for h in existing_result.scalars().all() if h}

    # Build the list of chunks that need to be embedded + inserted.
    pending: list[dict] = []
    rejected_files: list[str] = []
    for file_path in files:
        content = file_path.read_text(encoding="utf-8")
        source_name = _derive_source_name(file_path, content)
        chunks = _chunk_text(content)

        file_rejected = False
        for chunk_text in chunks:
            if _check_injection_risk(chunk_text):
                # AUTHORITATIVE bypasses the runtime injection filter,
                # so a chunk that looks like an injection attempt MUST
                # NOT be ingested. Reject the entire file rather than
                # silently dropping a chunk -- that would produce
                # incomplete content from an apparently-trusted source.
                logger.error(
                    "Knowledge file rejected: injection pattern in chunk",
                    file=file_path.name,
                )
                rejected_files.append(file_path.name)
                file_rejected = True
                break

            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()
            if content_hash in existing_hashes:
                continue
            pending.append(
                {
                    "source_name": source_name,
                    "source_type": SOURCE_TYPE_BOOTSTRAP,
                    "content": chunk_text,
                    "content_hash": content_hash,
                    "trust_tier": KnowledgeChunk.TIER_AUTHORITATIVE,
                    "file": file_path.name,
                }
            )

        if file_rejected:
            # Drop any chunks staged from the rejected file from the
            # pending list (they would have been ingested otherwise).
            pending = [c for c in pending if c["file"] != file_path.name]

    if rejected_files:
        # Surface this loudly. A rejected file is a content-pipeline
        # bug or a tampered upstream -- not a "skip silently" event.
        logger.warning(
            "Knowledge files rejected at seed time",
            files=rejected_files,
        )

    if not pending:
        logger.info(
            "Knowledge base already seeded; no new chunks to embed",
            files=len(files),
            existing=len(existing_hashes),
        )
        return await _release_and_return(0)

    logger.info(
        "Embedding knowledge chunks",
        count=len(pending),
        files=len(files),
    )
    try:
        embeddings = await asyncio.to_thread(
            embed_texts, [c["content"] for c in pending]
        )
    except Exception:
        logger.error("Failed to embed knowledge chunks", exc_info=True)
        await db.rollback()  # Releases the advisory lock
        return 0

    # Use INSERT ... ON CONFLICT DO NOTHING against the partial unique
    # index added in migration 050. Defense-in-depth: even if the
    # advisory lock were bypassed (e.g. a future code change moves the
    # seed to a path that does not hold the lock), the DB still cannot
    # accept duplicate (content_hash, user_id) rows. The RETURNING id
    # clause lets us count actual inserts -- ON CONFLICT rows do not
    # appear in the returning result.
    #
    # Both the per-chunk INSERTs and the final commit are wrapped in
    # one try/except so an INSERT failure (e.g. constraint violation,
    # connection drop) rolls back cleanly instead of leaving the
    # session in an undefined state.
    inserted = 0
    try:
        for chunk_data, embedding in zip(pending, embeddings, strict=True):
            stmt = (
                pg_insert(KnowledgeChunk)
                .values(
                    user_id=None,  # Shared system knowledge
                    trust_tier=chunk_data["trust_tier"],
                    source_type=chunk_data["source_type"],
                    source_name=chunk_data["source_name"],
                    content=chunk_data["content"],
                    embedding=embedding,
                    content_hash=chunk_data["content_hash"],
                    metadata_json={"file": chunk_data["file"]},
                )
                .on_conflict_do_nothing(
                    index_elements=["content_hash", "user_id"],
                    index_where=text("content_hash IS NOT NULL"),
                )
                .returning(KnowledgeChunk.id)
            )
            result = await db.execute(stmt)
            if result.scalar_one_or_none() is not None:
                inserted += 1
        await db.commit()
    except SQLAlchemyError:
        # Roll back so the session is reusable; the caller's narrow
        # except in main.py will log and continue starting up. The
        # rollback also releases the xact-scoped advisory lock.
        await db.rollback()
        raise

    logger.info(
        "Knowledge base seeded",
        chunks_inserted=inserted,
        files_processed=len(files),
        rejected_files=len(rejected_files),
    )
    return inserted
