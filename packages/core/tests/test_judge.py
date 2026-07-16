"""Tests for the pairwise LLM judge (reprompt_core.judge).

No real network calls / no live key needed
---------------------------------------------
Same story as ``test_llm_client.py``: there is no BYOK key configured in
this environment. Every test here mocks
``reprompt_core.llm.client.complete`` directly via monkeypatch (per the task
brief, "same pattern used in the existing llm client tests") — judge.py
calls it as ``llm_client.complete(...)`` (a module-attribute lookup, not a
bound `from ... import complete`), so patching the attribute on
``reprompt_core.llm.client`` is visible to judge.py regardless of which
import path a test patches through; both point at the same function object.
"""

from __future__ import annotations

import json

import pytest

from reprompt_core.judge import (
    DEFAULT_DISAGREEMENT_THRESHOLD,
    JudgeCriterion,
    JudgeResponseError,
    JudgeResult,
    judge_pairwise,
    judge_single_pass,
)
from reprompt_core.llm.client import LLMResponse
from reprompt_core.trace import TokenUsage

BENCHMARK = "The invoice total is $1,204.50, due on the 15th of next month."
CANDIDATE = "Invoice total: $1,204.50. Payment due the 15th of next month."

CRITERIA = [
    JudgeCriterion(name="Covers all key entities", weight=0.6, description="Mentions the amount and due date."),
    JudgeCriterion(name="Tone: formal and concise", weight=0.4, description="No filler, no casual phrasing."),
]


def _fake_llm_response(content: str, *, model: str = "claude-sonnet-4-5", cost_usd: float | None = 0.001) -> LLMResponse:
    return LLMResponse(
        content=content,
        model=model,
        provider="anthropic",
        usage=TokenUsage(input=100, output=50, thinking=None),
        cost_usd=cost_usd,
        latency_ms=250.0,
        finish_reason="stop",
    )


def _uniform_score_content(criteria: list[JudgeCriterion], score: float, reasoning: str = "Looks equivalent.") -> str:
    return json.dumps(
        {
            "criteria": [
                {"name": c.name, "score": score, "reasoning": reasoning}
                for c in criteria
            ]
        }
    )


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def test_prompt_includes_criteria_names_weights_and_both_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_calls: list[dict] = []

    def fake_complete(model, messages, **kwargs):
        captured_calls.append({"model": model, "messages": messages, "kwargs": kwargs})
        return _fake_llm_response(_uniform_score_content(CRITERIA, 0.9))

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    judge_pairwise(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")

    assert len(captured_calls) == 2
    for call in captured_calls:
        user_content = call["messages"][1]["content"]
        assert BENCHMARK in user_content
        assert CANDIDATE in user_content
        for criterion in CRITERIA:
            assert criterion.name in user_content
            assert criterion.description in user_content
            assert f"weight={criterion.weight:g}" in user_content
        # response_format was requested for structured output, per the task brief.
        assert "response_format" in call["kwargs"]


def test_prompt_includes_original_input_when_given(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []

    def fake_complete(model, messages, **kwargs):
        captured.append({"messages": messages})
        return _fake_llm_response(_uniform_score_content(CRITERIA, 0.8))

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    judge_pairwise(
        BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5", input={"customer_id": "cust_4821"}
    )

    for call in captured:
        assert "cust_4821" in call["messages"][1]["content"]


def test_prompt_omits_input_section_when_not_given(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []

    def fake_complete(model, messages, **kwargs):
        captured.append({"messages": messages})
        return _fake_llm_response(_uniform_score_content(CRITERIA, 0.8))

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    judge_pairwise(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")

    for call in captured:
        assert "ORIGINAL INPUT" not in call["messages"][1]["content"]


def test_calls_complete_exactly_twice_per_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = 0

    def fake_complete(model, messages, **kwargs):
        nonlocal call_count
        call_count += 1
        return _fake_llm_response(_uniform_score_content(CRITERIA, 0.75))

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    judge_pairwise(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")

    assert call_count == 2


# ---------------------------------------------------------------------------
# Position swap
# ---------------------------------------------------------------------------


def test_position_swap_makes_two_distinct_calls_with_swapped_content(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_complete(model, messages, **kwargs):
        captured.append(messages[1]["content"])
        return _fake_llm_response(_uniform_score_content(CRITERIA, 0.9))

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    judge_pairwise(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")

    assert len(captured) == 2
    first_call, second_call = captured

    # Order 1: benchmark presented first (OUTPUT 1), candidate second (OUTPUT 2).
    assert first_call.index("OUTPUT 1") < first_call.index(BENCHMARK) < first_call.index("OUTPUT 2") < first_call.index(CANDIDATE)
    # Order 2: swapped — candidate first, benchmark second.
    assert second_call.index("OUTPUT 1") < second_call.index(CANDIDATE) < second_call.index("OUTPUT 2") < second_call.index(BENCHMARK)

    # The two calls must actually differ (this is the "distinct calls" part).
    assert first_call != second_call

    # Both calls still label roles explicitly and unambiguously in both orders
    # (the role labels never swap, only the presentation order does).
    for content in captured:
        assert "BENCHMARK OUTPUT" in content
        assert "CANDIDATE OUTPUT" in content


# ---------------------------------------------------------------------------
# Combining results
# ---------------------------------------------------------------------------


def test_combines_scores_by_averaging_across_orderings(monkeypatch: pytest.MonkeyPatch) -> None:
    """When both orderings agree, the combined per-criterion score equals that
    shared value and overall_score is the weight-normalized average."""

    def fake_complete(model, messages, **kwargs):
        return _fake_llm_response(_uniform_score_content(CRITERIA, 0.8, reasoning="Matches well."))

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    result = judge_pairwise(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")

    assert isinstance(result, JudgeResult)
    assert result.overall_score == pytest.approx(0.8, abs=1e-9)
    assert len(result.criteria) == 2
    for judgment in result.criteria:
        assert judgment.score == pytest.approx(0.8, abs=1e-9)
        assert judgment.order_disagreement == pytest.approx(0.0, abs=1e-9)
    assert result.disagreement == pytest.approx(0.0, abs=1e-9)
    assert result.low_confidence is False


def test_overall_score_respects_criterion_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    """Criterion A (weight 0.6) scores 1.0, criterion B (weight 0.4) scores 0.0
    in both orderings -> weighted overall must be 0.6, not a plain 0.5 average."""

    def fake_complete(model, messages, **kwargs):
        content = json.dumps(
            {
                "criteria": [
                    {"name": CRITERIA[0].name, "score": 1.0, "reasoning": "Perfect."},
                    {"name": CRITERIA[1].name, "score": 0.0, "reasoning": "Wrong tone."},
                ]
            }
        )
        return _fake_llm_response(content)

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    result = judge_pairwise(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")

    assert result.overall_score == pytest.approx(0.6, abs=1e-9)


def test_combined_reasoning_includes_both_orderings_when_they_differ(monkeypatch: pytest.MonkeyPatch) -> None:
    call_index = 0

    def fake_complete(model, messages, **kwargs):
        nonlocal call_index
        call_index += 1
        reasoning = "Order-1 reasoning." if call_index == 1 else "Order-2 reasoning."
        return _fake_llm_response(_uniform_score_content(CRITERIA, 0.7, reasoning=reasoning))

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    result = judge_pairwise(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")

    for judgment in result.criteria:
        assert "Order-1 reasoning." in judgment.reasoning
        assert "Order-2 reasoning." in judgment.reasoning


def test_cost_and_latency_are_summed_across_both_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_complete(model, messages, **kwargs):
        return _fake_llm_response(_uniform_score_content(CRITERIA, 0.5), cost_usd=0.002)

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    result = judge_pairwise(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")

    assert result.cost_usd == pytest.approx(0.004, abs=1e-9)
    assert result.latency_ms == pytest.approx(500.0, abs=1e-9)


def test_cost_none_when_both_calls_report_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_complete(model, messages, **kwargs):
        return _fake_llm_response(_uniform_score_content(CRITERIA, 0.5), cost_usd=None)

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    result = judge_pairwise(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")

    assert result.cost_usd is None


# ---------------------------------------------------------------------------
# Disagreement / low-confidence
# ---------------------------------------------------------------------------


def test_high_disagreement_between_orderings_is_flagged_low_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Order 1 scores everything 0.95 (looks great); order 2 scores everything
    0.1 (looks terrible) purely as a function of presentation order — this is
    exactly the position-bias failure mode position-swapping exists to catch."""
    call_index = 0

    def fake_complete(model, messages, **kwargs):
        nonlocal call_index
        call_index += 1
        score = 0.95 if call_index == 1 else 0.1
        return _fake_llm_response(_uniform_score_content(CRITERIA, score))

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    result = judge_pairwise(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")

    assert result.disagreement == pytest.approx(0.85, abs=1e-9)
    assert result.disagreement > DEFAULT_DISAGREEMENT_THRESHOLD
    assert result.low_confidence is True
    # The score is still returned (averaged), not discarded.
    assert result.overall_score == pytest.approx((0.95 + 0.1) / 2, abs=1e-9)


def test_disagreement_uses_max_not_mean_across_criteria(monkeypatch: pytest.MonkeyPatch) -> None:
    """One criterion disagrees wildly, the other agrees perfectly — disagreement
    must reflect the worst criterion (max), not be diluted by averaging."""
    call_index = 0

    def fake_complete(model, messages, **kwargs):
        nonlocal call_index
        call_index += 1
        if call_index == 1:
            scores = {CRITERIA[0].name: 1.0, CRITERIA[1].name: 0.5}
        else:
            scores = {CRITERIA[0].name: 0.0, CRITERIA[1].name: 0.5}
        content = json.dumps(
            {"criteria": [{"name": name, "score": score, "reasoning": "r"} for name, score in scores.items()]}
        )
        return _fake_llm_response(content)

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    result = judge_pairwise(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")

    assert result.disagreement == pytest.approx(1.0, abs=1e-9)  # from criterion 0
    assert result.low_confidence is True


def test_disagreement_threshold_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    call_index = 0

    def fake_complete(model, messages, **kwargs):
        nonlocal call_index
        call_index += 1
        score = 0.6 if call_index == 1 else 0.5
        return _fake_llm_response(_uniform_score_content(CRITERIA, score))

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    # disagreement is 0.1: below a strict threshold, above a very loose one.
    strict = judge_pairwise(
        BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5", disagreement_threshold=0.05
    )
    assert strict.low_confidence is True

    call_index = 0
    loose = judge_pairwise(
        BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5", disagreement_threshold=0.5
    )
    assert loose.low_confidence is False


# ---------------------------------------------------------------------------
# Malformed / off-schema responses
# ---------------------------------------------------------------------------


def test_invalid_json_response_raises_judge_response_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_complete(model, messages, **kwargs):
        return _fake_llm_response("not json at all")

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    with pytest.raises(JudgeResponseError, match="doesn't match the expected JSON schema"):
        judge_pairwise(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")


def test_response_missing_a_criterion_raises_judge_response_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_complete(model, messages, **kwargs):
        content = json.dumps({"criteria": [{"name": CRITERIA[0].name, "score": 0.9, "reasoning": "ok"}]})
        return _fake_llm_response(content)

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    with pytest.raises(JudgeResponseError, match=CRITERIA[1].name):
        judge_pairwise(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")


def test_criterion_name_matching_is_case_and_whitespace_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_complete(model, messages, **kwargs):
        content = json.dumps(
            {
                "criteria": [
                    {"name": f"  {c.name.upper()}  ", "score": 0.7, "reasoning": "ok"}
                    for c in CRITERIA
                ]
            }
        )
        return _fake_llm_response(content)

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    result = judge_pairwise(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")

    # Result preserves the caller's original (canonical) criterion names.
    assert {j.name for j in result.criteria} == {c.name for c in CRITERIA}


# ---------------------------------------------------------------------------
# Input coercion / validation
# ---------------------------------------------------------------------------


def test_accepts_plain_dicts_for_judge_criteria(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_criteria = [
        {"name": "Covers all key entities", "weight": 0.6, "description": "..."},
        {"name": "Tone: formal and concise", "weight": 0.4, "description": "..."},
    ]

    def fake_complete(model, messages, **kwargs):
        content = json.dumps(
            {"criteria": [{"name": c["name"], "score": 0.8, "reasoning": "ok"} for c in raw_criteria]}
        )
        return _fake_llm_response(content)

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    result = judge_pairwise(BENCHMARK, CANDIDATE, raw_criteria, model="claude-sonnet-4-5")

    assert result.overall_score == pytest.approx(0.8, abs=1e-9)


def test_empty_judge_criteria_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def should_not_be_called(model, messages, **kwargs):
        raise AssertionError("complete() must not be called with zero criteria")

    monkeypatch.setattr("reprompt_core.llm.client.complete", should_not_be_called)

    with pytest.raises(ValueError, match="at least one judge criterion"):
        judge_pairwise(BENCHMARK, CANDIDATE, [], model="claude-sonnet-4-5")


# ---------------------------------------------------------------------------
# judge_single_pass — the no-swap judge call used by Prism's critique-ranking
# pass (loop.py's _optimize_stage_prism, see DEV_TRACKER.md's Phase 1
# quality-fixes note)
# ---------------------------------------------------------------------------


def test_judge_single_pass_makes_exactly_one_call_with_no_disagreement(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []

    def fake_complete(model, messages, **kwargs):
        captured.append({"messages": messages})
        return _fake_llm_response(_uniform_score_content(CRITERIA, 0.7, "Reasonably close."))

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    result = judge_single_pass(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")

    assert len(captured) == 1  # no position-swap - one call, not two
    assert result.overall_score == pytest.approx(0.7)
    assert result.disagreement == 0.0
    assert result.low_confidence is False
    assert all(c.reasoning == "Reasonably close." for c in result.criteria)


def test_judge_single_pass_retries_once_on_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            _fake_llm_response("not valid json", cost_usd=0.001),
            _fake_llm_response(_uniform_score_content(CRITERIA, 0.6), cost_usd=0.002),
        ]
    )

    def fake_complete(model, messages, **kwargs):
        return next(responses)

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    result = judge_single_pass(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")

    assert result.overall_score == pytest.approx(0.6)


def test_judge_single_pass_raises_after_retry_also_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = {"n": 0}

    def fake_complete(model, messages, **kwargs):
        call_count["n"] += 1
        return _fake_llm_response("still not json", cost_usd=0.001)

    monkeypatch.setattr("reprompt_core.llm.client.complete", fake_complete)

    with pytest.raises(JudgeResponseError) as exc_info:
        judge_single_pass(BENCHMARK, CANDIDATE, CRITERIA, model="claude-sonnet-4-5")

    assert call_count["n"] == 2  # exactly one retry, no third attempt
    # The failed response's cost is still recoverable for budget accounting.
    assert exc_info.value.response is not None
    assert exc_info.value.response.cost_usd == pytest.approx(0.001)
