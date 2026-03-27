"""Story 35.12: Research source management API."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import DiabeticOrAdminUser
from src.database import get_db
from src.logging_config import get_logger
from src.middleware.rate_limit import limiter
from src.models.research_source import ResearchSource
from src.schemas.auth import ErrorResponse
from src.schemas.research import (
    ResearchRunResponse,
    ResearchSourceCreate,
    ResearchSourceListResponse,
    ResearchSourceResponse,
    SuggestedSource,
    SuggestionsResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/ai/research", tags=["ai-research"])

MAX_SOURCES_PER_USER = 10


@router.get(
    "/sources",
    response_model=ResearchSourceListResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def list_research_sources(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> ResearchSourceListResponse:
    """List the user's configured research sources."""
    result = await db.execute(
        select(ResearchSource)
        .where(ResearchSource.user_id == current_user.id)
        .order_by(ResearchSource.created_at.desc())
    )
    sources = list(result.scalars().all())
    return ResearchSourceListResponse(
        sources=[ResearchSourceResponse.model_validate(s) for s in sources],
        total=len(sources),
    )


@router.post(
    "/sources",
    response_model=ResearchSourceResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid URL or limit reached"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def add_research_source(
    request: ResearchSourceCreate,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> ResearchSourceResponse:
    """Add a new research source URL."""
    from sqlalchemy import func

    # Check source limit
    count_result = await db.execute(
        select(func.count()).where(ResearchSource.user_id == current_user.id)
    )
    if (count_result.scalar() or 0) >= MAX_SOURCES_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_SOURCES_PER_USER} research sources allowed",
        )

    # Check for duplicate URL
    existing = await db.execute(
        select(ResearchSource).where(
            ResearchSource.user_id == current_user.id,
            ResearchSource.url == request.url,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="This URL is already configured")

    # SSRF validation (use research-specific validator that always blocks private IPs)
    try:
        from src.services.research_pipeline import _validate_research_url

        _validate_research_url(request.url)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid URL. Research sources must use HTTPS and target public addresses.",
        ) from None

    source = ResearchSource(
        user_id=current_user.id,
        url=request.url,
        name=request.name,
        category=request.category,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    logger.info(
        "Research source added",
        user_id=str(current_user.id),
        url=request.url,
        name=request.name,
    )

    return ResearchSourceResponse.model_validate(source)


@router.delete(
    "/sources/{source_id}",
    responses={
        200: {"description": "Source deleted"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Source not found"},
    },
)
async def delete_research_source(
    source_id: uuid.UUID,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a research source and its associated knowledge chunks."""
    from sqlalchemy import delete

    from src.models.knowledge_chunk import KnowledgeChunk

    result = await db.execute(
        select(ResearchSource).where(
            ResearchSource.id == source_id,
            ResearchSource.user_id == current_user.id,
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Research source not found")

    # Delete associated knowledge chunks
    chunks_result = await db.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.user_id == current_user.id,
            KnowledgeChunk.source_url == source.url,
        )
    )
    chunks_deleted = chunks_result.rowcount

    await db.delete(source)
    await db.commit()

    logger.info(
        "Research source deleted",
        user_id=str(current_user.id),
        source_id=str(source_id),
        chunks_deleted=chunks_deleted,
    )

    return {"message": "Research source deleted", "chunks_deleted": chunks_deleted}


@router.post(
    "/run",
    response_model=ResearchRunResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        429: {"model": ErrorResponse, "description": "Rate limited"},
    },
)
@limiter.limit("2/hour")
async def trigger_research(
    request: Request,
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> ResearchRunResponse:
    """Manually trigger the AI research pipeline for the current user.

    The AI evaluates sources, follows links within allowed domains,
    and produces structured clinical knowledge. Rate limited to 2/hour.
    """
    from src.schemas.research import SourceRecommendation
    from src.services.ai_researcher import ai_research_for_user

    result = await ai_research_for_user(db, current_user.id)
    recs = [
        SourceRecommendation(
            domain=r.get("domain", ""),
            url=r.get("url", ""),
            reason=r.get("reason", ""),
        )
        for r in result.get("recommendations", [])
        if r.get("domain") and r.get("url")
    ]
    return ResearchRunResponse(
        sources=result.get("sources", 0),
        updated=result.get("updated", 0),
        new=result.get("new", 0),
        unchanged=result.get("unchanged", 0),
        errors=result.get("errors", 0),
        recommendations=recs,
    )


@router.get(
    "/suggestions",
    response_model=SuggestionsResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def get_suggestions(
    current_user: DiabeticOrAdminUser,
    db: AsyncSession = Depends(get_db),
) -> SuggestionsResponse:
    """Get suggested research sources based on user's device/insulin config."""
    from src.services.research_pipeline import get_suggested_sources

    suggestions = await get_suggested_sources(db, current_user.id)

    # Build the "based_on" context
    from src.models.insulin_config import InsulinConfig
    from src.models.integration import IntegrationCredential, IntegrationType
    from src.models.pump_hardware_info import PumpHardwareInfo

    based_on: dict[str, str] = {}

    insulin_result = await db.execute(
        select(InsulinConfig).where(InsulinConfig.user_id == current_user.id)
    )
    insulin = insulin_result.scalar_one_or_none()
    if insulin:
        based_on["insulin"] = insulin.insulin_type

    pump_result = await db.execute(
        select(PumpHardwareInfo).where(PumpHardwareInfo.user_id == current_user.id)
    )
    if pump_result.scalar_one_or_none():
        based_on["pump"] = "tandem"

    int_result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user.id,
            IntegrationCredential.integration_type == IntegrationType.DEXCOM,
        )
    )
    if int_result.scalar_one_or_none():
        based_on["cgm"] = "dexcom"

    return SuggestionsResponse(
        suggestions=[SuggestedSource(**s) for s in suggestions],
        based_on=based_on,
    )
