"""Tests for the harness client factory and MockClient."""

import pytest

from benchmarks.clients import MockClient, build_client_from_env
from src.schemas.ai_response import AIMessage


async def test_mock_client_returns_canned_content():
    client = MockClient(content="Your breakfast peaks average 187 mg/dL.")
    resp = await client.generate(
        messages=[AIMessage(role="user", content="hi")],
        system_prompt="sys",
    )
    assert "187" in resp.content
    assert resp.usage.output_tokens > 0


def test_build_client_from_env_requires_provider(monkeypatch):
    monkeypatch.delenv("BENCHMARK_PROVIDER", raising=False)
    with pytest.raises(ValueError, match="BENCHMARK_PROVIDER"):
        build_client_from_env()


def test_build_client_from_env_openai_compatible(monkeypatch):
    monkeypatch.setenv("BENCHMARK_PROVIDER", "openai_compatible")
    monkeypatch.setenv("BENCHMARK_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("BENCHMARK_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("BENCHMARK_API_KEY", "test-api-key")
    client = build_client_from_env()
    assert client.model == "qwen2.5:7b"


def test_build_client_from_env_supports_custom_prefix(monkeypatch):
    monkeypatch.setenv("JUDGE_PROVIDER", "openai_compatible")
    monkeypatch.setenv("JUDGE_MODEL", "judge-model")
    monkeypatch.setenv("JUDGE_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("JUDGE_API_KEY", "test-api-key")
    client = build_client_from_env(prefix="JUDGE")
    assert client.model == "judge-model"


def test_claude_api_requires_api_key(monkeypatch):
    monkeypatch.setenv("BENCHMARK_PROVIDER", "claude_api")
    monkeypatch.delenv("BENCHMARK_API_KEY", raising=False)
    with pytest.raises(ValueError, match="BENCHMARK_API_KEY is required"):
        build_client_from_env()


def test_openai_api_rejects_custom_base_url(monkeypatch):
    monkeypatch.setenv("BENCHMARK_PROVIDER", "openai_api")
    monkeypatch.setenv("BENCHMARK_MODEL", "gpt-4o")
    monkeypatch.setenv("BENCHMARK_API_KEY", "test-api-key")
    monkeypatch.setenv("BENCHMARK_BASE_URL", "https://example.invalid/v1")
    with pytest.raises(ValueError, match="only supported for openai_compatible"):
        build_client_from_env()
