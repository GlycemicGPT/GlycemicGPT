"""Story 35.3: Chat history service for conversation memory.

Manages conversation threads and message persistence so the AI receives
multi-turn context with every chat request.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.chat_message import ChatMessage, ChatRole
from src.schemas.ai_response import AIMessage

logger = get_logger(__name__)

# A new conversation starts after this many minutes of inactivity
CONVERSATION_INACTIVITY_MINUTES = 30

# Maximum number of turns (user+assistant pairs) to include as context
MAX_HISTORY_TURNS = 10

# Maximum total messages to load (2 per turn)
MAX_HISTORY_MESSAGES = MAX_HISTORY_TURNS * 2

# Approximate token budget for history context (~4 chars per token).
# Reserves headroom for system prompt (~2K) + diabetes context (~2K) + current message.
# Conservative: 12K tokens of history out of typical 128K context window.
MAX_HISTORY_TOKEN_BUDGET = 12000
CHARS_PER_TOKEN_ESTIMATE = 4


async def get_or_create_conversation(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> uuid.UUID:
    """Get the active conversation ID or create a new one.

    A conversation is "active" if the most recent message from this user
    is within the inactivity threshold. Otherwise, a new conversation_id
    is generated.

    Args:
        db: Database session.
        user_id: User's UUID.

    Returns:
        The active or newly created conversation UUID.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=CONVERSATION_INACTIVITY_MINUTES)

    result = await db.execute(
        select(ChatMessage.conversation_id, ChatMessage.created_at)
        .where(ChatMessage.user_id == user_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    row = result.first()

    if row is not None:
        conv_id, last_time = row
        # Ensure last_time is timezone-aware for comparison
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=UTC)
        if last_time >= cutoff:
            return conv_id

    return uuid.uuid4()


async def store_message(
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    role: ChatRole,
    content: str,
    token_count: int | None = None,
    model: str | None = None,
) -> ChatMessage:
    """Store a chat message.

    Args:
        db: Database session.
        user_id: User's UUID.
        conversation_id: Conversation UUID.
        role: Message role (user or assistant).
        content: Message text.
        token_count: Optional token count for this message.
        model: Optional AI model name (for assistant messages).

    Returns:
        The created ChatMessage record.
    """
    message = ChatMessage(
        user_id=user_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        token_count=token_count,
        model=model,
    )
    db.add(message)
    await db.flush()

    logger.debug(
        "Chat message stored",
        user_id=str(user_id),
        conversation_id=str(conversation_id),
        role=role.value,
        token_count=token_count,
    )

    return message


async def get_recent_messages(
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    max_messages: int = MAX_HISTORY_MESSAGES,
) -> list[AIMessage]:
    """Load recent messages from a conversation for AI context.

    Returns messages in chronological order (oldest first) so they can
    be passed directly to the AI client's messages array.

    Args:
        db: Database session.
        user_id: User's UUID.
        conversation_id: Conversation UUID.
        max_messages: Maximum messages to return.

    Returns:
        List of AIMessage objects in chronological order.
    """
    result = await db.execute(
        select(ChatMessage.role, ChatMessage.content)
        .where(
            ChatMessage.user_id == user_id,
            ChatMessage.conversation_id == conversation_id,
        )
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(max_messages)
    )
    rows = result.all()

    # Reverse to chronological order (oldest first)
    rows.reverse()

    # Trim oldest messages if total exceeds token budget
    messages = [AIMessage(role=row[0].value, content=row[1]) for row in rows]
    total_chars = sum(len(m.content) for m in messages)
    budget_chars = MAX_HISTORY_TOKEN_BUDGET * CHARS_PER_TOKEN_ESTIMATE

    while messages and total_chars > budget_chars:
        removed = messages.pop(0)
        total_chars -= len(removed.content)

    return messages


async def get_conversation_messages(
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ChatMessage], int]:
    """Get all messages in a conversation for API response.

    Returns full ChatMessage objects (with IDs, timestamps, etc.)
    for the history endpoint.

    Args:
        db: Database session.
        user_id: User's UUID.
        conversation_id: Conversation UUID.
        limit: Maximum messages to return.
        offset: Number of messages to skip.

    Returns:
        Tuple of (messages list, total count).
    """
    from sqlalchemy import func

    count_result = await db.execute(
        select(func.count()).where(
            ChatMessage.user_id == user_id,
            ChatMessage.conversation_id == conversation_id,
        )
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.user_id == user_id,
            ChatMessage.conversation_id == conversation_id,
        )
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .limit(limit)
        .offset(offset)
    )
    messages = list(result.scalars().all())

    return messages, total


async def clear_conversation(
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None = None,
) -> int:
    """Clear chat history for a user.

    If conversation_id is provided, clears only that conversation.
    Otherwise, clears all conversations for the user.

    Args:
        db: Database session.
        user_id: User's UUID.
        conversation_id: Optional specific conversation to clear.

    Returns:
        Number of messages deleted.
    """
    conditions = [ChatMessage.user_id == user_id]
    if conversation_id is not None:
        conditions.append(ChatMessage.conversation_id == conversation_id)

    result = await db.execute(delete(ChatMessage).where(*conditions))
    deleted = result.rowcount

    logger.info(
        "Chat history cleared",
        user_id=str(user_id),
        conversation_id=str(conversation_id) if conversation_id else "all",
        deleted=deleted,
    )

    return deleted
