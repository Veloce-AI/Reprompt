"""Tests for reprompt_core.contract.mine — two-axis contract mining.

All tests use fake call/entails callables (no model, no network).
"""

from __future__ import annotations

import json

from reprompt_core.budget import BudgetTracker
from reprompt_core.contract.mine import AssertionSpec, MineExample, MineInput, MinedContract, mine_contract
from reprompt_core.llm.client import LLMResponse
from reprompt_core.trace import TokenUsage


def _fake_usage() -> TokenUsage:
    return TokenUsage(input=5, output=5, thinking=None)


def _make_call(output: str = "response", cost: float = 0.001):
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


def _exact_match(a: str, b: str) -> bool:
    return a.strip() == b.strip()


def _json_example(keys: list[str], output: dict) -> MineExample:
    return MineExample(
        input={"q": "test"},
        rendered_prompt="Answer: {{q}}",
        output=json.dumps(output),
    )


def _mine_input(examples: list[MineExample], axis_b_repeats: int = 0) -> MineInput:
    return MineInput(
        stage_id=1,
        prompt_template="{{q}}",
        target_model="gpt-4o-mini",
        examples=examples,
        axis_b_repeats=axis_b_repeats,
    )


# ---------------------------------------------------------------------------
# Structural invariant extraction
# ---------------------------------------------------------------------------


def test_required_keys_mined_from_uniform_json_outputs() -> None:
    examples = [
        MineExample(input={}, rendered_prompt="p", output=json.dumps({"currency": "USD", "value": 100})),
        MineExample(input={}, rendered_prompt="p", output=json.dumps({"currency": "EUR", "value": 200})),
        MineExample(input={}, rendered_prompt="p", output=json.dumps({"currency": "GBP", "value": 50})),
    ]
    result = mine_contract(
        _mine_input(examples, axis_b_repeats=0),
        call=_make_call(),
        entails=_exact_match,
        budget=BudgetTracker(budget_usd=10.0),
    )
    kinds = {inv.kind for inv in result.invariants}
    assert "required_keys" in kinds
    req_keys_spec = next(inv for inv in result.invariants if inv.kind == "required_keys")
    assert set(req_keys_spec.spec["keys"]) == {"currency", "value"}


def test_enum_values_mined_from_repeated_field_value() -> None:
    examples = [
        MineExample(input={}, rendered_prompt="p", output=json.dumps({"status": "ok", "score": 1})),
        MineExample(input={}, rendered_prompt="p", output=json.dumps({"status": "fail", "score": 0})),
        MineExample(input={}, rendered_prompt="p", output=json.dumps({"status": "ok", "score": 1})),
    ]
    result = mine_contract(
        _mine_input(examples, axis_b_repeats=0),
        call=_make_call(),
        entails=_exact_match,
        budget=BudgetTracker(budget_usd=10.0),
    )
    enum_specs = [inv for inv in result.invariants if inv.kind == "enum_values" and inv.spec.get("field") == "status"]
    assert enum_specs, "expected enum_values assertion for 'status' field"
    assert set(enum_specs[0].spec["values"]) == {"ok", "fail"}


def test_regex_prefix_mined_from_text_outputs() -> None:
    examples = [
        MineExample(input={}, rendered_prompt="p", output="Answer: yes this works"),
        MineExample(input={}, rendered_prompt="p", output="Answer: no it does not"),
        MineExample(input={}, rendered_prompt="p", output="Answer: maybe"),
    ]
    result = mine_contract(
        _mine_input(examples, axis_b_repeats=0),
        call=_make_call(),
        entails=_exact_match,
        budget=BudgetTracker(budget_usd=10.0),
    )
    regex_specs = [inv for inv in result.invariants if inv.kind == "regex"]
    assert regex_specs, "expected regex assertion for common prefix"
    assert "Answer" in regex_specs[0].spec["pattern"]


def test_no_invariants_for_heterogeneous_json_keys() -> None:
    examples = [
        MineExample(input={}, rendered_prompt="p", output=json.dumps({"a": 1})),
        MineExample(input={}, rendered_prompt="p", output=json.dumps({"b": 2})),
    ]
    result = mine_contract(
        _mine_input(examples, axis_b_repeats=0),
        call=_make_call(),
        entails=_exact_match,
        budget=BudgetTracker(budget_usd=10.0),
    )
    req_keys = [inv for inv in result.invariants if inv.kind == "required_keys"]
    assert not req_keys, "no required_keys when no common keys across outputs"


# ---------------------------------------------------------------------------
# Axis B noise floor
# ---------------------------------------------------------------------------


def test_axis_b_stable_output_gives_low_noise_floor() -> None:
    examples = [MineExample(input={}, rendered_prompt="p", output="same output")]
    result = mine_contract(
        _mine_input(examples, axis_b_repeats=3),
        call=_make_call(output="same output"),  # Axis B always returns same string
        entails=_exact_match,
        budget=BudgetTracker(budget_usd=10.0),
    )
    assert result.noise_floor < 0.5  # all Axis B outputs cluster together


def test_axis_b_varying_output_gives_high_noise_floor() -> None:
    examples = [MineExample(input={}, rendered_prompt="p", output="baseline")]
    call_count = [0]

    def varying_call(model, messages, **kw):
        call_count[0] += 1
        return LLMResponse(
            content=f"unique output {call_count[0]}",
            model=model,
            provider="fake",
            usage=_fake_usage(),
            cost_usd=0.001,
            latency_ms=1.0,
            finish_reason="stop",
        )

    result = mine_contract(
        _mine_input(examples, axis_b_repeats=3),
        call=varying_call,
        entails=_exact_match,  # exact match → each unique output is its own cluster
        budget=BudgetTracker(budget_usd=10.0),
    )
    assert result.noise_floor > 0.0


# ---------------------------------------------------------------------------
# Axis B only noise (not an invariant when absent from Axis A)
# ---------------------------------------------------------------------------


def test_axis_b_only_variance_does_not_create_invariant() -> None:
    """When Axis A outputs are heterogeneous, no invariant should be emitted
    even if Axis B is stable — the invariant must appear in Axis A."""
    examples = [
        MineExample(input={}, rendered_prompt="p", output=json.dumps({"x": 1})),
        MineExample(input={}, rendered_prompt="p", output=json.dumps({"y": 2})),
    ]
    result = mine_contract(
        _mine_input(examples, axis_b_repeats=0),
        call=_make_call(output=json.dumps({"x": 1})),
        entails=_exact_match,
        budget=BudgetTracker(budget_usd=10.0),
    )
    req_keys = [inv for inv in result.invariants if inv.kind == "required_keys"]
    assert not req_keys


# ---------------------------------------------------------------------------
# MinedContract fields
# ---------------------------------------------------------------------------


def test_samples_used_counts_both_axes() -> None:
    examples = [MineExample(input={}, rendered_prompt="p", output="out")]
    result = mine_contract(
        _mine_input(examples, axis_b_repeats=2),
        call=_make_call(),
        entails=_exact_match,
        budget=BudgetTracker(budget_usd=10.0),
    )
    assert result.axis_a_count == 1
    assert result.axis_b_count == 2
    assert result.samples_used == 3


def test_budget_exhausted_skips_axis_b() -> None:
    examples = [MineExample(input={}, rendered_prompt="p", output="out")]
    budget = BudgetTracker(budget_usd=0.001)
    budget.record_spend(0.001)  # pre-exhaust
    result = mine_contract(
        _mine_input(examples, axis_b_repeats=3),
        call=_make_call(),
        entails=_exact_match,
        budget=budget,
    )
    assert result.axis_b_count == 0
    assert result.axis_a_count == 1
