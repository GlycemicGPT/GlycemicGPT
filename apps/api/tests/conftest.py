"""Pytest configuration and shared fixtures.

Properly configures async testing with SQLAlchemy to avoid event loop issues.
"""

import asyncio
import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# Set testing mode BEFORE importing app to use NullPool
os.environ["TESTING"] = "true"

from src.config import settings

# Override settings for testing
settings.testing = True
# Provide a sufficiently long secret_key for tests (generated at runtime)
settings.secret_key = "t" * 32  # noqa: S105  -- test-only, not a real secret

from src.database import get_engine, get_session_maker, reset_database
from src.main import app


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop.

    This ensures all tests share the same event loop, which is required
    for SQLAlchemy's asyncpg connection pool to work correctly.
    """
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """Session-scoped database engine fixture.

    Disposes the connection pool after all tests complete.
    """
    engine = get_engine()
    yield engine
    await reset_database()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session for each test.

    Each test gets its own session that is rolled back after the test.
    """
    session_maker = get_session_maker()
    async with session_maker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP client for testing the API."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
