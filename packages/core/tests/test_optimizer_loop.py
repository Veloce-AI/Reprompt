"""Tests for reprompt_core.optimizer.loop — run_sweep_for_stage (shared,
backend-agnostic), the "simple" strategy, and the "prism" strategy
(multi-round mutate/critique/refine).

No real network calls / no live key needed — every test supplies a fake
``call`` callable. Embedding similarity is monkeypatched in tests that
need to control scores precisely (the plateau test) since it otherwise
runs a real local model — same convention as this suite's other tests
that avoid real network calls, applied here to avoid real-model-inference
flakiness for an exact-threshold test.
"""

from __future__ import annotations

import json

import pytest

from reprompt_core.budget import BudgetTracker
from reprompt_core.llm.client import LLMResponse
from reprompt_core.optimizer.loop import (
    PLATEAU_EPSILON,
    OptimizationResult,
    StageOptimizationInput,
    run_optimizer,
)
from reprompt_core.optimizer.mutator import MutationExample
from reprompt_core.trace import TokenUsage

TARGET_MODEL = "gemini/gemini-2.0-flash"
JUDGE_MODEL = "gemini/gemini-2.0-flash"

EXAMPLES = [
    {"input": {"document": "Q1 revenue was $4.2M USD."}, "output": '{"currency": "USD", "revenue": 4200000}'},
]

# Empty rubric throughout most tests: deterministic_score is vacuously 1.0
# (no checks configured) and no judge_criteria means the judge is never
# actually called (see scoring.score_candidate's run_judge gating) - this
# keeps cheap_score fully controlled by embedding_similarity alone, and
# keeps these tests independent of judge.py's own behavior (tested
# elsewhere).
EMPTY_RUBRIC: dict = {}


def _stage(stage_id: int = 1, examples: list | None = None) -> StageOptimizationInput:
    return StageOptimizationInput(
        stage_id=stage_id,
        stage_name=f"Stage {stage_id}",
        original_prompt_template="Extract data from: {{document}}",
        target_model=TARGET_MODEL,
        rubric=EMPTY_RUBRIC,
        examples=examples if examples is not None else EXAMPLES,
    )


def _fake_response(content: str, *, cost_usd: float | None = 0.001, latency_ms: float = 100.0) -> LLMResponse:
    return LLMResponse(
        content=content, model=TARGET_MODEL, provider="gemini",
        usage=TokenUsage(input=100, output=50, thinking=None),
        cost_usd=cost_usd, latency_ms=latency_ms, finish_reason="stop",
    )


def _make_call(*, mutation_variants=None, refined_text="a refined prompt", sweep_output='{"currency": "USD", "revenue": 4200000}'):
    """A single fake `call` that dispatches based on `response_format`:
    structured (Pydantic class) calls are mutation/critique/few-shot
    requests (distinguished by keywords in the system prompt, since those
    are this module's real, stable distinguishing text); anything else is
    a plain sweep/cheap-score completion call. Returns (call, captured)."""
    captured: list[dict] = []

    def call(model, messages, **kwargs):
        captured.append({"model": model, "messages": messages, "kwargs": kwargs})
        response_format = kwargs.get("response_format")
        system_content = messages[0]["content"] if messages else ""
        if isinstance(response_format, type):
            if "critique" in system_content.lower():
                return _fake_response(json.dumps({"critique": "needs work", "refined_prompt": refined_text}))
            if "indices" in system_content.lower():
                return _fake_response(json.dumps({"indices": [1]}))
            variants = mutation_variants if mutation_variants is not None else ["variant A"]
            return _fake_response(json.dumps({"variants": variants}))
        return _fake_response(sweep_output)

    return call, captured


# ---------------------------------------------------------------------------
# "simple" strategy
# ---------------------------------------------------------------------------


def test_simple_strategy_runs_and_selects_a_winner() -> None:
    call, captured = _make_call()
    budget = BudgetTracker(budget_usd=10.0)

    result = run_optimizer(
        [_stage()], call=call, budget=budget, judge_model=JUDGE_MODEL,
        strategy="simple", max_sweep_candidates_per_prompt=1, parity_threshold=0.0,
    )

    assert len(result.stage_results) == 1
    stage_result = result.stage_results[0]
    assert stage_result.best is not None
    assert stage_result.error is None
    assert any(isinstance(c["kwargs"].get("response_format"), type) for c in captured)  # mutation call happened


def test_simple_strategy_degrades_gracefully_when_mutation_fails() -> None:
    def call(model, messages, **kwargs):
        response_format = kwargs.get("response_format")
        if isinstance(response_format, type):
            return _fake_response("not valid json")  # both attempts fail -> PromptMutationError
        return _fake_response('{"currency": "USD", "revenue": 4200000}')

    budget = BudgetTracker(budget_usd=10.0)
    result = run_optimizer(
        [_stage()], call=call, budget=budget, judge_model=JUDGE_MODEL,
        strategy="simple", max_sweep_candidates_per_prompt=1, parity_threshold=0.0,
    )

    stage_result = result.stage_results[0]
    assert stage_result.error is None  # mutation failure is not a stage failure
    assert stage_result.best is not None  # still ran the sweep on the original prompt alone
    assert stage_result.best.params["source"] == "original"


# ---------------------------------------------------------------------------
# "prism" strategy
# ---------------------------------------------------------------------------


def test_prism_strategy_produces_a_refined_candidate() -> None:
    call, captured = _make_call(mutation_variants=["mutated variant"], refined_text="a genuinely refined prompt")
    budget = BudgetTracker(budget_usd=10.0)

    result = run_optimizer(
        [_stage()], call=call, budget=budget, judge_model=JUDGE_MODEL,
        strategy="prism", max_sweep_candidates_per_prompt=1, parity_threshold=0.0,
        num_prompt_variants=1, max_refine_rounds=1,
    )

    stage_result = result.stage_results[0]
    assert stage_result.error is None
    assert stage_result.best is not None
    # A critique/refine call happened (system prompt contains "critique").
    critique_calls = [c for c in captured if "critique" in c["messages"][0]["content"].lower()]
    assert len(critique_calls) >= 1


def test_prism_include_few_shot_attaches_examples_to_the_winner() -> None:
    many_examples = [
        {"input": {"document": f"doc {i}"}, "output": '{"currency": "USD", "revenue": 100}'} for i in range(5)
    ]
    call, _captured = _make_call(mutation_variants=["mutated variant"])
    budget = BudgetTracker(budget_usd=10.0)

    result = run_optimizer(
        [_stage(examples=many_examples)], call=call, budget=budget, judge_model=JUDGE_MODEL,
        strategy="prism", max_sweep_candidates_per_prompt=1, parity_threshold=0.0,
        num_prompt_variants=1, max_refine_rounds=1, include_few_shot=True,
    )

    stage_result = result.stage_results[0]
    assert stage_result.best is not None
    assert stage_result.best.few_shot_examples is not None
    assert len(stage_result.best.few_shot_examples) <= 2


def test_simple_strategy_is_the_default_and_never_calls_critique() -> None:
    call, captured = _make_call(mutation_variants=["variant A"])
    budget = BudgetTracker(budget_usd=10.0)

    run_optimizer(
        [_stage()], call=call, budget=budget, judge_model=JUDGE_MODEL,
        max_sweep_candidates_per_prompt=1, parity_threshold=0.0,  # strategy omitted - defaults to "simple"
    )

    critique_calls = [c for c in captured if "critique" in c["messages"][0]["content"].lower()]
    assert critique_calls == []


def test_prism_plateau_early_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Round 2's refined candidate scores no better than its round-1
    parent (both mocked to the same embedding similarity) - assert no
    third round of refinement is attempted for it, even though
    max_refine_rounds allows more."""
    embedding_scores = iter([0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3])  # always plateaued
    monkeypatch.setattr(
        "reprompt_core.optimizer.loop.embedding_similarity",
        lambda benchmark, candidate, **kw: next(embedding_scores, 0.3),
    )

    call, captured = _make_call(mutation_variants=["mutated variant"], refined_text="refined but not better")
    budget = BudgetTracker(budget_usd=10.0)

    run_optimizer(
        [_stage()], call=call, budget=budget, judge_model=JUDGE_MODEL,
        strategy="prism", max_sweep_candidates_per_prompt=1, parity_threshold=0.0,
        num_prompt_variants=1, max_refine_rounds=3,  # would allow 3 rounds if not plateaued
    )

    critique_calls = [c for c in captured if "critique" in c["messages"][0]["content"].lower()]
    # Round 1 refines both round-1 candidates (original + the one mutation) = 2 critique calls.
    # Round 2 would re-rank the 2 refined candidates; since neither improved over its parent
    # (PLATEAU_EPSILON not cleared), round 2 must NOT issue any further critique calls.
    assert len(critique_calls) == 2


def test_prism_budget_hard_stop_mid_loop() -> None:
    call, _captured = _make_call(mutation_variants=["variant A", "variant B", "variant C"])
    budget = BudgetTracker(budget_usd=0.0015)  # exhausts after ~1-2 calls at cost_usd=0.001 each

    result = run_optimizer(
        [_stage()], call=call, budget=budget, judge_model=JUDGE_MODEL,
        strategy="prism", max_sweep_candidates_per_prompt=6, parity_threshold=0.0,
        num_prompt_variants=3, max_refine_rounds=2,
    )

    assert budget.is_exhausted
    assert result.stopped_early is True
    # Still returns a well-formed result for whatever was attempted, no crash.
    assert isinstance(result, OptimizationResult)


def test_prism_one_stage_failure_does_not_abort_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_embedding_similarity(*args, **kwargs):
        raise RuntimeError("simulated unexpected failure")

    monkeypatch.setattr("reprompt_core.optimizer.loop.embedding_similarity", broken_embedding_similarity)

    call, _captured = _make_call(mutation_variants=["variant A"])
    budget = BudgetTracker(budget_usd=10.0)

    stages = [_stage(stage_id=1), _stage(stage_id=2)]
    result = run_optimizer(
        stages, call=call, budget=budget, judge_model=JUDGE_MODEL,
        strategy="prism", max_sweep_candidates_per_prompt=1, parity_threshold=0.0,
        num_prompt_variants=1, max_refine_rounds=1,
    )

    assert len(result.stage_results) == 2
    # Both stages hit the broken embedding call during Prism's cheap-score
    # step; both must be recorded as failed, not raised - the run itself
    # must still complete and report on every stage.
    assert all(r.error is not None for r in result.stage_results)
