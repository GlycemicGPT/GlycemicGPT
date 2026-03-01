"""Tests for ScopeChecker (Story 28.7).

Verifies scope enforcement for API key vs JWT authentication.
"""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.core.auth import ScopeChecker


def _mock_request(api_key_scopes=None):
    """Create a mock request with optional API key scopes."""
    request = MagicMock()
    if api_key_scopes is not None:
        request.state._api_key_scopes = set(api_key_scopes)
    else:
        # Simulate JWT auth (no _api_key_scopes attribute)
        del request.state._api_key_scopes
    return request


def _mock_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    return user


class TestScopeChecker:
    """Tests for the ScopeChecker dependency."""

    @pytest.mark.asyncio
    async def test_jwt_auth_grants_all_scopes(self):
        """JWT/cookie auth bypasses scope checks (first-party)."""
        checker = ScopeChecker(["read:glucose", "read:pump", "read:alerts"])
        request = _mock_request(api_key_scopes=None)
        user = _mock_user()
        result = await checker(request, user)
        assert result is True

    @pytest.mark.asyncio
    async def test_api_key_with_matching_scopes(self):
        """API key with all required scopes passes."""
        checker = ScopeChecker(["read:glucose"])
        request = _mock_request(api_key_scopes=["read:glucose", "read:pump"])
        user = _mock_user()
        result = await checker(request, user)
        assert result is True

    @pytest.mark.asyncio
    async def test_api_key_missing_scope_raises_403(self):
        """API key missing a required scope gets 403."""
        checker = ScopeChecker(["read:alerts"])
        request = _mock_request(api_key_scopes=["read:glucose"])
        user = _mock_user()

        with pytest.raises(HTTPException) as exc_info:
            await checker(request, user)
        assert exc_info.value.status_code == 403
        assert "read:alerts" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_api_key_missing_multiple_scopes(self):
        """Error message lists all missing scopes."""
        checker = ScopeChecker(["read:alerts", "read:pump"])
        request = _mock_request(api_key_scopes=["read:glucose"])
        user = _mock_user()

        with pytest.raises(HTTPException) as exc_info:
            await checker(request, user)
        assert exc_info.value.status_code == 403
        assert "read:alerts" in exc_info.value.detail
        assert "read:pump" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_api_key_exact_scopes_match(self):
        """API key with exactly the required scopes passes."""
        checker = ScopeChecker(["read:glucose"])
        request = _mock_request(api_key_scopes=["read:glucose"])
        user = _mock_user()
        result = await checker(request, user)
        assert result is True
