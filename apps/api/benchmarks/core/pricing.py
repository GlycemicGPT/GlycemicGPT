"""Rough USD cost estimation from token usage.

IMPORTANT: model prices change often and vary by region/tier. PRICE_TABLE is a
USER-EDITABLE TEMPLATE -- it ships EMPTY. Add entries you have VERIFIED against
your provider's current pricing page. Unknown models return None (reported as
"unknown"), never a guessed number. Local models are usually free -- map them to
(0.0, 0.0) yourself if you want a $0 line.
"""

from __future__ import annotations

# model-id substring -> (usd_per_1k_input_tokens, usd_per_1k_output_tokens).
# EDIT and VERIFY before relying on any dollar figure. Ships empty on purpose.
PRICE_TABLE: dict[str, tuple[float, float]] = {}


def estimate_cost_usd(
    model: str, input_tokens: int, output_tokens: int
) -> float | None:
    """Estimate USD cost, or None if `model` matches no PRICE_TABLE entry."""
    model_lower = (model or "").lower()
    key = next((k for k in PRICE_TABLE if k in model_lower), None)
    if key is None:
        return None
    cost_in, cost_out = PRICE_TABLE[key]
    return round(input_tokens / 1000 * cost_in + output_tokens / 1000 * cost_out, 6)
