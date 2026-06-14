"""max_tokens budget threads runner -> generate (for thinking models, issue #554)."""

from benchmarks.core.runner import run_scenario
from benchmarks.scenario import Scenario
from src.models.ai_provider import AIProviderType
from src.schemas.ai_response import AIResponse, AIUsage
from src.services.ai_client import BaseAIClient


class _CapturingClient(BaseAIClient):
    def __init__(self):
        super().__init__(api_key="x", model="cap", provider_type=AIProviderType.OPENAI_COMPATIBLE)
        self.seen_max_tokens = "UNSET"

    async def generate(self, messages, system_prompt=None, max_tokens=1024):
        self.seen_max_tokens = max_tokens
        return AIResponse(content="ok", model=self.model,
                          provider=AIProviderType.OPENAI_COMPATIBLE,
                          usage=AIUsage(input_tokens=1, output_tokens=1))


def _scn():
    return Scenario.model_validate({
        "id": "mt-1", "surface": "chat", "units": "mg/dL",
        "input": {"message": "hi", "context": ""}, "ground_truth": {},
    })


async def test_max_tokens_passed_through_when_set():
    c = _CapturingClient()
    await run_scenario(_scn(), c, max_tokens=8192)
    assert c.seen_max_tokens == 8192


async def test_default_uses_client_default_when_unset():
    c = _CapturingClient()
    await run_scenario(_scn(), c)
    assert c.seen_max_tokens == 1024  # client's own default, not overridden
