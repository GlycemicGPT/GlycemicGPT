"""Story 35.10: Knowledge Base viewer API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import DiabeticOrAdminUser
from src.database import get_db
from src.logging_config import get_logger
from src.schemas.auth import ErrorResponse
from src.schemas.knowledge import (
    KnowledgeDeleteResponse,
    KnowledgeDocumentDetailResponse,
    KnowledgeDocumentListResponse,
    KnowledgeStatsResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get(
    "/documents",
    response_model=KnowledgeDocumentListResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def list_knowledge_documents(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
    trust_tier: str | None = Query(
        default=None,
        description="Filter by trust tier",
        pattern="^(AUTHORITATIVE|CURATED|RESEARCHED|USER_PROVIDED|EXTRACTED)$",
    ),
    search: str | None = Query(default=None, max_length=200, description="Search text"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> KnowledgeDocumentListResponse:
    """List knowledge documents grouped by source."""
    from src.services.knowledge_manager import list_documents

    documents, total_docs, total_chunks = await list_documents(
        db,
        current_user.id,
        trust_tier=trust_tier,
        search=search,
        page=page,
        page_size=page_size,
    )

    return KnowledgeDocumentListResponse(
        documents=documents,
        total_documents=total_docs,
        total_chunks=total_chunks,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/documents/chunks",
    response_model=KnowledgeDocumentDetailResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def get_document_chunks(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
    source_name: str = Query(..., description="Document source name"),
    source_url: str | None = Query(default=None, description="Document source URL"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> KnowledgeDocumentDetailResponse:
    """Get chunks for a specific knowledge document."""
    from src.services.knowledge_manager import get_document_chunks as get_chunks

    chunks, total = await get_chunks(
        db,
        current_user.id,
        source_name,
        source_url,
        page=page,
        page_size=page_size,
    )

    if not chunks and total == 0:
        raise HTTPException(status_code=404, detail="Document not found")

    # Get source_type and trust_tier from the database for this document
    from sqlalchemy import or_, select

    from src.models.knowledge_chunk import KnowledgeChunk

    source_url_filter = (
        KnowledgeChunk.source_url == source_url
        if source_url
        else KnowledgeChunk.source_url.is_(None)
    )
    meta_result = await db.execute(
        select(KnowledgeChunk.source_type, KnowledgeChunk.trust_tier)
        .where(
            or_(
                KnowledgeChunk.user_id == current_user.id,
                KnowledgeChunk.user_id.is_(None),
            ),
            KnowledgeChunk.valid_to.is_(None),
            KnowledgeChunk.source_name == source_name,
            source_url_filter,
        )
        .limit(1)
    )
    meta = meta_result.first()

    return KnowledgeDocumentDetailResponse(
        source_name=source_name,
        source_url=source_url,
        source_type=meta[0] if meta else "unknown",
        trust_tier=meta[1] if meta else "UNKNOWN",
        chunk_count=len(chunks),
        chunks=chunks,
        total=total,
    )


@router.delete(
    "/documents",
    response_model=KnowledgeDeleteResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def delete_knowledge_document(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
    source_name: str = Query(..., description="Document source name"),
    source_url: str | None = Query(default=None, description="Document source URL"),
) -> KnowledgeDeleteResponse:
    """Delete (soft) a knowledge document and all its chunks.

    Only user-owned chunks can be deleted. Shared system chunks
    cannot be deleted via this endpoint.
    """
    from src.services.knowledge_manager import delete_document

    count = await delete_document(db, current_user.id, source_name, source_url)

    if count == 0:
        raise HTTPException(
            status_code=404,
            detail="No deletable chunks found. System-shared knowledge cannot be deleted.",
        )

    return KnowledgeDeleteResponse(
        message=f"Document '{source_name}' deleted",
        chunks_invalidated=count,
    )


@router.get(
    "/stats",
    response_model=KnowledgeStatsResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def get_stats(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeStatsResponse:
    """Get aggregate knowledge base statistics."""
    from src.services.knowledge_manager import get_knowledge_stats

    return await get_knowledge_stats(db, current_user.id)
