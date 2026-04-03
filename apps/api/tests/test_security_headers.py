"""Tests for security response headers middleware.

Verifies that all responses include the expected security headers
(X-Content-Type-Options, X-Frame-Options, etc.).
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


def assert_security_headers(response):
    """Assert all expected security headers are present on a response."""
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-XSS-Protection"] == "0"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert (
        response.headers["Permissions-Policy"]
        == "camera=(), microphone=(), geolocation=()"
    )


class TestSecurityHeaders:
    """Verify security headers are present on responses."""

    @pytest.mark.asyncio
    async def test_health_endpoint_has_security_headers(self, client):
        """Security headers appear on health endpoint responses."""
        with patch(
            "src.routers.health.check_database_connection", new_callable=AsyncMock
        ) as mock_db:
            mock_db.return_value = True
            response = await client.get("/health")

        assert response.status_code == 200
        assert_security_headers(response)

    @pytest.mark.asyncio
    async def test_root_endpoint_has_security_headers(self, client):
        """Security headers appear on the root endpoint."""
        response = await client.get("/")

        assert response.status_code == 200
        assert_security_headers(response)

    @pytest.mark.asyncio
    async def test_404_response_has_security_headers(self, client):
        """Security headers appear on 404 (not found) responses."""
        response = await client.get("/nonexistent-path-that-does-not-exist")

        assert response.status_code == 404
        assert_security_headers(response)

    @pytest.mark.asyncio
    async def test_auth_failure_has_security_headers(self, client):
        """Security headers appear on 401 (unauthorized) responses."""
        response = await client.get("/api/settings/alert-thresholds")

        assert response.status_code == 401
        assert_security_headers(response)

    @pytest.mark.asyncio
    async def test_no_hsts_header(self, client):
        """HSTS is NOT set by the API -- it belongs on the reverse proxy."""
        response = await client.get("/")

        assert "Strict-Transport-Security" not in response.headers
