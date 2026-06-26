"""Pytest configuration and shared fixtures.

Properly configures async testing with SQLAlchemy to avoid event loop issues.
"""

import asyncio
import hashlib
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
# Keep external nutrition-grounding lookups (Story 50.E1) off the network by
# default; the grounding tests enable/patch them explicitly where needed.
settings.open_food_facts_enabled = False
settings.usda_fdc_api_key = ""

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


@pytest.fixture(autouse=True)
def _fake_embedding_model(monkeypatch):
    """Replace the heavy fastembed model with a deterministic stub.

    The embedding model is ~500 MB and downloads on first use; keeping it out of
    the test run avoids a network dependency in CI. The stub is deterministic --
    identical text yields an identical unit vector (cosine distance 0) and
    different text yields a near-orthogonal one -- so own-history meal recall
    (Story 50.E1) is testable without the real model. Tests that patch
    ``embed_text`` directly are unaffected: they replace the imported symbol,
    not this model factory.
    """
    import numpy as np

    from src.services import embedding

    class _FakeEmbeddingModel:
        def embed(self, texts):
            for text in texts:
                seed = int.from_bytes(
                    hashlib.sha256(text.encode("utf-8")).digest()[:8], "big"
                )
                vec = np.random.default_rng(seed).standard_normal(
                    embedding.EMBEDDING_DIM
                )
                norm = np.linalg.norm(vec)
                yield vec / norm if norm else vec

    monkeypatch.setattr(embedding, "_get_model", lambda: _FakeEmbeddingModel())


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP client for testing the API."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
