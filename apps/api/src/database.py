"""Database connection and session management.

Uses lazy initialization to ensure the engine is created within
the correct event loop context, avoiding asyncpg event loop issues.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from src.config import settings
from src.logging_config import get_logger

logger = get_logger(__name__)

# Engine and session maker - lazily initialized
_engine: AsyncEngine | None = None
_async_session_maker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Get or create the database engine.

    Creates the engine lazily to ensure it's created within
    the correct event loop context.

    When testing=True, uses NullPool to avoid event loop issues
    with connection pooling across different test event loops.
    """
    global _engine
    if _engine is None:
        if settings.testing:
            # Use NullPool for testing to avoid event loop issues
            _engine = create_async_engine(
                settings.database_url,
                echo=settings.log_format == "text",
                poolclass=NullPool,
            )
        else:
            # Use connection pooling for production
            _engine = create_async_engine(
                settings.database_url,
                echo=settings.log_format == "text",
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
            )
    return _engine


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    """Get or create the session maker."""
    global _async_session_maker
    if _async_session_maker is None:
        _async_session_maker = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_maker


# Backwards compatible aliases
@property
def engine() -> AsyncEngine:
    """Backwards compatible engine access."""
    return get_engine()


@property
def async_session_maker() -> async_sessionmaker[AsyncSession]:
    """Backwards compatible session maker access."""
    return get_session_maker()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for getting database sessions."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


# Alias for backwards compatibility
get_session = get_db


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database sessions."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def check_database_connection() -> bool:
    """
    Check if the database is reachable.

    Returns:
        True if database is connected, False otherwise.
    """
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
            return True
    except Exception:
        logger.warning("Database health check failed", exc_info=True)
        return False


async def close_database() -> None:
    """Close the database engine and all connections."""
    global _engine, _async_session_maker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _async_session_maker = None


async def reset_database() -> None:
    """Reset the database engine for testing.

    This disposes the current engine and clears the references,
    allowing a new engine to be created in a different event loop.
    """
    await close_database()
