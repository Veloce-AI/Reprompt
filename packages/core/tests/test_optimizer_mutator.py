"""Tests for refract_core.optimizer.mutator — prompt mutation
(generate_prompt_mutations), Prism's critique/refine step
(critique_and_refine), and Prism's optional few-shot selection
(select_few_shot_examples).

No real network calls / no live key needed — every test supplies a fake
``call`` callable directly (same dependency-injection convention as
test_rubric_generator.py / test_judge.py).
"""

from __future__ import annotations

import json

import pytest

from refract_core.deterministic import CheckResult, EvaluationResult
from refract_core.llm.client import LLMResponse
from refract_core.optimizer.mutator import (
    MutationExample,
    PromptMutationError,
    critique_and_refine,
    select_few_shot_examples,
)
from refract_core.scoring import DEFAULT_WEIGHTS, CompositeScore
from refract_core.trace import TokenUsage

PROMPT_TEMPLATE = "Extract the currency and revenue figure from: {{document}}"
TARGET_MODEL = "gemini/gemini-2.0-flash"

EXAMPLES = [
    MutationExample(input={"document": "Q1 revenue was $4.2M USD."}, output='{"currency": "USD", "revenue": 4200000}'),
    MutationExample(input={"document": "Q2 revenue was €3.1M."}, output='{"currency": "EUR", "revenue": 3100000}'),
    MutationExample(input={"document": "Q3 revenue was £900K."}, output='{"currency": "GBP", "revenue": 900000}'),
]

RUBRIC = {
    "deterministic_checks": [{"type": "required_keys", "keys": ["currency", "revenue"]}],
    "judge_criteria": [{"name": "Correct currency", "weight": 1.0, "description": "Uses the right ISO code."}],
}


def _fake_response(
    content: str, *, model: str = "gemini/gemini-2.0-flash", cost_usd: float | None = 0.001, latency_ms: float = 250.0
) -> LLMResponse:
    return LLMResponse(
        content=content,
        model=model,
        provider="gemini",
        usage=TokenUsage(input=200, output=120, thinking=None),
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        finish_reason="stop",
    )


def _make_call(responses: list[LLMResponse]):
    """Returns (call, captured_calls) — `call` yields each response in
    `responses` in order; captures (model, messages, kwargs) per invocation."""
    captured: list[dict] = []
    iterator = iter(responses)

    def call(model, messages, **kwargs):
        captured.append({"model": model, "messages": messages, "kwargs": kwargs})
        return next(iterator)

    return call, captured


def _make_score(*, failing_check: bool = True, judge_score: float | None = None) -> CompositeScore:
    """A realistic, poorly-scoring CompositeScore for critique_and_refine
    tests — one failed required_keys check, mediocre embedding similarity."""
    results = [
        CheckResult(
            id="req-1", type="required_keys", label="Required keys present",
            passed=not failing_check, reason="Missing required key 'revenue'." if failing_check else "All keys present.",
        )
    ]
    evaluation = EvaluationResult(results=results)
    det_score = 0.0 if failing_check else 1.0
    embedding_score = 0.4
    judge_component = judge_score if judge_score is not None else 0.0
    final_score = (
        DEFAULT_WEIGHTS.deterministic * det_score
        + DEFAULT_WEIGHTS.judge * judge_component
        + DEFAULT_WEIGHTS.embedding * embedding_score
    ) / DEFAULT_WEIGHTS.total
    return CompositeScore(
        deterministic=evaluation,
        deterministic_score=det_score,
        embedding_score=embedding_score,
        judge_score=judge_score,
        weights=DEFAULT_WEIGHTS,
        final_score=final_score,
        gated=False,
        gate_reason=None,
        judge_skipped=judge_score is None,
    )


# ---------------------------------------------------------------------------
# critique_and_refine
# ---------------------------------------------------------------------------


def test_critique_and_refine_includes_score_context_in_the_prompt() -> None:
    score = _make_score(failing_check=True)
    response = _fake_response(json.dumps({"critique": "Missing revenue key.", "refined_prompt": PROMPT_TEMPLATE + " Always include revenue."}))
    call, captured = _make_call([response])

    result = critique_and_refine(
        PROMPT_TEMPLATE, score, EXAMPLES, RUBRIC, TARGET_MODEL, call=call,
    )

    assert len(captured) == 1
    user_message = captured[0]["messages"][1]["content"]
    assert "Missing required key 'revenue'" in user_message
    assert result.variants == [PROMPT_TEMPLATE + " Always include revenue."]
    assert result.cost_usd == 0.001


def test_critique_and_refine_retries_once_on_malformed_json() -> None:
    score = _make_score(failing_check=True)
    responses = [
        _fake_response("not valid json", cost_usd=0.001),
        _fake_response(json.dumps({"critique": "ok", "refined_prompt": "refined version"}), cost_usd=0.002),
    ]
    call, captured = _make_call(responses)

    result = critique_and_refine(PROMPT_TEMPLATE, score, EXAMPLES, RUBRIC, TARGET_MODEL, call=call)

    assert len(captured) == 2
    assert result.variants == ["refined version"]
    assert result.cost_usd == pytest.approx(0.003)


def test_critique_and_refine_retries_on_empty_refined_prompt() -> None:
    score = _make_score(failing_check=True)
    responses = [
        _fake_response(json.dumps({"critique": "ok", "refined_prompt": ""})),
        _fake_response(json.dumps({"critique": "ok", "refined_prompt": "a real refinement"})),
    ]
    call, captured = _make_call(responses)

    result = critique_and_refine(PROMPT_TEMPLATE, score, EXAMPLES, RUBRIC, TARGET_MODEL, call=call)

    assert len(captured) == 2
    assert result.variants == ["a real refinement"]


def test_critique_and_refine_raises_after_retry_also_fails() -> None:
    score = _make_score(failing_check=True)
    responses = [_fake_response("still not json"), _fake_response("also not json")]
    call, captured = _make_call(responses)

    with pytest.raises(PromptMutationError):
        critique_and_refine(PROMPT_TEMPLATE, score, EXAMPLES, RUBRIC, TARGET_MODEL, call=call)

    assert len(captured) == 2  # exactly one retry, no third attempt


def test_critique_and_refine_uses_target_model_when_no_mutator_model_given() -> None:
    score = _make_score(failing_check=True)
    response = _fake_response(json.dumps({"critique": "ok", "refined_prompt": "refined"}))
    call, captured = _make_call([response])

    critique_and_refine(PROMPT_TEMPLATE, score, EXAMPLES, RUBRIC, TARGET_MODEL, call=call)

    assert captured[0]["model"] == TARGET_MODEL


# ---------------------------------------------------------------------------
# select_few_shot_examples
# ---------------------------------------------------------------------------


def test_select_few_shot_examples_only_returns_real_examples() -> None:
    # Model picks indices 1 and 3 (1-based, as instructed) - never invents text.
    response = _fake_response(json.dumps({"indices": [1, 3]}))
    call, captured = _make_call([response])

    selected = select_few_shot_examples(PROMPT_TEMPLATE, EXAMPLES, call=call, model=TARGET_MODEL, max_examples=2)

    assert selected == [EXAMPLES[0], EXAMPLES[2]]
    assert len(captured) == 1


def test_select_few_shot_examples_drops_out_of_range_indices() -> None:
    response = _fake_response(json.dumps({"indices": [1, 99, -1]}))
    call, _captured = _make_call([response])

    selected = select_few_shot_examples(PROMPT_TEMPLATE, EXAMPLES, call=call, model=TARGET_MODEL, max_examples=2)

    assert selected == [EXAMPLES[0]]


def test_select_few_shot_examples_respects_max_examples() -> None:
    response = _fake_response(json.dumps({"indices": [1, 2, 3]}))
    call, _captured = _make_call([response])

    selected = select_few_shot_examples(PROMPT_TEMPLATE, EXAMPLES, call=call, model=TARGET_MODEL, max_examples=2)

    assert len(selected) == 2


def test_select_few_shot_examples_falls_back_when_model_output_unusable() -> None:
    # Both the initial attempt and the retry are unusable (empty indices).
    responses = [_fake_response(json.dumps({"indices": []})), _fake_response("not json at all")]
    call, captured = _make_call(responses)

    selected = select_few_shot_examples(PROMPT_TEMPLATE, EXAMPLES, call=call, model=TARGET_MODEL, max_examples=2)

    assert selected == EXAMPLES[:2]  # graceful fallback, never raises
    assert len(captured) == 2


def test_select_few_shot_examples_returns_all_when_fewer_than_max() -> None:
    call, captured = _make_call([])  # must never be called - short-circuits before any call

    selected = select_few_shot_examples(PROMPT_TEMPLATE, EXAMPLES[:1], call=call, model=TARGET_MODEL, max_examples=2)

    assert selected == EXAMPLES[:1]
    assert len(captured) == 0
