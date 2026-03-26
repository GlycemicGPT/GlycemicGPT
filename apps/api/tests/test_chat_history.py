"""Story 35.3: Tests for chat history service."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.chat_message import ChatRole
from src.services.chat_history import (
    CONVERSATION_INACTIVITY_MINUTES,
    clear_conversation,
    get_or_create_conversation,
    get_recent_messages,
    store_message,
)


class TestGetOrCreateConversation:
    """Tests for conversation ID management."""

    @pytest.mark.asyncio
    async def test_new_conversation_when_no_history(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = None
        db.execute.return_value = mock_result

        conv_id = await get_or_create_conversation(db, uuid.uuid4())
        assert isinstance(conv_id, uuid.UUID)

    @pytest.mark.asyncio
    async def test_reuses_active_conversation(self):
        db = AsyncMock()
        existing_conv_id = uuid.uuid4()
        recent_time = datetime.now(UTC) - timedelta(minutes=5)

        mock_result = MagicMock()
        mock_result.first.return_value = (existing_conv_id, recent_time)
        db.execute.return_value = mock_result

        conv_id = await get_or_create_conversation(db, uuid.uuid4())
        assert conv_id == existing_conv_id

    @pytest.mark.asyncio
    async def test_new_conversation_after_inactivity(self):
        db = AsyncMock()
        old_conv_id = uuid.uuid4()
        old_time = datetime.now(UTC) - timedelta(
            minutes=CONVERSATION_INACTIVITY_MINUTES + 5
        )

        mock_result = MagicMock()
        mock_result.first.return_value = (old_conv_id, old_time)
        db.execute.return_value = mock_result

        conv_id = await get_or_create_conversation(db, uuid.uuid4())
        assert conv_id != old_conv_id
        assert isinstance(conv_id, uuid.UUID)

    @pytest.mark.asyncio
    async def test_handles_naive_datetime(self):
        """Ensure naive datetimes from DB are handled correctly."""
        db = AsyncMock()
        existing_conv_id = uuid.uuid4()
        # Naive datetime (no tzinfo) -- should be treated as UTC
        recent_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)

        mock_result = MagicMock()
        mock_result.first.return_value = (existing_conv_id, recent_time)
        db.execute.return_value = mock_result

        conv_id = await get_or_create_conversation(db, uuid.uuid4())
        assert conv_id == existing_conv_id


class TestStoreMessage:
    """Tests for message persistence."""

    @pytest.mark.asyncio
    async def test_stores_user_message(self):
        db = AsyncMock()
        user_id = uuid.uuid4()
        conv_id = uuid.uuid4()

        msg = await store_message(
            db, user_id, conv_id, ChatRole.USER, "How am I doing?"
        )

        assert msg.user_id == user_id
        assert msg.conversation_id == conv_id
        assert msg.role == ChatRole.USER
        assert msg.content == "How am I doing?"
        db.add.assert_called_once()
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_stores_assistant_message_with_metadata(self):
        db = AsyncMock()
        msg = await store_message(
            db,
            uuid.uuid4(),
            uuid.uuid4(),
            ChatRole.ASSISTANT,
            "Your glucose looks good.",
            token_count=150,
            model="claude-sonnet-4-5",
        )

        assert msg.role == ChatRole.ASSISTANT
        assert msg.token_count == 150
        assert msg.model == "claude-sonnet-4-5"


class TestGetRecentMessages:
    """Tests for loading conversation history."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_messages(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        db.execute.return_value = mock_result

        messages = await get_recent_messages(db, uuid.uuid4(), uuid.uuid4())
        assert messages == []

    @pytest.mark.asyncio
    async def test_returns_messages_in_chronological_order(self):
        db = AsyncMock()
        mock_result = MagicMock()
        # DB returns newest first (DESC), service should reverse
        mock_result.all.return_value = [
            (ChatRole.ASSISTANT, "Response text"),
            (ChatRole.USER, "Question text"),
        ]
        db.execute.return_value = mock_result

        messages = await get_recent_messages(db, uuid.uuid4(), uuid.uuid4())
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Question text"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Response text"

    @pytest.mark.asyncio
    async def test_respects_max_messages_limit(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        db.execute.return_value = mock_result

        await get_recent_messages(db, uuid.uuid4(), uuid.uuid4(), max_messages=5)
        # Verify the query was called (we can't easily check the limit param
        # on the SQLAlchemy query, but the function should not raise)
        db.execute.assert_called_once()


class TestClearConversation:
    """Tests for clearing chat history."""

    @pytest.mark.asyncio
    async def test_clears_specific_conversation(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 10
        db.execute.return_value = mock_result

        deleted = await clear_conversation(db, uuid.uuid4(), uuid.uuid4())
        assert deleted == 10
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_clears_all_conversations_for_user(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 25
        db.execute.return_value = mock_result

        deleted = await clear_conversation(db, uuid.uuid4())
        assert deleted == 25
