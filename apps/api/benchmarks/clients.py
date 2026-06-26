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


def build_client_from_env(prefix: str = "BENCHMARK") -> BaseAIClient:
    """Construct a real provider client from ``{prefix}_*`` env vars.

    The default prefix is ``BENCHMARK``, so existing callers are unaffected.
    Pass ``prefix="JUDGE"`` to read ``JUDGE_PROVIDER``, ``JUDGE_MODEL``, etc.
    """
    provider_key = f"{prefix}_PROVIDER"
    provider = os.environ.get(provider_key)
    if not provider:
        raise ValueError(f"{provider_key} is not set")
    if provider not in _PROVIDER_MAP:
        raise ValueError(f"Unsupported {provider_key}: {provider}")

    provider_type = _PROVIDER_MAP[provider]
    model = os.environ.get(f"{prefix}_MODEL", "")
    api_key = os.environ.get(f"{prefix}_API_KEY")
    base_url = os.environ.get(f"{prefix}_BASE_URL") or None

    # Local imports keep heavy SDKs out of import-time for tests that only use MockClient.
    from src.integrations.claude import ClaudeClient
    from src.integrations.openai_client import OpenAIClient

    if provider_type == AIProviderType.CLAUDE_API:
        if not api_key:
            raise ValueError(f"{prefix}_API_KEY is required for claude_api")
        return ClaudeClient(
            api_key=api_key,
            model=model or "claude-sonnet-4-5-20250929",
            provider_type=provider_type,
        )
    if not model:
        raise ValueError(f"{prefix}_MODEL is required for openai_* providers")
    # A custom base_url is only meaningful for openai_compatible (local/self-hosted);
    # forwarding it to the hosted openai_api could silently redirect a benchmark to
    # the wrong backend, and a hosted provider must have a real key.
    if provider_type == AIProviderType.OPENAI_API:
        if not api_key:
            raise ValueError(f"{prefix}_API_KEY is required for openai_api")
        if base_url is not None:
            raise ValueError(
                f"{prefix}_BASE_URL is only supported for openai_compatible"
            )
    return OpenAIClient(
        api_key=api_key or "benchmark",
        model=model,
        base_url=base_url
        if provider_type == AIProviderType.OPENAI_COMPATIBLE
        else None,
        provider_type=provider_type,
    )
