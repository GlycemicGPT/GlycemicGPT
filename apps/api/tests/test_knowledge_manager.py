"""Story 35.10: Tests for Knowledge Base management service."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.knowledge_manager import (
    delete_document,
    get_document_chunks,
    get_knowledge_stats,
    list_documents,
)


class TestListDocuments:
    """Tests for document listing with grouping."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_chunks(self):
        db = AsyncMock()

        # The function executes 3 queries: grouped docs, total doc count, total chunk count
        # Order: 1) grouped results, 2) total doc count, 3) total chunk count
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.all.return_value = []
        db.execute.return_value = mock_result

        docs, total_docs, total_chunks = await list_documents(db, uuid.uuid4())
        assert docs == []
        assert total_docs == 0
        assert total_chunks == 0


class TestGetDocumentChunks:
    """Tests for getting chunks for a specific document."""

    @pytest.mark.asyncio
    async def test_returns_chunks_for_document(self):
        db = AsyncMock()

        # Count query
        count_result = MagicMock()
        count_result.scalar.return_value = 2

        # Chunks query
        chunk1 = MagicMock()
        chunk1.id = uuid.uuid4()
        chunk1.content = "This is chunk 1 content about insulin."
        chunk1.source_url = "https://example.com"
        chunk1.retrieved_at = datetime.now(UTC)
        chunk1.created_at = datetime.now(UTC)
        chunk1.injection_risk = False

        chunk2 = MagicMock()
        chunk2.id = uuid.uuid4()
        chunk2.content = "This is chunk 2 content about dosing."
        chunk2.source_url = "https://example.com"
        chunk2.retrieved_at = datetime.now(UTC)
        chunk2.created_at = datetime.now(UTC)
        chunk2.injection_risk = False

        chunks_result = MagicMock()
        chunks_result.scalars.return_value.all.return_value = [chunk1, chunk2]

        db.execute.side_effect = [count_result, chunks_result]

        chunks, total = await get_document_chunks(
            db, uuid.uuid4(), "Test Document", "https://example.com"
        )
        assert total == 2
        assert len(chunks) == 2
        assert chunks[0].content == "This is chunk 1 content about insulin."
        assert chunks[1].content_length == len("This is chunk 2 content about dosing.")

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_chunks(self):
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        chunks_result = MagicMock()
        chunks_result.scalars.return_value.all.return_value = []

        db.execute.side_effect = [count_result, chunks_result]

        chunks, total = await get_document_chunks(db, uuid.uuid4(), "Missing Document")
        assert total == 0
        assert chunks == []


class TestDeleteDocument:
    """Tests for soft-deleting documents."""

    @pytest.mark.asyncio
    async def test_soft_deletes_user_owned_chunks(self):
        db = AsyncMock()

        # Bulk UPDATE returns rowcount
        result = MagicMock()
        result.rowcount = 2
        db.execute.return_value = result

        count = await delete_document(
            db, uuid.uuid4(), "My Document", "https://example.com"
        )
        assert count == 2
        db.execute.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_chunks_found(self):
        db = AsyncMock()
        result = MagicMock()
        result.rowcount = 0
        db.execute.return_value = result

        count = await delete_document(db, uuid.uuid4(), "No Such Document")
        assert count == 0
        db.commit.assert_not_called()  # No commit on empty result


class TestGetKnowledgeStats:
    """Tests for knowledge base statistics."""

    @pytest.mark.asyncio
    async def test_returns_stats(self):
        db = AsyncMock()

        # Total chunks
        total_result = MagicMock()
        total_result.scalar.return_value = 15

        # By tier
        tier_result = MagicMock()
        tier_result.all.return_value = [("RESEARCHED", 10), ("CURATED", 5)]

        # Document count
        doc_result = MagicMock()
        doc_result.scalar.return_value = 3

        db.execute.side_effect = [total_result, tier_result, doc_result]

        stats = await get_knowledge_stats(db, uuid.uuid4())
        assert stats.total_chunks == 15
        assert stats.total_documents == 3
        assert stats.by_tier == {"RESEARCHED": 10, "CURATED": 5}

    @pytest.mark.asyncio
    async def test_returns_empty_stats(self):
        db = AsyncMock()

        total_result = MagicMock()
        total_result.scalar.return_value = 0
        tier_result = MagicMock()
        tier_result.all.return_value = []
        doc_result = MagicMock()
        doc_result.scalar.return_value = 0

        db.execute.side_effect = [total_result, tier_result, doc_result]

        stats = await get_knowledge_stats(db, uuid.uuid4())
        assert stats.total_chunks == 0
        assert stats.total_documents == 0
        assert stats.by_tier == {}
