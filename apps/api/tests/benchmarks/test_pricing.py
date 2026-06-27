from benchmarks.core import pricing
from benchmarks.core.pricing import estimate_cost_usd


def test_known_model_cost(monkeypatch):
    monkeypatch.setitem(pricing.PRICE_TABLE, "test-model", (0.001, 0.002))
    # 1000 in * 0.001 + 2000 out * 0.002 per 1k => 0.001 + 0.004 = 0.005
    assert estimate_cost_usd("test-model", 1000, 2000) == 0.005


def test_substring_match(monkeypatch):
    monkeypatch.setitem(pricing.PRICE_TABLE, "sonnet", (0.003, 0.015))
    assert estimate_cost_usd("claude-sonnet-4-5-20250929", 1000, 0) == 0.003


def test_unknown_model_returns_none():
    assert estimate_cost_usd("some-local-7b", 1000, 1000) is None


def test_most_specific_price_key_wins(monkeypatch):
    # With both keys present (broad inserted first), the longer/more specific key
    # must win so gpt-4o-mini isn't charged the gpt-4o rate.
    monkeypatch.setitem(pricing.PRICE_TABLE, "gpt-4o", (1.0, 1.0))
    monkeypatch.setitem(pricing.PRICE_TABLE, "gpt-4o-mini", (0.001, 0.001))
    assert estimate_cost_usd("gpt-4o-mini", 1000, 0) == 0.001
