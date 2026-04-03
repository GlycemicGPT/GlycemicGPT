"""Tests for health check endpoints.

Story 1.2: Database Migrations & Health Endpoint
- AC2: GET /health returns {"status": "healthy", "database": "connected"}
- AC3: Health endpoint compatible with Kubernetes liveness/readiness probes
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.fixture
async def client():
    """Create async test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    @pytest.mark.asyncio
    async def test_returns_healthy_with_db_connected(self, client):
        """
        AC2: GET /health returns {"status": "healthy", "database": "connected"}
        when database is available.
        """
        with patch(
            "src.routers.health.check_database_connection", new_callable=AsyncMock
        ) as mock_db:
            mock_db.return_value = True

            response = await client.get("/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["database"] == "connected"

    @pytest.mark.asyncio
    async def test_returns_degraded_when_db_disconnected(self, client):
        """
        Health endpoint returns 503 with degraded status when database
        is unavailable.
        """
        with patch(
            "src.routers.health.check_database_connection", new_callable=AsyncMock
        ) as mock_db:
            mock_db.return_value = False

            response = await client.get("/health")

            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "degraded"
            assert data["database"] == "disconnected"


class TestLivenessProbe:
    """Tests for /health/live endpoint (Kubernetes liveness probe)."""

    @pytest.mark.asyncio
    async def test_returns_alive(self, client):
        """
        AC3: Liveness probe returns alive status.

        Liveness should NOT check external dependencies like databases.
        If this fails, Kubernetes will restart the container.
        """
        response = await client.get("/health/live")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"


class TestReadinessProbe:
    """Tests for /health/ready endpoint (Kubernetes readiness probe)."""

    @pytest.mark.asyncio
    async def test_returns_ready_with_db_connected(self, client):
        """
        AC3: Readiness probe returns ready when database is connected.

        If this passes, Kubernetes will route traffic to this pod.
        """
        with patch(
            "src.routers.health.check_database_connection", new_callable=AsyncMock
        ) as mock_db:
            mock_db.return_value = True

            response = await client.get("/health/ready")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"
            assert data["database"] == "connected"

    @pytest.mark.asyncio
    async def test_returns_not_ready_when_db_disconnected(self, client):
        """
        Readiness probe returns 503 when database is unavailable.

        If this fails, Kubernetes will stop routing traffic to this pod.
        """
        with patch(
            "src.routers.health.check_database_connection", new_callable=AsyncMock
        ) as mock_db:
            mock_db.return_value = False

            response = await client.get("/health/ready")

            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "not_ready"
            assert data["database"] == "disconnected"


class TestRootEndpoint:
    """Tests for root endpoint."""

    @pytest.mark.asyncio
    async def test_returns_api_info(self, client):
        """Root endpoint returns API information."""
        response = await client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "GlycemicGPT API"
        assert (
            "version" not in data
        )  # Story 28.10: version removed to prevent info disclosure
        assert data["docs"] == "/docs"
