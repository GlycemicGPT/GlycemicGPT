"""Story 5.2 / 14.2 / 15.4: BYOAI abstraction layer.

Abstract base class and factory for AI provider clients.
Provides a unified interface for generating AI responses
regardless of the underlying provider (Claude, OpenAI, subscription proxy,
or self-hosted OpenAI-compatible endpoint).

Story 15.4: Subscription types auto-route through managed sidecar.
"""

import abc

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.encryption import decrypt_credential
from src.logging_config import get_logger
from src.models.ai_provider import AIProviderConfig, AIProviderType
from src.models.user import User
from src.schemas.ai_response import AIMessage, AIResponse

logger = get_logger(__name__)

# Default models when user has not specified a model_name override
DEFAULT_MODELS: dict[AIProviderType, str] = {
    AIProviderType.CLAUDE_API: "claude-sonnet-4-5-20250929",
    AIProviderType.OPENAI_API: "gpt-4o",
    AIProviderType.CLAUDE_SUBSCRIPTION: "claude-sonnet-4-5-20250929",
    AIProviderType.CHATGPT_SUBSCRIPTION: "gpt-4o",
    AIProviderType.OPENAI_COMPATIBLE: "",  # Must be specified by user
    # Legacy values
    AIProviderType.CLAUDE: "claude-sonnet-4-5-20250929",
    AIProviderType.OPENAI: "gpt-4o",
}

# Provider types that use the OpenAI SDK (with optional base_url)
_OPENAI_SDK_TYPES = {
    AIProviderType.OPENAI_API,
    AIProviderType.CLAUDE_SUBSCRIPTION,
    AIProviderType.CHATGPT_SUBSCRIPTION,
    AIProviderType.OPENAI_COMPATIBLE,
    AIProviderType.OPENAI,  # Legacy
}

# Provider types that use the Anthropic SDK
_ANTHROPIC_SDK_TYPES = {
    AIProviderType.CLAUDE_API,
    AIProviderType.CLAUDE,  # Legacy
}

# Subscription types that route through the managed sidecar
_SUBSCRIPTION_TYPES = {
    AIProviderType.CLAUDE_SUBSCRIPTION,
    AIProviderType.CHATGPT_SUBSCRIPTION,
}


class BaseAIClient(abc.ABC):
    """Abstract base class for AI provider clients.

    Subclasses implement provider-specific API calls while
    returning a normalized AIResponse.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        provider_type: AIProviderType | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._base_url = base_url
        self._provider_type = provider_type

    @abc.abstractmethod
    async def generate(
        self,
        messages: list[AIMessage],
        system_prompt: str | None = None,
        max_tokens: int = 1024,
    ) -> AIResponse:
        """Generate an AI response.

        Args:
            messages: List of conversation messages.
            system_prompt: Optional system-level instruction.
            max_tokens: Maximum tokens in the response.

        Returns:
            Normalized AIResponse with content, model, provider, and usage.
        """


async def get_ai_client(
    user: User,
    db: AsyncSession,
) -> BaseAIClient:
    """Factory that returns the appropriate AI client for a user.

    Loads the user's AI provider configuration, decrypts the API key,
    and returns a configured client instance.

    Args:
        user: The authenticated user.
        db: Database session.

    Returns:
        A configured BaseAIClient subclass instance.

    Raises:
        HTTPException: 404 if no provider is configured.
    """
    from src.integrations.claude import ClaudeClient
    from src.integrations.openai_client import OpenAIClient

    result = await db.execute(
        select(AIProviderConfig).where(AIProviderConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No AI provider configured. Please configure an AI provider first.",
        )

    # Subscription types using sidecar OAuth may have no stored API key;
    # they use a placeholder key since the sidecar handles authentication.
    if config.encrypted_api_key:
        api_key = decrypt_credential(config.encrypted_api_key)
    else:
        api_key = settings.ai_sidecar_api_key or "sidecar-managed"
    model = config.model_name or DEFAULT_MODELS.get(config.provider_type, "")

    # For subscription types, auto-route through the managed sidecar
    # when no explicit base_url is configured.
    base_url = config.base_url
    if config.provider_type in _SUBSCRIPTION_TYPES and not base_url:
        base_url = f"{settings.ai_sidecar_url}/v1"

    if config.provider_type in _ANTHROPIC_SDK_TYPES:
        return ClaudeClient(
            api_key=api_key,
            model=model,
            provider_type=config.provider_type,
        )

    if config.provider_type in _OPENAI_SDK_TYPES:
        if not model:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No model specified. Please configure a model name for your provider.",
            )
        return OpenAIClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
            provider_type=config.provider_type,
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported AI provider: {config.provider_type}",
    )
