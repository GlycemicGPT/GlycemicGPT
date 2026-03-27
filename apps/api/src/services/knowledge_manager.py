"""Story 35.10: Knowledge Base management service.

Groups raw knowledge_chunks into logical documents and provides
list, view, delete, and stats operations for the Knowledge Base UI.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.knowledge_chunk import KnowledgeChunk
from src.schemas.knowledge import (
    KnowledgeChunkResponse,
    KnowledgeDocumentSummary,
    KnowledgeStatsResponse,
)

logger = get_logger(__name__)


async def list_documents(
    db: AsyncSession,
    user_id: uuid.UUID,
    trust_tier: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[KnowledgeDocumentSummary], int, int]:
    """List knowledge documents grouped by source.

    Documents are virtual aggregations of chunks grouped by
    (source_name, source_url, source_type, trust_tier).

    Returns: (documents, total_document_count, total_chunk_count)
    """
    # Base filter: user's own + shared, currently valid
    base_filters = [
        or_(
            KnowledgeChunk.user_id == user_id,
            KnowledgeChunk.user_id.is_(None),
        ),
        KnowledgeChunk.valid_to.is_(None),
    ]

    if trust_tier:
        base_filters.append(KnowledgeChunk.trust_tier == trust_tier)

    if search:
        # Escape ILIKE wildcards, search source_name only (not content -- too expensive)
        escaped = search.replace("%", r"\%").replace("_", r"\_")
        search_pattern = f"%{escaped}%"
        base_filters.append(KnowledgeChunk.source_name.ilike(search_pattern))

    # Get grouped documents with aggregates
    group_cols = [
        KnowledgeChunk.source_name,
        KnowledgeChunk.source_url,
        KnowledgeChunk.source_type,
        KnowledgeChunk.trust_tier,
    ]

    query = (
        select(
            KnowledgeChunk.source_name,
            KnowledgeChunk.source_url,
            KnowledgeChunk.source_type,
            KnowledgeChunk.trust_tier,
            func.count().label("chunk_count"),
            func.sum(func.length(KnowledgeChunk.content)).label("total_length"),
            func.min(KnowledgeChunk.created_at).label("first_created"),
            func.max(KnowledgeChunk.retrieved_at).label("last_updated"),
            func.sum(func.cast(KnowledgeChunk.injection_risk, sa.Integer)).label(
                "injection_count"
            ),
        )
        .where(*base_filters)
        .group_by(*group_cols)
        .order_by(func.max(KnowledgeChunk.created_at).desc())
    )

    # Get total document count using subquery (count grouped rows)
    subq = (
        select(KnowledgeChunk.source_name)
        .where(*base_filters)
        .group_by(*group_cols)
        .subquery()
    )
    total_doc_result = await db.execute(select(func.count()).select_from(subq))
    total_documents = total_doc_result.scalar() or 0

    # Total chunks
    total_chunk_result = await db.execute(select(func.count()).where(*base_filters))
    total_chunks = total_chunk_result.scalar() or 0

    # Paginated results
    offset = (page - 1) * page_size
    result = await db.execute(query.offset(offset).limit(page_size))
    rows = result.all()

    documents = []
    for row in rows:
        documents.append(
            KnowledgeDocumentSummary(
                source_name=row.source_name or "Unknown",
                source_url=row.source_url,
                source_type=row.source_type or "unknown",
                trust_tier=row.trust_tier or "UNKNOWN",
                chunk_count=row.chunk_count,
                total_content_length=row.total_length or 0,
                first_created=row.first_created,
                last_updated=row.last_updated,
                injection_risk_count=row.injection_count or 0,
            )
        )

    return documents, total_documents, total_chunks


async def get_document_chunks(
    db: AsyncSession,
    user_id: uuid.UUID,
    source_name: str,
    source_url: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[KnowledgeChunkResponse], int]:
    """Get all chunks for a specific document grouping.

    Returns: (chunks, total_count)
    """
    filters = [
        or_(
            KnowledgeChunk.user_id == user_id,
            KnowledgeChunk.user_id.is_(None),
        ),
        KnowledgeChunk.valid_to.is_(None),
        KnowledgeChunk.source_name == source_name,
    ]
    if source_url:
        filters.append(KnowledgeChunk.source_url == source_url)
    else:
        filters.append(KnowledgeChunk.source_url.is_(None))

    # Total count
    count_result = await db.execute(select(func.count()).where(*filters))
    total = count_result.scalar() or 0

    # Paginated chunks
    offset = (page - 1) * page_size
    result = await db.execute(
        select(KnowledgeChunk)
        .where(*filters)
        .order_by(KnowledgeChunk.created_at.asc())
        .offset(offset)
        .limit(page_size)
    )
    chunks = []
    for chunk in result.scalars().all():
        content = chunk.content or ""
        chunks.append(
            KnowledgeChunkResponse(
                id=chunk.id,
                content=content,
                content_preview=content[:200] + "..."
                if len(content) > 200
                else content,
                content_length=len(content),
                source_url=chunk.source_url,
                retrieved_at=chunk.retrieved_at,
                created_at=chunk.created_at,
                injection_risk=chunk.injection_risk,
            )
        )

    return chunks, total


async def delete_document(
    db: AsyncSession,
    user_id: uuid.UUID,
    source_name: str,
    source_url: str | None = None,
) -> int:
    """Soft-delete a document by invalidating all its chunks.

    Only user-owned chunks can be deleted (not shared system chunks).
    Sets valid_to=now() and records the deletion in audit columns.

    Returns: number of chunks invalidated.
    """
    now = datetime.now(UTC)

    filters = [
        KnowledgeChunk.user_id == user_id,  # Only user's own chunks
        KnowledgeChunk.valid_to.is_(None),
        KnowledgeChunk.source_name == source_name,
    ]
    if source_url:
        filters.append(KnowledgeChunk.source_url == source_url)
    else:
        filters.append(KnowledgeChunk.source_url.is_(None))

    # Bulk update for efficiency (avoids loading all chunks into memory)
    from sqlalchemy import update

    result = await db.execute(
        update(KnowledgeChunk)
        .where(*filters)
        .values(
            valid_to=now,
            updated_at=now,
            update_source="manual_delete",
            change_summary="Deleted by user via Knowledge Base UI",
        )
    )
    count = result.rowcount

    if count > 0:
        await db.commit()

    logger.info(
        "Knowledge document deleted",
        user_id=str(user_id),
        source_name=source_name,
        chunks_invalidated=count,
    )

    return count


async def get_knowledge_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> KnowledgeStatsResponse:
    """Get aggregate knowledge base statistics."""
    base_filters = [
        or_(
            KnowledgeChunk.user_id == user_id,
            KnowledgeChunk.user_id.is_(None),
        ),
        KnowledgeChunk.valid_to.is_(None),
    ]

    # Total chunks
    total_result = await db.execute(select(func.count()).where(*base_filters))
    total_chunks = total_result.scalar() or 0

    # By tier
    tier_result = await db.execute(
        select(KnowledgeChunk.trust_tier, func.count())
        .where(*base_filters)
        .group_by(KnowledgeChunk.trust_tier)
    )
    by_tier = {row[0]: row[1] for row in tier_result.all()}

    # Document count (matching grouped definition from list_documents)
    stats_subq = (
        select(KnowledgeChunk.source_name)
        .where(*base_filters)
        .group_by(
            KnowledgeChunk.source_name,
            KnowledgeChunk.source_url,
            KnowledgeChunk.source_type,
            KnowledgeChunk.trust_tier,
        )
        .subquery()
    )
    doc_result = await db.execute(select(func.count()).select_from(stats_subq))
    total_documents = doc_result.scalar() or 0

    return KnowledgeStatsResponse(
        total_documents=total_documents,
        total_chunks=total_chunks,
        by_tier=by_tier,
    )
