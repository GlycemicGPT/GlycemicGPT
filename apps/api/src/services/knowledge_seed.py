"""Story 35.9: Bootstrap seed for clinical knowledge base.

Seeds the knowledge_chunks table with authoritative clinical content
on first startup. Skipped if content already exists.
"""

import asyncio
import hashlib
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.knowledge_chunk import KnowledgeChunk
from src.services.embedding import embed_texts

logger = get_logger(__name__)

# Directory containing bootstrap knowledge files
KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "knowledge"

# Target chunk size in characters (~512 tokens at ~4 chars/token)
CHUNK_SIZE = 2000
CHUNK_OVERLAP = 200


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


async def seed_knowledge_base(db: AsyncSession) -> int:
    """Seed the knowledge base with bootstrap clinical content.

    Skips if knowledge_chunks already has CURATED content.
    Embedding is done BEFORE opening the DB session for INSERT to avoid
    connection timeouts during the CPU-heavy embedding step.
    Returns the number of chunks inserted.
    """
    # Check if already seeded
    count_result = await db.execute(
        select(func.count()).where(
            KnowledgeChunk.trust_tier == "CURATED",
            KnowledgeChunk.user_id.is_(None),
        )
    )
    existing = count_result.scalar() or 0
    if existing > 0:
        logger.info("Knowledge base already seeded", existing_chunks=existing)
        return 0

    if not KNOWLEDGE_DIR.exists():
        logger.warning("Knowledge directory not found", path=str(KNOWLEDGE_DIR))
        return 0

    # Collect all markdown files
    files = sorted(KNOWLEDGE_DIR.glob("*.md"))
    if not files:
        logger.warning("No knowledge files found", path=str(KNOWLEDGE_DIR))
        return 0

    logger.info("Seeding knowledge base", files=len(files))

    all_chunks: list[dict] = []
    all_texts: list[str] = []

    for file_path in files:
        content = file_path.read_text(encoding="utf-8")
        source_name = file_path.stem.replace("-", " ").title()
        chunks = _chunk_text(content)

        for chunk_text in chunks:
            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()
            all_chunks.append(
                {
                    "source_name": source_name,
                    "source_type": "bootstrap",
                    "content": chunk_text,
                    "content_hash": content_hash,
                    "trust_tier": "CURATED",
                    "file": file_path.name,
                }
            )
            all_texts.append(chunk_text)

    if not all_texts:
        logger.warning("No content to seed")
        return 0

    # Batch embed all chunks FIRST (CPU-heavy, can take minutes on first run).
    # Run in thread to avoid blocking the async event loop.
    logger.info("Embedding knowledge chunks", count=len(all_texts))
    try:
        embeddings = await asyncio.to_thread(embed_texts, all_texts)
    except Exception:
        logger.error("Failed to embed knowledge chunks", exc_info=True)
        return 0

    # Now store chunks in a quick DB operation (embeddings already computed).
    # Use content_hash to skip chunks that already exist (idempotency).
    inserted = 0
    for chunk_data, embedding in zip(all_chunks, embeddings, strict=True):
        # Check for existing chunk with same hash (handles race conditions)
        existing = await db.execute(
            select(func.count()).where(
                KnowledgeChunk.content_hash == chunk_data["content_hash"],
                KnowledgeChunk.user_id.is_(None),
            )
        )
        if (existing.scalar() or 0) > 0:
            continue

        db.add(
            KnowledgeChunk(
                user_id=None,  # Shared system knowledge
                trust_tier=chunk_data["trust_tier"],
                source_type=chunk_data["source_type"],
                source_name=chunk_data["source_name"],
                content=chunk_data["content"],
                embedding=embedding,
                content_hash=chunk_data["content_hash"],
                metadata_json={"file": chunk_data["file"]},
            )
        )
        inserted += 1

    await db.commit()

    logger.info(
        "Knowledge base seeded",
        chunks_inserted=inserted,
        chunks_skipped=len(all_chunks) - inserted,
        files_processed=len(files),
    )

    return inserted
