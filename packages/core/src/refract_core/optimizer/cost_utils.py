"""Pre-call cost estimation for the optimizer loop.

Purely a rough pre-check helper (same spirit as ``budget.estimate_cost_usd``,
which needs per-token pricing already looked up) — the real, authoritative
spend always comes from ``LLMResponse.cost_usd`` after a call actually
happens, recorded via ``BudgetTracker.record_spend``. This module never
substitutes for that; nothing in the optimizer loop trusts its output for
anything but an optional pre-flight ``assert_can_afford`` check.
"""

from __future__ import annotations

import litellm

__all__ = ["estimate_cost"]


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Rough cost estimate for one call against ``model``.

    Returns ``0.0`` on any error — self-hosted/local models and models
    LiteLLM has no pricing data for are both treated as free for
    estimation purposes. Never raises; this is a best-effort planning
    number, not a billing figure.
    """
    try:
        cost = litellm.completion_cost(
            model=model, prompt_tokens=input_tokens, completion_tokens=output_tokens
        )
        return float(cost) if cost is not None else 0.0
    except Exception:
        return 0.0
