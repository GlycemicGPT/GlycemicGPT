"""Tests for security audit logging service (Story 28.7)."""

import uuid
from unittest.mock import AsyncMock

import pytest

from src.services.audit_service import log_event


class TestAuditService:
    """Tests for the audit log_event function."""

    @pytest.mark.asyncio
    async def test_log_event_inserts_entry(self):
        """log_event adds a SecurityAuditLog to the session."""
        mock_db = AsyncMock()
        user_id = uuid.uuid4()

        await log_event(
            mock_db,
            event_type="api_key.created",
            user_id=user_id,
            detail={"key_prefix": "ggpt_abc"},
            ip_address="10.0.0.1",
        )

        # Should have called db.add() and db.flush()
        assert mock_db.add.called
        entry = mock_db.add.call_args[0][0]
        assert entry.event_type == "api_key.created"
        assert entry.user_id == user_id
        assert "ggpt_abc" in entry.detail
        assert entry.ip_address == "10.0.0.1"
        assert mock_db.flush.called

    @pytest.mark.asyncio
    async def test_log_event_with_null_user(self):
        """log_event works with user_id=None (anonymous events)."""
        mock_db = AsyncMock()

        await log_event(
            mock_db,
            event_type="auth.failed",
            ip_address="192.168.1.1",
        )

        entry = mock_db.add.call_args[0][0]
        assert entry.user_id is None
        assert entry.event_type == "auth.failed"

    @pytest.mark.asyncio
    async def test_log_event_with_null_detail(self):
        """log_event works with detail=None."""
        mock_db = AsyncMock()

        await log_event(
            mock_db,
            event_type="device.registered",
            user_id=uuid.uuid4(),
        )

        entry = mock_db.add.call_args[0][0]
        assert entry.detail is None

    @pytest.mark.asyncio
    async def test_log_event_swallows_exceptions(self):
        """log_event never raises, even if the DB operation fails."""
        mock_db = AsyncMock()
        mock_db.flush.side_effect = RuntimeError("DB down")

        # Should not raise
        await log_event(
            mock_db,
            event_type="api_key.created",
            user_id=uuid.uuid4(),
        )
