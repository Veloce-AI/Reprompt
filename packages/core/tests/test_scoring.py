"""Tests for the composite scorer (reprompt_core.scoring).

Model choice for the end-to-end test
----------------------------------------
Like ``test_embedding.py``, the end-to-end test in this module uses the
small, fast ``sentence-transformers/all-MiniLM-L6-v2`` model instead of the
product-default bge-m3, via ``score_candidate``'s ``embedding_model_name``
override — production code that doesn't pass it still gets bge-m3.
"""

from __future__ import annotations

import pytest

from reprompt_core.deterministic import (
    EvaluationResult,
    JsonSchemaCheck,
    LengthBoundsCheck,
    RequiredKeysCheck,
    evaluate_deterministic_checks,
)
from reprompt_core.scoring import (
    DEFAULT_MIN_DETERMINISTIC_SCORE_FOR_JUDGE,
    DEFAULT_WEIGHTS,
    CompositeScore,
    ScoreWeights,
    compute_composite_score,
    deterministic_score,
    score_candidate,
    should_run_judge,
)

TEST_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _det_result(*, passed: list[bool], types: list[str] | None = None) -> EvaluationResult:
    """Build an EvaluationResult with the given pass/fail pattern, without
    needing real check objects — scoring.py only reads .results[i].passed/.type."""
    from reprompt_core.deterministic import CheckResult

    types = types or ["required_keys"] * len(passed)
    return EvaluationResult(
        results=[
            CheckResult(id=f"c{i}", type=t, label=f"check {i}", passed=p, reason="ok" if p else "failed")
            for i, (p, t) in enumerate(zip(passed, types))
        ]
    )


# ---------------------------------------------------------------------------
# deterministic_score
# ---------------------------------------------------------------------------


def test_deterministic_score_is_fraction_passed() -> None:
    result = _det_result(passed=[True, True, False, True])
    assert deterministic_score(result) == pytest.approx(0.75)


def test_deterministic_score_vacuously_one_for_no_checks() -> None:
    assert deterministic_score(EvaluationResult(results=[])) == 1.0


def test_deterministic_score_zero_when_all_fail() -> None:
    result = _det_result(passed=[False, False])
    assert deterministic_score(result) == 0.0


# ---------------------------------------------------------------------------
# should_run_judge — the "gate before spending judge tokens" logic
# ---------------------------------------------------------------------------


def test_should_run_judge_true_when_all_checks_pass() -> None:
    result = _det_result(passed=[True, True, True])
    should_run, reason = should_run_judge(result)
    assert should_run is True
    assert reason is None


def test_should_run_judge_true_with_no_checks_configured() -> None:
    should_run, reason = should_run_judge(EvaluationResult(results=[]))
    assert should_run is True
    assert reason is None


def test_should_run_judge_false_below_min_deterministic_score() -> None:
    # 1/3 passed = 0.33, below the default 0.5 threshold.
    result = _det_result(passed=[True, False, False])
    should_run, reason = should_run_judge(result)
    assert should_run is False
    assert "33%" in reason
    assert "threshold" in reason


def test_should_run_judge_respects_custom_threshold() -> None:
    result = _det_result(passed=[True, False, False])  # 33%
    should_run, _ = should_run_judge(result, min_deterministic_score=0.2)
    assert should_run is True


def test_should_run_judge_false_on_hard_gate_regardless_of_overall_fraction() -> None:
    # 3/4 passed overall (75%, well above the default threshold) but the one
    # failure is a json_schema (hard gate) check.
    result = _det_result(
        passed=[True, True, True, False],
        types=["required_keys", "regex", "length_bounds", "json_schema"],
    )
    should_run, reason = should_run_judge(result)
    assert should_run is False
    assert "Hard gate failed" in reason


# ---------------------------------------------------------------------------
# compute_composite_score — the weighted formula
# ---------------------------------------------------------------------------


def test_full_formula_with_all_three_components_present() -> None:
    det_result = _det_result(passed=[True, True, True, False])  # 0.75
    weights = ScoreWeights(deterministic=0.3, judge=0.4, embedding=0.3)

    score = compute_composite_score(det_result, embedding_sim=0.8, judge_score=0.9, weights=weights)

    expected = 0.3 * 0.75 + 0.4 * 0.9 + 0.3 * 0.8
    assert score.final_score == pytest.approx(expected, abs=1e-9)
    assert score.deterministic_score == pytest.approx(0.75)
    assert score.embedding_score == pytest.approx(0.8)
    assert score.judge_score == pytest.approx(0.9)
    assert score.gated is False
    assert score.gate_reason is None
    assert score.judge_skipped is False
    assert isinstance(score, CompositeScore)


def test_weights_are_normalized_when_they_dont_sum_to_one() -> None:
    det_result = _det_result(passed=[True])  # 1.0
    weights = ScoreWeights(deterministic=1, judge=1, embedding=1)  # sums to 3

    score = compute_composite_score(det_result, embedding_sim=1.0, judge_score=1.0, weights=weights)

    assert score.final_score == pytest.approx(1.0, abs=1e-9)


def test_default_weights_are_used_when_not_specified() -> None:
    det_result = _det_result(passed=[True])
    score = compute_composite_score(det_result, embedding_sim=1.0, judge_score=1.0)
    assert score.weights == DEFAULT_WEIGHTS
    assert score.final_score == pytest.approx(1.0, abs=1e-9)


def test_missing_judge_score_contributes_zero_and_flags_judge_skipped() -> None:
    det_result = _det_result(passed=[True])  # det_score = 1.0
    weights = ScoreWeights(deterministic=1, judge=1, embedding=1)

    score = compute_composite_score(det_result, embedding_sim=1.0, judge_score=None, weights=weights)

    # (1*1.0 + 1*0.0 + 1*1.0) / 3 = 2/3
    assert score.final_score == pytest.approx(2 / 3, abs=1e-9)
    assert score.judge_skipped is True
    assert score.judge_score is None


def test_hard_gate_forces_zero_final_score_regardless_of_weights() -> None:
    det_result = _det_result(passed=[True, False], types=["required_keys", "json_schema"])
    # Weights that would otherwise make embedding/judge dominate.
    weights = ScoreWeights(deterministic=0.01, judge=0.5, embedding=0.49)

    score = compute_composite_score(det_result, embedding_sim=1.0, judge_score=1.0, weights=weights)

    assert score.final_score == 0.0
    assert score.gated is True
    assert "json_schema" in score.gate_reason or "Hard gate failed" in score.gate_reason
    # Component scores are still recorded for transparency/debugging even
    # though they don't drive final_score.
    assert score.embedding_score == pytest.approx(1.0)
    assert score.judge_score == pytest.approx(1.0)


def test_zero_total_weight_raises_value_error() -> None:
    det_result = _det_result(passed=[True])
    weights = ScoreWeights(deterministic=0, judge=0, embedding=0)
    with pytest.raises(ValueError, match="at least one positive weight"):
        compute_composite_score(det_result, embedding_sim=1.0, judge_score=1.0, weights=weights)


def test_composite_score_carries_the_full_deterministic_breakdown_for_ui() -> None:
    det_result = _det_result(passed=[True, False])
    score = compute_composite_score(det_result, embedding_sim=0.5, judge_score=0.5)
    assert score.deterministic is det_result
    assert len(score.deterministic.results) == 2


# ---------------------------------------------------------------------------
# score_candidate — end to end, real deterministic.py + embedding.py,
# mocked judge score (this is the test the task brief calls out explicitly)
# ---------------------------------------------------------------------------


def test_score_candidate_end_to_end_with_mocked_judge_score() -> None:
    benchmark_output = '{"currency": "USD", "revenue": 4200000}'
    candidate_output = '{"currency": "USD", "revenue": 4200000}'
    checks = [
        RequiredKeysCheck(keys=["currency", "revenue"]),
        LengthBoundsCheck(min_length=5, max_length=200),
    ]

    score = score_candidate(
        benchmark_output=benchmark_output,
        candidate_output=candidate_output,
        deterministic_checks=checks,
        embedding_model_name=TEST_EMBEDDING_MODEL,
        judge_score=0.92,  # mocked — no real judge/LLM call made
    )

    assert isinstance(score, CompositeScore)
    # Real deterministic.py: both checks pass on identical, well-formed output.
    assert score.deterministic_score == 1.0
    assert score.deterministic.passed is True
    # Real embedding.py: identical strings score ~1.0.
    assert score.embedding_score == pytest.approx(1.0, abs=1e-3)
    assert score.judge_score == pytest.approx(0.92)
    assert score.judge_skipped is False
    assert score.gated is False
    # Weighted formula actually ran with real component scores.
    expected = (
        DEFAULT_WEIGHTS.deterministic * 1.0
        + DEFAULT_WEIGHTS.judge * 0.92
        + DEFAULT_WEIGHTS.embedding * score.embedding_score
    ) / DEFAULT_WEIGHTS.total
    assert score.final_score == pytest.approx(expected, abs=1e-6)


def test_score_candidate_run_judge_callable_is_invoked_when_gate_passes() -> None:
    benchmark_output = "Quarterly revenue grew 12% on strong enterprise renewals."
    candidate_output = "Revenue grew 12% this quarter, driven by enterprise renewals."
    checks = [LengthBoundsCheck(min_length=5, max_length=500)]

    calls = {"count": 0}

    def fake_run_judge() -> float:
        calls["count"] += 1
        return 0.85

    score = score_candidate(
        benchmark_output=benchmark_output,
        candidate_output=candidate_output,
        deterministic_checks=checks,
        embedding_model_name=TEST_EMBEDDING_MODEL,
        run_judge=fake_run_judge,
    )

    assert calls["count"] == 1
    assert score.judge_score == pytest.approx(0.85)


def test_score_candidate_gate_skips_run_judge_callable_to_save_tokens() -> None:
    """The central 'gate before spending judge tokens' behavior: deterministic
    checks fail badly enough that should_run_judge() says no, so the
    (expensive) run_judge callable must never be invoked."""
    benchmark_output = "The order ships tomorrow."
    candidate_output = "garbled unrelated nonsense output"
    # Two required_keys-style checks against non-JSON output both fail ->
    # deterministic_score = 0.0, well below the default 0.5 gate threshold.
    checks = [
        RequiredKeysCheck(keys=["order_id"]),
        RequiredKeysCheck(keys=["ship_date"]),
    ]

    def should_not_be_called() -> float:
        raise AssertionError("run_judge must not be called when the gate says skip")

    score = score_candidate(
        benchmark_output=benchmark_output,
        candidate_output=candidate_output,
        deterministic_checks=checks,
        embedding_model_name=TEST_EMBEDDING_MODEL,
        run_judge=should_not_be_called,
    )

    assert score.deterministic_score == 0.0
    assert score.judge_score is None
    assert score.judge_skipped is True


def test_score_candidate_hard_gate_skips_run_judge_callable() -> None:
    checks = [JsonSchemaCheck(schema={"type": "object", "required": ["currency"]})]

    def should_not_be_called() -> float:
        raise AssertionError("run_judge must not be called when a hard gate check fails")

    score = score_candidate(
        benchmark_output="The currency is USD.",
        candidate_output="this is not json",
        deterministic_checks=checks,
        embedding_model_name=TEST_EMBEDDING_MODEL,
        run_judge=should_not_be_called,
    )

    assert score.gated is True
    assert score.final_score == 0.0
    assert score.judge_score is None


def test_score_candidate_without_judge_score_or_run_judge_leaves_judge_score_none() -> None:
    """A fully valid state: no BYOK judge configured at all yet."""
    checks = [LengthBoundsCheck(min_length=1, max_length=1000)]

    score = score_candidate(
        benchmark_output="Hello there, how can I help today?",
        candidate_output="Hi! How can I help you today?",
        deterministic_checks=checks,
        embedding_model_name=TEST_EMBEDDING_MODEL,
    )

    assert score.judge_score is None
    assert score.judge_skipped is True
    assert score.final_score >= 0.0  # still a valid partial score, no crash


def test_score_candidate_prefers_supplied_judge_score_over_run_judge() -> None:
    checks = [LengthBoundsCheck(min_length=1, max_length=1000)]

    def should_not_be_called() -> float:
        raise AssertionError("run_judge must not be called when judge_score is already supplied")

    score = score_candidate(
        benchmark_output="Same text.",
        candidate_output="Same text.",
        deterministic_checks=checks,
        embedding_model_name=TEST_EMBEDDING_MODEL,
        judge_score=0.5,
        run_judge=should_not_be_called,
    )

    assert score.judge_score == pytest.approx(0.5)


def test_score_candidate_uses_evaluate_deterministic_checks_semantics_directly() -> None:
    """Sanity check that score_candidate really calls the real deterministic
    evaluator rather than reinventing check logic — a required key that's
    genuinely missing must be reflected in the real EvaluationResult."""
    checks = [RequiredKeysCheck(keys=["revenue", "currency"])]
    candidate_output = '{"revenue": 100}'

    score = score_candidate(
        benchmark_output='{"revenue": 100, "currency": "USD"}',
        candidate_output=candidate_output,
        deterministic_checks=checks,
        embedding_model_name=TEST_EMBEDDING_MODEL,
        judge_score=1.0,
    )

    # Cross-check against calling evaluate_deterministic_checks directly.
    direct = evaluate_deterministic_checks(candidate_output, checks)
    assert score.deterministic.results[0].passed == direct.results[0].passed is False
    assert "currency" in score.deterministic.results[0].reason
