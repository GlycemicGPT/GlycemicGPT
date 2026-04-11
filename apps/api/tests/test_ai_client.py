"""Story 5.2 / 14.4: Tests for BYOAI abstraction layer."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import openai
import pytest

from src.integrations.claude import ClaudeClient
from src.integrations.openai_client import OpenAIClient
from src.models.ai_provider import AIProviderType
from src.schemas.ai_response import AIMessage, AIResponse


def _user_message(content: str = "Hello") -> list[AIMessage]:
    """Create a single user message list for testing."""
    return [AIMessage(role="user", content=content)]


class TestClaudeClient:
    """Tests for ClaudeClient.generate()."""

    @patch("src.integrations.claude.anthropic.AsyncAnthropic")
    async def test_generate_returns_normalized_response(self, mock_cls):
        """Test that Claude generate() returns a normalized AIResponse."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(text="Hello from Claude")],
            model="claude-sonnet-4-5-20250929",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )

        client = ClaudeClient(
            api_key="sk-test",
            model="claude-sonnet-4-5-20250929",
            provider_type=AIProviderType.CLAUDE_API,
        )
        result = await client.generate(_user_message())

        assert isinstance(result, AIResponse)
        assert result.content == "Hello from Claude"
        assert result.model == "claude-sonnet-4-5-20250929"
        assert result.provider == AIProviderType.CLAUDE_API
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 5

    @patch("src.integrations.claude.anthropic.AsyncAnthropic")
    async def test_generate_with_system_prompt(self, mock_cls):
        """Test that system prompt is passed to the Anthropic API."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(text="response")],
            model="claude-sonnet-4-5-20250929",
            usage=SimpleNamespace(input_tokens=20, output_tokens=10),
        )

        client = ClaudeClient(api_key="sk-test", model="claude-sonnet-4-5-20250929")
        await client.generate(
            _user_message(),
            system_prompt="You are a diabetes assistant.",
        )

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["system"] == "You are a diabetes assistant."

    @patch("src.integrations.claude.anthropic.AsyncAnthropic")
    async def test_generate_without_system_prompt(self, mock_cls):
        """Test that system key is omitted when no system prompt given."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(text="response")],
            model="claude-sonnet-4-5-20250929",
            usage=SimpleNamespace(input_tokens=5, output_tokens=3),
        )

        client = ClaudeClient(api_key="sk-test", model="claude-sonnet-4-5-20250929")
        await client.generate(_user_message())

        call_kwargs = mock_client.messages.create.call_args[1]
        assert "system" not in call_kwargs

    @patch("src.integrations.claude.anthropic.AsyncAnthropic")
    async def test_generate_auth_error_raises(self, mock_cls):
        """Test that authentication errors propagate."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = anthropic.AuthenticationError(
            message="invalid key",
            response=MagicMock(status_code=401),
            body=None,
        )

        client = ClaudeClient(api_key="sk-bad", model="claude-sonnet-4-5-20250929")
        with pytest.raises(anthropic.AuthenticationError):
            await client.generate(_user_message())

    @patch("src.integrations.claude.anthropic.AsyncAnthropic")
    async def test_generate_rate_limit_raises(self, mock_cls):
        """Test that rate limit errors propagate."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )

        client = ClaudeClient(api_key="sk-test", model="claude-sonnet-4-5-20250929")
        with pytest.raises(anthropic.RateLimitError):
            await client.generate(_user_message())

    @patch("src.integrations.claude.anthropic.AsyncAnthropic")
    async def test_generate_connection_error_raises(self, mock_cls):
        """Test that connection errors propagate."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = anthropic.APIConnectionError(
            request=MagicMock(),
        )

        client = ClaudeClient(api_key="sk-test", model="claude-sonnet-4-5-20250929")
        with pytest.raises(anthropic.APIConnectionError):
            await client.generate(_user_message())

    @patch("src.integrations.claude.anthropic.AsyncAnthropic")
    async def test_generate_unexpected_error_raises(self, mock_cls):
        """Test that unexpected errors propagate."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = RuntimeError("unexpected")

        client = ClaudeClient(api_key="sk-test", model="claude-sonnet-4-5-20250929")
        with pytest.raises(RuntimeError, match="unexpected"):
            await client.generate(_user_message())

    @patch("src.integrations.claude.anthropic.AsyncAnthropic")
    async def test_generate_empty_content_returns_empty_string(self, mock_cls):
        """Test that empty content list returns empty string."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[],
            model="claude-sonnet-4-5-20250929",
            usage=SimpleNamespace(input_tokens=5, output_tokens=0),
        )

        client = ClaudeClient(api_key="sk-test", model="claude-sonnet-4-5-20250929")
        result = await client.generate(_user_message())

        assert result.content == ""

    @patch("src.integrations.claude.anthropic.AsyncAnthropic")
    async def test_generate_handles_null_usage(self, mock_cls):
        """Test that missing usage info defaults to zero."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(text="response")],
            model="claude-sonnet-4-5-20250929",
            usage=None,
        )

        client = ClaudeClient(api_key="sk-test", model="claude-sonnet-4-5-20250929")
        result = await client.generate(_user_message())

        assert result.usage.input_tokens == 0
        assert result.usage.output_tokens == 0

    @patch("src.integrations.claude.anthropic.AsyncAnthropic")
    async def test_generate_preserves_message_roles(self, mock_cls):
        """Test that message roles are preserved in multi-turn conversations."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(text="response")],
            model="claude-sonnet-4-5-20250929",
            usage=SimpleNamespace(input_tokens=20, output_tokens=5),
        )

        messages = [
            AIMessage(role="user", content="What is my A1C?"),
            AIMessage(role="assistant", content="Your A1C is 6.5%."),
            AIMessage(role="user", content="Is that good?"),
        ]

        client = ClaudeClient(api_key="sk-test", model="claude-sonnet-4-5-20250929")
        await client.generate(messages)

        call_kwargs = mock_client.messages.create.call_args[1]
        sent_messages = call_kwargs["messages"]
        assert sent_messages[0]["role"] == "user"
        assert sent_messages[1]["role"] == "assistant"
        assert sent_messages[2]["role"] == "user"


class TestOpenAIClient:
    """Tests for OpenAIClient.generate()."""

    @patch("src.integrations.openai_client.openai.AsyncOpenAI")
    async def test_generate_returns_normalized_response(self, mock_cls):
        """Test that OpenAI generate() returns a normalized AIResponse."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="Hello from OpenAI"))
            ],
            model="gpt-4o",
            usage=SimpleNamespace(prompt_tokens=8, completion_tokens=4),
        )

        client = OpenAIClient(
            api_key="sk-test",
            model="gpt-4o",
            provider_type=AIProviderType.OPENAI_API,
        )
        result = await client.generate(_user_message())

        assert isinstance(result, AIResponse)
        assert result.content == "Hello from OpenAI"
        assert result.model == "gpt-4o"
        assert result.provider == AIProviderType.OPENAI_API
        assert result.usage.input_tokens == 8
        assert result.usage.output_tokens == 4

    @patch("src.integrations.openai_client.openai.AsyncOpenAI")
    async def test_generate_with_base_url(self, mock_cls):
        """Test that base_url is passed to AsyncOpenAI constructor."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="proxy response"))
            ],
            model="claude-sonnet-4-5-20250929",
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3),
        )

        client = OpenAIClient(
            api_key="not-needed",
            model="claude-sonnet-4-5-20250929",
            base_url="http://localhost:3456/v1",
            provider_type=AIProviderType.CLAUDE_SUBSCRIPTION,
        )
        result = await client.generate(_user_message())

        # Verify base_url was passed to constructor
        mock_cls.assert_called_once_with(
            api_key="not-needed",
            base_url="http://localhost:3456/v1",
        )
        assert result.provider == AIProviderType.CLAUDE_SUBSCRIPTION

    @patch("src.integrations.openai_client.openai.AsyncOpenAI")
    async def test_generate_without_base_url(self, mock_cls):
        """Test that base_url is not passed when None."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="response"))],
            model="gpt-4o",
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3),
        )

        client = OpenAIClient(
            api_key="sk-test",
            model="gpt-4o",
            provider_type=AIProviderType.OPENAI_API,
        )
        await client.generate(_user_message())

        # Verify only api_key was passed (no base_url)
        mock_cls.assert_called_once_with(api_key="sk-test")

    @patch("src.integrations.openai_client.openai.AsyncOpenAI")
    async def test_generate_with_system_prompt(self, mock_cls):
        """Test that system prompt is prepended as system message for OpenAI."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="response"))],
            model="gpt-4o",
            usage=SimpleNamespace(prompt_tokens=15, completion_tokens=5),
        )

        client = OpenAIClient(api_key="sk-test", model="gpt-4o")
        await client.generate(
            _user_message(),
            system_prompt="You are a diabetes assistant.",
        )

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a diabetes assistant."
        assert messages[1]["role"] == "user"

    @patch("src.integrations.openai_client.openai.AsyncOpenAI")
    async def test_generate_without_system_prompt(self, mock_cls):
        """Test that no system message is added when system prompt is omitted."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="response"))],
            model="gpt-4o",
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3),
        )

        client = OpenAIClient(api_key="sk-test", model="gpt-4o")
        await client.generate(_user_message())

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    @patch("src.integrations.openai_client.openai.AsyncOpenAI")
    async def test_generate_auth_error_raises(self, mock_cls):
        """Test that authentication errors propagate."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = openai.AuthenticationError(
            message="invalid key",
            response=MagicMock(status_code=401),
            body=None,
        )

        client = OpenAIClient(api_key="sk-bad", model="gpt-4o")
        with pytest.raises(openai.AuthenticationError):
            await client.generate(_user_message())

    @patch("src.integrations.openai_client.openai.AsyncOpenAI")
    async def test_generate_handles_null_usage(self, mock_cls):
        """Test that missing usage info defaults to zero."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))],
            model="gpt-4o",
            usage=None,
        )

        client = OpenAIClient(api_key="sk-test", model="gpt-4o")
        result = await client.generate(_user_message())

        assert result.usage.input_tokens == 0
        assert result.usage.output_tokens == 0

    @patch("src.integrations.openai_client.openai.AsyncOpenAI")
    async def test_generate_rate_limit_raises(self, mock_cls):
        """Test that rate limit errors propagate."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = openai.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )

        client = OpenAIClient(api_key="sk-test", model="gpt-4o")
        with pytest.raises(openai.RateLimitError):
            await client.generate(_user_message())

    @patch("src.integrations.openai_client.openai.AsyncOpenAI")
    async def test_generate_connection_error_raises(self, mock_cls):
        """Test that connection errors propagate."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = openai.APIConnectionError(
            request=MagicMock(),
        )

        client = OpenAIClient(api_key="sk-test", model="gpt-4o")
        with pytest.raises(openai.APIConnectionError):
            await client.generate(_user_message())

    @patch("src.integrations.openai_client.openai.AsyncOpenAI")
    async def test_generate_unexpected_error_raises(self, mock_cls):
        """Test that unexpected errors propagate."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = RuntimeError("unexpected")

        client = OpenAIClient(api_key="sk-test", model="gpt-4o")
        with pytest.raises(RuntimeError, match="unexpected"):
            await client.generate(_user_message())

    @patch("src.integrations.openai_client.openai.AsyncOpenAI")
    async def test_generate_empty_choices_returns_empty_string(self, mock_cls):
        """Test that empty choices list returns empty string."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[],
            model="gpt-4o",
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=0),
        )

        client = OpenAIClient(api_key="sk-test", model="gpt-4o")
        result = await client.generate(_user_message())

        assert result.content == ""

    @patch("src.integrations.openai_client.openai.AsyncOpenAI")
    async def test_generate_preserves_message_roles(self, mock_cls):
        """Test that message roles are preserved in multi-turn conversations."""
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="response"))],
            model="gpt-4o",
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=5),
        )

        messages = [
            AIMessage(role="user", content="What is my A1C?"),
            AIMessage(role="assistant", content="Your A1C is 6.5%."),
            AIMessage(role="user", content="Is that good?"),
        ]

        client = OpenAIClient(api_key="sk-test", model="gpt-4o")
        await client.generate(messages)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        sent_messages = call_kwargs["messages"]
        assert sent_messages[0]["role"] == "user"
        assert sent_messages[1]["role"] == "assistant"
        assert sent_messages[2]["role"] == "user"


class TestResponseNormalization:
    """Test that both providers return the same AIResponse shape."""

    @patch("src.integrations.claude.anthropic.AsyncAnthropic")
    @patch("src.integrations.openai_client.openai.AsyncOpenAI")
    async def test_both_providers_return_same_schema(
        self, mock_openai_cls, mock_claude_cls
    ):
        """Test that Claude and OpenAI clients both return AIResponse."""
        # Set up Claude mock
        mock_claude = AsyncMock()
        mock_claude_cls.return_value = mock_claude
        mock_claude.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(text="Claude says hello")],
            model="claude-sonnet-4-5-20250929",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )

        # Set up OpenAI mock
        mock_openai = AsyncMock()
        mock_openai_cls.return_value = mock_openai
        mock_openai.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="OpenAI says hello"))
            ],
            model="gpt-4o",
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )

        claude_client = ClaudeClient(api_key="sk-c", model="claude-sonnet-4-5-20250929")
        openai_client = OpenAIClient(api_key="sk-o", model="gpt-4o")

        claude_result = await claude_client.generate(_user_message())
        openai_result = await openai_client.generate(_user_message())

        # Both return AIResponse with the same fields
        for result in [claude_result, openai_result]:
            assert isinstance(result, AIResponse)
            assert isinstance(result.content, str)
            assert isinstance(result.model, str)
            assert isinstance(result.provider, AIProviderType)
            assert hasattr(result.usage, "input_tokens")
            assert hasattr(result.usage, "output_tokens")


class TestAIClientFactory:
    """Tests for get_ai_client factory function."""

    async def test_factory_returns_claude_client(self):
        """Test factory returns ClaudeClient for claude_api provider."""
        from src.services.ai_client import get_ai_client

        mock_user = SimpleNamespace(id=uuid.uuid4())
        mock_config = SimpleNamespace(
            provider_type=AIProviderType.CLAUDE_API,
            encrypted_api_key="encrypted-key",
            model_name=None,
            base_url=None,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_db.execute.return_value = mock_result

        with patch(
            "src.services.ai_client.decrypt_credential", return_value="sk-ant-key"
        ):
            client = await get_ai_client(mock_user, mock_db)

        assert isinstance(client, ClaudeClient)
        assert client.model == "claude-sonnet-4-5-20250929"

    async def test_factory_returns_openai_client(self):
        """Test factory returns OpenAIClient for openai_api provider."""
        from src.services.ai_client import get_ai_client

        mock_user = SimpleNamespace(id=uuid.uuid4())
        mock_config = SimpleNamespace(
            provider_type=AIProviderType.OPENAI_API,
            encrypted_api_key="encrypted-key",
            model_name="gpt-4o-mini",
            base_url=None,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_db.execute.return_value = mock_result

        with patch(
            "src.services.ai_client.decrypt_credential", return_value="sk-openai-key"
        ):
            client = await get_ai_client(mock_user, mock_db)

        assert isinstance(client, OpenAIClient)
        assert client.model == "gpt-4o-mini"

    async def test_factory_returns_openai_client_for_subscription(self):
        """Test factory returns OpenAIClient with base_url for subscription types."""
        from src.services.ai_client import get_ai_client

        mock_user = SimpleNamespace(id=uuid.uuid4())
        mock_config = SimpleNamespace(
            provider_type=AIProviderType.CLAUDE_SUBSCRIPTION,
            encrypted_api_key="encrypted-key",
            model_name=None,
            base_url="http://localhost:3456/v1",
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_db.execute.return_value = mock_result

        with patch(
            "src.services.ai_client.decrypt_credential", return_value="not-needed"
        ):
            client = await get_ai_client(mock_user, mock_db)

        assert isinstance(client, OpenAIClient)
        assert client._base_url == "http://localhost:3456/v1"
        assert client._provider_type == AIProviderType.CLAUDE_SUBSCRIPTION

    async def test_factory_returns_openai_client_for_compatible(self):
        """Test factory returns OpenAIClient for openai_compatible type."""
        from src.services.ai_client import get_ai_client

        mock_user = SimpleNamespace(id=uuid.uuid4())
        mock_config = SimpleNamespace(
            provider_type=AIProviderType.OPENAI_COMPATIBLE,
            encrypted_api_key="encrypted-key",
            model_name="llama3.1:70b",
            base_url="http://localhost:11434/v1",
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_db.execute.return_value = mock_result

        with patch(
            "src.services.ai_client.decrypt_credential", return_value="not-needed"
        ):
            client = await get_ai_client(mock_user, mock_db)

        assert isinstance(client, OpenAIClient)
        assert client.model == "llama3.1:70b"
        assert client._base_url == "http://localhost:11434/v1"

    async def test_factory_raises_404_when_no_provider(self):
        """Test factory raises HTTPException 404 when no provider configured."""
        from fastapi import HTTPException

        from src.services.ai_client import get_ai_client

        mock_user = SimpleNamespace(id=uuid.uuid4())

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await get_ai_client(mock_user, mock_db)

        assert exc_info.value.status_code == 404
        assert "No AI provider configured" in exc_info.value.detail

    async def test_factory_uses_custom_model_name(self):
        """Test factory uses model_name from config when set."""
        from src.services.ai_client import get_ai_client

        mock_user = SimpleNamespace(id=uuid.uuid4())
        mock_config = SimpleNamespace(
            provider_type=AIProviderType.CLAUDE_API,
            encrypted_api_key="encrypted-key",
            model_name="claude-opus-4-6",
            base_url=None,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_db.execute.return_value = mock_result

        with patch(
            "src.services.ai_client.decrypt_credential", return_value="sk-ant-key"
        ):
            client = await get_ai_client(mock_user, mock_db)

        assert client.model == "claude-opus-4-6"

    async def test_factory_uses_sidecar_api_key_when_encrypted_api_key_is_none(self):
        """Test factory uses sidecar API key when encrypted_api_key is None."""
        from src.services.ai_client import get_ai_client

        mock_user = SimpleNamespace(id=uuid.uuid4())
        mock_config = SimpleNamespace(
            provider_type=AIProviderType.CLAUDE_SUBSCRIPTION,
            encrypted_api_key=None,
            model_name=None,
            base_url="http://ai-sidecar:3456/v1",
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_db.execute.return_value = mock_result

        with patch("src.services.ai_client.settings") as mock_settings:
            mock_settings.ai_sidecar_api_key = "test-sidecar-key"
            mock_settings.ai_sidecar_url = "http://ai-sidecar:3456"
            client = await get_ai_client(mock_user, mock_db)

        assert isinstance(client, OpenAIClient)
        assert client._api_key == "test-sidecar-key"
        assert client._base_url == "http://ai-sidecar:3456/v1"

    async def test_factory_auto_routes_subscription_through_sidecar(self):
        """Test factory auto-sets base_url to sidecar for subscription types with no base_url."""
        from src.services.ai_client import get_ai_client

        mock_user = SimpleNamespace(id=uuid.uuid4())
        mock_config = SimpleNamespace(
            provider_type=AIProviderType.CLAUDE_SUBSCRIPTION,
            encrypted_api_key=None,
            model_name=None,
            base_url=None,  # No explicit base_url
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_db.execute.return_value = mock_result

        with patch("src.services.ai_client.settings") as mock_settings:
            mock_settings.ai_sidecar_url = "http://ai-sidecar:3456"
            mock_settings.ai_sidecar_api_key = "test-sidecar-key"
            client = await get_ai_client(mock_user, mock_db)

        assert isinstance(client, OpenAIClient)
        assert client._base_url == "http://ai-sidecar:3456/v1"
        assert client._api_key == "test-sidecar-key"

    async def test_factory_preserves_explicit_base_url_for_subscription(self):
        """Test factory uses explicit base_url when set, even for subscription types."""
        from src.services.ai_client import get_ai_client

        mock_user = SimpleNamespace(id=uuid.uuid4())
        mock_config = SimpleNamespace(
            provider_type=AIProviderType.CLAUDE_SUBSCRIPTION,
            encrypted_api_key="encrypted-key",
            model_name=None,
            base_url="http://custom-proxy:8080/v1",  # Explicit base_url
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_db.execute.return_value = mock_result

        with patch(
            "src.services.ai_client.decrypt_credential", return_value="not-needed"
        ):
            client = await get_ai_client(mock_user, mock_db)

        assert isinstance(client, OpenAIClient)
        assert client._base_url == "http://custom-proxy:8080/v1"

    async def test_factory_raises_400_on_unsupported_provider(self):
        """Test factory raises HTTPException 400 for unsupported provider type."""
        from fastapi import HTTPException

        from src.services.ai_client import get_ai_client

        mock_user = SimpleNamespace(id=uuid.uuid4())
        mock_config = SimpleNamespace(
            provider_type="gemini",
            encrypted_api_key="encrypted-key",
            model_name=None,
            base_url=None,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_db.execute.return_value = mock_result

        with (
            patch(
                "src.services.ai_client.decrypt_credential",
                return_value="sk-gemini-key",
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_ai_client(mock_user, mock_db)

        assert exc_info.value.status_code == 400
        assert "Unsupported AI provider" in exc_info.value.detail
