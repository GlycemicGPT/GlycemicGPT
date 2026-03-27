"""Story 35.10: Knowledge Base viewer schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class KnowledgeChunkResponse(BaseModel):
    """A single knowledge chunk for preview."""

    id: uuid.UUID
    content: str
    content_preview: str = Field(description="First 200 chars of content")
    content_length: int
    source_url: str | None
    retrieved_at: datetime | None
    created_at: datetime
    injection_risk: bool


class KnowledgeDocumentSummary(BaseModel):
    """A logical document (group of chunks from the same source)."""

    source_name: str
    source_url: str | None
    source_type: str
    trust_tier: str
    chunk_count: int
    total_content_length: int
    first_created: datetime
    last_updated: datetime | None
    injection_risk_count: int = 0
    update_source: str | None = None
    change_summary: str | None = None


class KnowledgeDocumentListResponse(BaseModel):
    """Paginated list of knowledge documents."""

    documents: list[KnowledgeDocumentSummary]
    total_documents: int
    total_chunks: int
    page: int = 1
    page_size: int = 20


class KnowledgeDocumentDetailResponse(BaseModel):
    """A document with its chunks."""

    source_name: str
    source_url: str | None
    source_type: str
    trust_tier: str
    chunk_count: int
    chunks: list[KnowledgeChunkResponse]
    total: int


class KnowledgeStatsResponse(BaseModel):
    """Aggregate knowledge base statistics."""

    total_documents: int
    total_chunks: int
    by_tier: dict[str, int] = Field(default_factory=dict)


class KnowledgeDeleteResponse(BaseModel):
    """Response after deleting a document."""

    message: str
    chunks_invalidated: int
