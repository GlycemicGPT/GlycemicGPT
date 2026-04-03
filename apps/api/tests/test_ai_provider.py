"""Story 5.1 / 14.4: Tests for AI provider configuration."""

import uuid
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.core.encryption import decrypt_credential, encrypt_credential
from src.main import app
from src.services.ai_provider import mask_api_key


def unique_email(prefix: str = "test") -> str:
    """Generate a unique email for testing.

    Args:
        prefix: Email prefix before the UUID segment.

    Returns:
        A unique email address string.
    """
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def register_and_login(client: AsyncClient) -> str:
    """Register a new user and return the session cookie value.

    Args:
        client: The async HTTP test client.

    Returns:
        JWT session cookie string for authenticating subsequent requests.
    """
    email = unique_email("ai_provider")
    password = "SecurePass123"

    await client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )

    login_response = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )

    return login_response.cookies.get(settings.jwt_cookie_name)


class TestAIProviderConfiguration:
    """Tests for AI provider configuration endpoints."""

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_configure_claude_provider(self, mock_validate):
        """Test configuring Claude API as AI provider with valid key."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_api",
                    "api_key": "sk-ant-test-valid-key-1234",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["provider_type"] == "claude_api"
        assert data["status"] == "connected"
        assert "...1234" in data["masked_api_key"]
        assert data["last_validated_at"] is not None

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_configure_openai_provider(self, mock_validate):
        """Test configuring OpenAI API as AI provider with valid key."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "openai_api",
                    "api_key": "sk-openai-test-valid-key-5678",
                    "model_name": "gpt-4o",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["provider_type"] == "openai_api"
        assert data["status"] == "connected"
        assert data["model_name"] == "gpt-4o"
        assert "...5678" in data["masked_api_key"]

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_reject_invalid_api_key(self, mock_validate):
        """Test that invalid API keys are rejected."""
        mock_validate.return_value = (
            False,
            "Invalid Claude API key. Please check your key and try again.",
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_api",
                    "api_key": "invalid-key",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid Claude API key" in data["detail"]

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_get_provider_config(self, mock_validate):
        """Test getting current provider config returns masked key."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            # Configure provider first
            await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_api",
                    "api_key": "sk-ant-test-key-for-get-abcd",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Get the config
            response = await client.get(
                "/api/ai/provider",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["provider_type"] == "claude_api"
        assert data["status"] == "connected"
        # Key should be masked
        assert "abcd" in data["masked_api_key"]
        assert "sk-ant-test-key-for-get-abcd" not in data["masked_api_key"]

    async def test_get_provider_not_configured(self):
        """Test getting provider config when none configured returns 404."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.get(
                "/api/ai/provider",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 404
        assert "No AI provider configured" in response.json()["detail"]

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_delete_provider_config(self, mock_validate):
        """Test deleting AI provider configuration."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            # Configure provider first
            await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_api",
                    "api_key": "sk-ant-test-key-delete",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Delete it
            response = await client.delete(
                "/api/ai/provider",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        assert "removed successfully" in response.json()["message"]

    async def test_delete_provider_not_configured(self):
        """Test deleting when no provider configured returns 404."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.delete(
                "/api/ai/provider",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 404

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_update_existing_provider(self, mock_validate):
        """Test updating an existing provider configuration."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            # Configure Claude API first
            await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_api",
                    "api_key": "sk-ant-original-key-1111",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Update to OpenAI API
            response = await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "openai_api",
                    "api_key": "sk-openai-new-key-2222",
                    "model_name": "gpt-4o",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["provider_type"] == "openai_api"
        assert data["model_name"] == "gpt-4o"
        assert "...2222" in data["masked_api_key"]

    async def test_configure_requires_auth(self):
        """Test that all AI provider endpoints require authentication."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # POST
            response = await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_api",
                    "api_key": "sk-test",
                },
            )
            assert response.status_code == 401

            # GET
            response = await client.get("/api/ai/provider")
            assert response.status_code == 401

            # DELETE
            response = await client.delete("/api/ai/provider")
            assert response.status_code == 401

            # POST test
            response = await client.post("/api/ai/provider/test")
            assert response.status_code == 401

            # POST subscription configure
            response = await client.post(
                "/api/ai/subscription/configure",
                json={"sidecar_provider": "claude"},
            )
            assert response.status_code == 401

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_test_endpoint_success(self, mock_validate):
        """Test the /provider/test endpoint when key is valid."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            # Configure provider first
            await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_api",
                    "api_key": "sk-ant-test-success-9999",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Test the stored key
            response = await client.post(
                "/api/ai/provider/test",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "successfully" in data["message"]

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_test_endpoint_failure(self, mock_validate):
        """Test the /provider/test endpoint when key validation fails."""
        # validate_ai_api_key is called twice: once during POST /provider (succeeds)
        # and once during POST /provider/test (fails), simulating a revoked key.
        mock_validate.side_effect = [
            (True, None),
            (False, "Invalid Claude API key. Please check your key and try again."),
        ]

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            # Configure provider first (succeeds)
            await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_api",
                    "api_key": "sk-ant-test-will-fail-0000",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Test the stored key (fails)
            response = await client.post(
                "/api/ai/provider/test",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Invalid Claude API key" in data["message"]

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_configure_claude_subscription(self, mock_validate):
        """Test configuring Claude subscription provider with base_url."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_subscription",
                    "api_key": "not-needed",
                    "base_url": "http://localhost:3456/v1",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["provider_type"] == "claude_subscription"
        assert data["status"] == "connected"
        assert data["base_url"] == "http://localhost:3456/v1"

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_configure_openai_compatible(self, mock_validate):
        """Test configuring self-hosted OpenAI-compatible provider."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "openai_compatible",
                    "api_key": "not-needed",
                    "base_url": "http://localhost:11434/v1",
                    "model_name": "llama3.1:70b",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["provider_type"] == "openai_compatible"
        assert data["status"] == "connected"
        assert data["base_url"] == "http://localhost:11434/v1"
        assert data["model_name"] == "llama3.1:70b"

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_subscription_does_not_require_base_url(self, mock_validate):
        """Test that subscription providers no longer require base_url (sidecar handles routing)."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_subscription",
                    "api_key": "not-needed",
                    # No base_url needed -- sidecar handles routing
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        # Should succeed (201) since subscription providers no longer require base_url
        assert response.status_code == 201

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_openai_compatible_requires_model_name(self, mock_validate):
        """Test that openai_compatible provider requires model_name."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "openai_compatible",
                    "api_key": "not-needed",
                    "base_url": "http://localhost:11434/v1",
                    # Missing model_name
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 422

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_get_provider_returns_base_url(self, mock_validate):
        """Test that GET /provider returns base_url when configured."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            # Configure subscription provider with base_url
            # Use localhost (always resolvable) to avoid DNS issues in tests
            await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_subscription",
                    "api_key": "not-needed",
                    "base_url": "http://localhost:3456/v1",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Get the config
            response = await client.get(
                "/api/ai/provider",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["base_url"] == "http://localhost:3456/v1"
        assert data["provider_type"] == "claude_subscription"

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_configure_chatgpt_subscription(self, mock_validate):
        """Test configuring ChatGPT subscription provider."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "chatgpt_subscription",
                    "api_key": "not-needed",
                    "base_url": "http://localhost:8080/v1",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["provider_type"] == "chatgpt_subscription"
        assert data["base_url"] == "http://localhost:8080/v1"

    async def test_reject_legacy_claude_type(self):
        """Test that legacy 'claude' provider type is rejected."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude",
                    "api_key": "sk-ant-test-key",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 422

    async def test_reject_legacy_openai_type(self):
        """Test that legacy 'openai' provider type is rejected."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "openai",
                    "api_key": "sk-test-key",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 422

    async def test_reject_invalid_base_url_scheme(self):
        """Test that base_url with non-http scheme is rejected."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_subscription",
                    "api_key": "not-needed",
                    "base_url": "file:///etc/passwd",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 422

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_base_url_stripped_for_direct_api_types(self, mock_validate):
        """Test that base_url is stripped when configuring a direct API type."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_api",
                    "api_key": "sk-ant-test-strip-base-url",
                    "base_url": "http://should-be-stripped:1234/v1",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["base_url"] is None


class TestSidecarNullSafety:
    """Tests for null encrypted_api_key handling (sidecar-managed providers)."""

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_get_provider_with_null_api_key_returns_sidecar_managed(
        self, mock_validate
    ):
        """Test GET /provider returns 'sidecar-managed' when encrypted_api_key is NULL."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            # Configure a subscription provider (this sets encrypted_api_key)
            await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_subscription",
                    "api_key": "not-needed",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Now NULL out the encrypted_api_key to simulate sidecar OAuth
            from src.database import get_session_maker
            from src.models.ai_provider import AIProviderConfig

            session_maker = get_session_maker()
            async with session_maker() as db:
                from sqlalchemy import update

                await db.execute(
                    update(AIProviderConfig).values(encrypted_api_key=None)
                )
                await db.commit()

            # GET should return sidecar-managed instead of crashing
            response = await client.get(
                "/api/ai/provider",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["masked_api_key"] == "sidecar-managed"

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_test_provider_with_null_api_key_no_sidecar_returns_failure(
        self, mock_validate
    ):
        """Test POST /provider/test returns failure when key is NULL and no sidecar_provider set."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            # Configure a subscription provider
            await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_subscription",
                    "api_key": "not-needed",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # NULL out the encrypted_api_key WITHOUT setting sidecar_provider
            from src.database import get_session_maker
            from src.models.ai_provider import AIProviderConfig

            session_maker = get_session_maker()
            async with session_maker() as db:
                from sqlalchemy import update

                await db.execute(
                    update(AIProviderConfig).values(encrypted_api_key=None)
                )
                await db.commit()

            # Test endpoint should return failure (no key, no sidecar)
            response = await client.post(
                "/api/ai/provider/test",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "reconfigure" in data["message"].lower()

    @patch("src.routers.ai.validate_ai_api_key")
    async def test_update_provider_clears_sidecar_provider(self, mock_validate):
        """Test that reconfiguring a provider clears stale sidecar_provider."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            # Configure a subscription provider
            await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_subscription",
                    "api_key": "not-needed",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Simulate sidecar being active by setting sidecar_provider
            from src.database import get_session_maker
            from src.models.ai_provider import AIProviderConfig

            session_maker = get_session_maker()
            async with session_maker() as db:
                from sqlalchemy import update

                await db.execute(
                    update(AIProviderConfig).values(sidecar_provider="claude")
                )
                await db.commit()

            # Reconfigure to a direct API provider
            response = await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_api",
                    "api_key": "sk-ant-test-switch-provider-1234",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["provider_type"] == "claude_api"
        assert data["sidecar_provider"] is None

    @patch("src.routers.ai.revoke_sidecar_auth")
    @patch("src.routers.ai.validate_sidecar_connection")
    async def test_delete_sidecar_provider_revokes_auth(
        self, mock_validate, mock_revoke
    ):
        """Test that deleting a sidecar-managed provider calls revoke_sidecar_auth."""
        mock_validate.return_value = (True, None)
        mock_revoke.return_value = {"revoked": True, "provider": "claude"}

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            # Configure a subscription provider via sidecar
            await client.post(
                "/api/ai/subscription/configure",
                json={"sidecar_provider": "claude"},
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Delete it
            response = await client.delete(
                "/api/ai/provider",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        assert "removed successfully" in response.json()["message"]
        mock_revoke.assert_called_once_with("claude")

    @patch("src.routers.ai.revoke_sidecar_auth")
    @patch("src.routers.ai.validate_sidecar_connection")
    async def test_delete_sidecar_provider_succeeds_when_revoke_fails(
        self, mock_validate, mock_revoke
    ):
        """Test that delete succeeds even when sidecar revocation fails."""
        mock_validate.return_value = (True, None)
        mock_revoke.return_value = None  # Sidecar unreachable

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            # Configure a subscription provider via sidecar
            await client.post(
                "/api/ai/subscription/configure",
                json={"sidecar_provider": "claude"},
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Delete it (should still succeed)
            response = await client.delete(
                "/api/ai/provider",
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 200
        mock_revoke.assert_called_once_with("claude")


class TestSubscriptionConfigure:
    """Tests for POST /api/ai/subscription/configure endpoint (Story 15.4)."""

    @patch("src.routers.ai.validate_sidecar_connection")
    async def test_configure_subscription_via_sidecar(self, mock_validate):
        """Test configuring a subscription provider via sidecar."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/subscription/configure",
                json={"sidecar_provider": "claude"},
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["provider_type"] == "claude_subscription"
        assert data["sidecar_provider"] == "claude"
        assert data["masked_api_key"] == "sidecar-managed"
        assert data["status"] == "connected"
        assert data["base_url"] is None  # Auto-routed via AI_SIDECAR_URL

    @patch("src.routers.ai.validate_sidecar_connection")
    async def test_configure_codex_subscription_via_sidecar(self, mock_validate):
        """Test configuring ChatGPT subscription via codex sidecar."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/subscription/configure",
                json={"sidecar_provider": "codex"},
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["provider_type"] == "chatgpt_subscription"
        assert data["sidecar_provider"] == "codex"

    @patch("src.routers.ai.validate_sidecar_connection")
    async def test_configure_subscription_rejects_unauthenticated_sidecar(
        self, mock_validate
    ):
        """Test that configure fails when sidecar is not authenticated."""
        mock_validate.return_value = (
            False,
            "Sidecar is running but not authenticated for claude.",
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/subscription/configure",
                json={"sidecar_provider": "claude"},
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 400
        assert "not authenticated" in response.json()["detail"].lower()

    async def test_configure_subscription_rejects_invalid_provider(self):
        """Test that invalid sidecar_provider is rejected."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/subscription/configure",
                json={"sidecar_provider": "gemini"},
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 422

    @patch("src.routers.ai.validate_sidecar_connection")
    @patch("src.routers.ai.validate_ai_api_key")
    async def test_subscription_configure_overwrites_existing_provider(
        self, mock_api_validate, mock_sidecar_validate
    ):
        """Test that subscription configure overwrites an existing direct API config."""
        mock_api_validate.return_value = (True, None)
        mock_sidecar_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            # First configure a direct API provider
            await client.post(
                "/api/ai/provider",
                json={
                    "provider_type": "claude_api",
                    "api_key": "sk-ant-test-overwrite-1234",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

            # Now switch to subscription via sidecar
            response = await client.post(
                "/api/ai/subscription/configure",
                json={"sidecar_provider": "claude"},
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["provider_type"] == "claude_subscription"
        assert data["sidecar_provider"] == "claude"
        assert data["masked_api_key"] == "sidecar-managed"

    @patch("src.routers.ai.validate_sidecar_connection")
    async def test_configure_subscription_with_custom_model(self, mock_validate):
        """Test configuring subscription provider with custom model name."""
        mock_validate.return_value = (True, None)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/subscription/configure",
                json={
                    "sidecar_provider": "claude",
                    "model_name": "claude-opus-4-6",
                },
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["model_name"] == "claude-opus-4-6"

    @patch("src.routers.ai.validate_sidecar_connection")
    async def test_configure_subscription_returns_502_when_sidecar_unreachable(
        self, mock_validate
    ):
        """Test that configure returns 502 when sidecar is unreachable."""
        mock_validate.return_value = (
            False,
            "AI sidecar is not reachable. Ensure the sidecar container is running.",
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            session_cookie = await register_and_login(client)

            response = await client.post(
                "/api/ai/subscription/configure",
                json={"sidecar_provider": "claude"},
                cookies={settings.jwt_cookie_name: session_cookie},
            )

        assert response.status_code == 502
        assert "not reachable" in response.json()["detail"].lower()


class TestAPIKeyEncryption:
    """Tests for API key encryption roundtrip."""

    def test_encrypt_decrypt_roundtrip(self):
        """Test that encrypting then decrypting returns the original key."""
        api_key = "sk-ant-test-key-roundtrip-12345"
        encrypted = encrypt_credential(api_key)
        decrypted = decrypt_credential(encrypted)
        assert decrypted == api_key

    def test_encryption_produces_different_ciphertext(self):
        """Test that the same key produces different ciphertext each time (Fernet uses timestamp)."""
        api_key = "sk-ant-test-key-different"
        encrypted1 = encrypt_credential(api_key)
        encrypted2 = encrypt_credential(api_key)
        assert encrypted1 != encrypted2
        # But both decrypt to the same value
        assert decrypt_credential(encrypted1) == api_key
        assert decrypt_credential(encrypted2) == api_key


class TestMaskAPIKey:
    """Tests for API key masking utility."""

    def test_mask_standard_key(self):
        """Test masking a standard API key."""
        result = mask_api_key("sk-ant-test-key-abcd")
        assert result == "sk-...abcd"

    def test_mask_openai_key(self):
        """Test masking an OpenAI-style key."""
        result = mask_api_key("sk-proj-xyz123")
        assert result == "sk-...z123"

    def test_mask_short_key(self):
        """Test masking a very short key."""
        result = mask_api_key("ab")
        assert result == "****"

    def test_mask_non_sk_prefix(self):
        """Test masking a key without sk- prefix."""
        result = mask_api_key("xai-test-key-9876")
        assert result == "...9876"
