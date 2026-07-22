"""Unit tests for reprompt_core.optimizer.seam — Phase 4 seam regression."""

from __future__ import annotations

from dataclasses import dataclass

from reprompt_core.budget import BudgetTracker
from reprompt_core.llm.client import LLMResponse
from reprompt_core.optimizer.seam import SeamExample, SeamInput, evaluate_seam
from reprompt_core.trace import TokenUsage


def _fake_usage() -> TokenUsage:
    return TokenUsage(input=10, output=10, thinking=None)


def _make_call(output: str = "downstream output", cost: float = 0.001):
    """Fake call: returns a fixed LLMResponse regardless of model/messages."""
    def call(model: str, messages: list, **kw) -> LLMResponse:
        return LLMResponse(
            content=output,
            model=model,
            provider="fake",
            usage=_fake_usage(),
            cost_usd=cost,
            latency_ms=1.0,
            finish_reason="stop",
        )
    return call


def _example(
    up_input: dict | None = None,
    up_output: str = "upstream output",
    down_input: dict | None = None,
    down_output: str = "downstream output",
) -> SeamExample:
    return SeamExample(
        upstream_input=up_input or {"q": "hello"},
        upstream_baseline_output=up_output,
        downstream_input=down_input or {"root": "upstream output"},
        downstream_baseline_output=down_output,
    )


def _seam_input(examples: list[SeamExample], threshold: float = 0.5) -> SeamInput:
    return SeamInput(
        upstream_stage_id=1,
        upstream_source_id="root",
        upstream_winning_prompt="{{q}}",
        upstream_target_model="gpt-4o-mini",
        upstream_params={"temperature": 0.0},
        downstream_stage_id=2,
        downstream_original_prompt="{{root}}",
        downstream_original_model="gpt-4o-mini",
        downstream_rubric={},
        examples=examples,
        parity_threshold=threshold,
    )


def test_seam_pass_when_downstream_output_matches_baseline():
    """Identical output → score > threshold (0.5) → passed.

    Seam scoring uses det+embedding only (no judge), so the max composite is
    ~0.55 (det×0.25 + embedding×0.30). We check > 0.5, not > 0.9.
    """
    call = _make_call(output="downstream output")
    budget = BudgetTracker(budget_usd=10.0)
    result = evaluate_seam(_seam_input([_example()]), call=call, budget=budget)
    assert result.passed
    assert result.parity_score is not None
    assert result.parity_score > 0.5


def test_seam_fail_when_downstream_output_diverges():
    """Completely different output should fail at a high threshold."""
    call = _make_call(output="COMPLETELY UNRELATED GIBBERISH XYZ 12345")
    budget = BudgetTracker(budget_usd=10.0)
    result = evaluate_seam(_seam_input([_example()], threshold=0.99), call=call, budget=budget)
    assert not result.passed


def test_seam_substitution_applied_when_upstream_source_id_in_downstream_input():
    """upstream_source_id key present in downstream_input → substitution_applied=True."""
    call = _make_call(output="downstream output")
    budget = BudgetTracker(budget_usd=10.0)
    ex = _example(down_input={"root": "old upstream output"})
    result = evaluate_seam(_seam_input([ex]), call=call, budget=budget)
    assert result.substitution_applied


def test_seam_no_substitution_when_key_absent():
    """Key absent from downstream_input → substitution_applied=False (stability check only)."""
    call = _make_call(output="downstream output")
    budget = BudgetTracker(budget_usd=10.0)
    ex = _example(down_input={"some_other_key": "value"})
    result = evaluate_seam(_seam_input([ex]), call=call, budget=budget)
    assert not result.substitution_applied


def test_seam_none_score_when_all_calls_fail():
    """All-failing call → parity_score=None, passed=False."""
    def failing_call(model, messages, **kw):
        raise RuntimeError("network error")

    budget = BudgetTracker(budget_usd=10.0)
    result = evaluate_seam(_seam_input([_example()]), call=failing_call, budget=budget)
    assert result.parity_score is None
    assert not result.passed


def test_seam_budget_exhausted_before_first_example():
    """Pre-exhausted budget → parity_score=None."""
    call = _make_call()
    budget = BudgetTracker(budget_usd=0.001)
    budget.record_spend(0.001)  # pre-exhaust
    assert budget.is_exhausted
    result = evaluate_seam(_seam_input([_example(), _example()]), call=call, budget=budget)
    assert result.parity_score is None


def test_seam_multiple_examples_mean_score():
    """Mean of per-example scores is returned; budget is consumed."""
    call = _make_call(output="downstream output")
    budget = BudgetTracker(budget_usd=10.0)
    result = evaluate_seam(
        _seam_input([_example(), _example(), _example()]),
        call=call,
        budget=budget,
    )
    assert result.parity_score is not None
    assert 0.0 <= result.parity_score <= 1.0
    assert budget.spent_usd > 0.0
