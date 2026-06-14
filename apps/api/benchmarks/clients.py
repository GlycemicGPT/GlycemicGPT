"""Build a BaseAIClient for benchmarking directly from environment variables,
plus a MockClient for deterministic, cost-free tests and CI smoke runs.

Env contract:
  BENCHMARK_PROVIDER : claude_api | openai_api | openai_compatible
  BENCHMARK_MODEL    : model id (required for openai_* providers)
  BENCHMARK_API_KEY  : provider key (or placeholder for local)
  BENCHMARK_BASE_URL : optional base_url for openai_compatible / local
"""

from __future__ import annotations

import os

from src.models.ai_provider import AIProviderType
from src.schemas.ai_response import AIMessage, AIResponse, AIUsage
from src.services.ai_client import BaseAIClient

_PROVIDER_MAP = {
    "claude_api": AIProviderType.CLAUDE_API,
    "openai_api": AIProviderType.OPENAI_API,
    "openai_compatible": AIProviderType.OPENAI_COMPATIBLE,
}


class MockClient(BaseAIClient):
    """Returns canned content; no network. Used by tests and CI smoke."""

    def __init__(self, content: str, model: str = "mock-model") -> None:
        super().__init__(
            api_key="mock",
            model=model,
            provider_type=AIProviderType.OPENAI_COMPATIBLE,
        )
        self._content = content

    async def generate(
        self,
        messages: list[AIMessage],
        system_prompt: str | None = None,
        max_tokens: int = 1024,
    ) -> AIResponse:
        return AIResponse(
            content=self._content,
            model=self.model,
            provider=AIProviderType.OPENAI_COMPATIBLE,
            usage=AIUsage(
                input_tokens=len((system_prompt or "").split())
                + sum(len(m.content.split()) for m in messages),
                output_tokens=max(1, len(self._content.split())),
            ),
        )


def build_client_from_env() -> BaseAIClient:
    """Construct a real provider client from BENCHMARK_* env vars."""
    provider = os.environ.get("BENCHMARK_PROVIDER")
    if not provider:
        raise ValueError("BENCHMARK_PROVIDER is not set")
    if provider not in _PROVIDER_MAP:
        raise ValueError(f"Unsupported BENCHMARK_PROVIDER: {provider}")

    provider_type = _PROVIDER_MAP[provider]
    model = os.environ.get("BENCHMARK_MODEL", "")
    api_key = os.environ.get("BENCHMARK_API_KEY", "benchmark")
    base_url = os.environ.get("BENCHMARK_BASE_URL") or None

    # Local imports keep heavy SDKs out of import-time for tests that only use MockClient.
    from src.integrations.claude import ClaudeClient
    from src.integrations.openai_client import OpenAIClient

    if provider_type == AIProviderType.CLAUDE_API:
        return ClaudeClient(
            api_key=api_key,
            model=model or "claude-sonnet-4-5-20250929",
            provider_type=provider_type,
        )
    if not model:
        raise ValueError("BENCHMARK_MODEL is required for openai_* providers")
    return OpenAIClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        provider_type=provider_type,
    )
