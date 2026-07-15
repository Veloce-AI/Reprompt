"""Tests for candidate selection (reprompt_core.selection).

Builds CompositeScore instances directly (rather than via
compute_composite_score / score_candidate) since these tests only care
about final_score values chosen by the test, not about exercising the
scoring formula itself (that's test_scoring.py's job) — CompositeScore is
a plain data container, so direct construction is the more focused choice
here.
"""

from __future__ import annotations

import pytest

from reprompt_core.deterministic import EvaluationResult
from reprompt_core.scoring import DEFAULT_WEIGHTS, CompositeScore
from reprompt_core.selection import ScoredSweepCandidate, select_best_candidate
from reprompt_core.sweep import SweepCandidate


def _score(final_score: float, *, gated: bool = False) -> CompositeScore:
    return CompositeScore(
        deterministic=EvaluationResult(results=[]),
        deterministic_score=1.0,
        embedding_score=final_score,
        judge_score=None,
        weights=DEFAULT_WEIGHTS,
        final_score=0.0 if gated else final_score,
        gated=gated,
        gate_reason="test-forced gate" if gated else None,
        judge_skipped=True,
    )


def _candidate(candidate_id: str, *, is_valid: bool = True) -> SweepCandidate:
    return SweepCandidate(
        id=candidate_id,
        label=f"candidate {candidate_id}",
        model="gpt-4o",
        temperature=0.5,
        format_mode="json",
        structured_output_mode=False,
        is_valid=is_valid,
        invalid_reason=None if is_valid else "test-forced invalid",
    )


def _scored(candidate_id: str, final_score: float, *, is_valid: bool = True) -> ScoredSweepCandidate:
    return ScoredSweepCandidate(
        candidate=_candidate(candidate_id, is_valid=is_valid),
        score=_score(final_score),
    )


# ---------------------------------------------------------------------------
# threshold rule
# ---------------------------------------------------------------------------


def test_single_candidate_above_threshold_is_selected() -> None:
    scored = [_scored("a", 0.97)]
    result = select_best_candidate(scored, parity_threshold=0.95)
    assert result.selected.candidate.id == "a"
    assert result.met_threshold is True


def test_best_above_threshold_wins_over_other_above_threshold_candidates() -> None:
    scored = [_scored("a", 0.96), _scored("b", 0.99), _scored("c", 0.97)]
    result = select_best_candidate(scored, parity_threshold=0.95)
    assert result.selected.candidate.id == "b"
    assert result.met_threshold is True


def test_no_candidate_above_threshold_falls_back_to_best_available() -> None:
    scored = [_scored("a", 0.60), _scored("b", 0.80), _scored("c", 0.75)]
    result = select_best_candidate(scored, parity_threshold=0.95)
    assert result.selected.candidate.id == "b"  # highest of the three, none clears 0.95
    assert result.met_threshold is False


def test_threshold_is_inclusive() -> None:
    scored = [_scored("a", 0.95)]
    result = select_best_candidate(scored, parity_threshold=0.95)
    assert result.met_threshold is True


# ---------------------------------------------------------------------------
# eligibility (is_valid) gates selection independent of score
# ---------------------------------------------------------------------------


def test_lower_scoring_eligible_candidate_above_threshold_beats_higher_scoring_ineligible_one() -> None:
    """The concrete 'somehow not eligible' state the task calls out: an
    is_valid=False candidate with a higher final_score must still lose to
    an eligible candidate that clears the threshold."""
    scored = [
        _scored("ineligible-high-score", 0.999, is_valid=False),
        _scored("eligible-above-threshold", 0.96),
    ]
    result = select_best_candidate(scored, parity_threshold=0.95)
    assert result.selected.candidate.id == "eligible-above-threshold"
    assert result.met_threshold is True


def test_ineligible_candidate_never_wins_the_fallback_either() -> None:
    scored = [
        _scored("ineligible-highest", 0.99, is_valid=False),
        _scored("eligible-lower", 0.70),
    ]
    result = select_best_candidate(scored, parity_threshold=0.95)
    assert result.selected.candidate.id == "eligible-lower"
    assert result.met_threshold is False


def test_all_ineligible_raises_value_error() -> None:
    scored = [_scored("a", 0.9, is_valid=False), _scored("b", 0.99, is_valid=False)]
    with pytest.raises(ValueError, match="eligible"):
        select_best_candidate(scored, parity_threshold=0.95)


# ---------------------------------------------------------------------------
# tie-breaking
# ---------------------------------------------------------------------------


def test_tie_above_threshold_breaks_to_first_seen_in_input_order() -> None:
    scored = [_scored("first", 0.97), _scored("second", 0.97)]
    result = select_best_candidate(scored, parity_threshold=0.95)
    assert result.selected.candidate.id == "first"

    # Reversed input order -> the (now-first) "second" wins, confirming the
    # tie-break is genuinely about input order, not candidate id/content.
    reversed_scored = [_scored("second", 0.97), _scored("first", 0.97)]
    reversed_result = select_best_candidate(reversed_scored, parity_threshold=0.95)
    assert reversed_result.selected.candidate.id == "second"


def test_tie_in_fallback_also_breaks_to_first_seen() -> None:
    scored = [_scored("first", 0.80), _scored("second", 0.80)]
    result = select_best_candidate(scored, parity_threshold=0.95)
    assert result.met_threshold is False
    assert result.selected.candidate.id == "first"


# ---------------------------------------------------------------------------
# misc
# ---------------------------------------------------------------------------


def test_empty_scored_list_raises_value_error() -> None:
    with pytest.raises(ValueError):
        select_best_candidate([], parity_threshold=0.95)


def test_reason_string_is_populated() -> None:
    scored = [_scored("a", 0.97)]
    result = select_best_candidate(scored, parity_threshold=0.95)
    assert result.reason
    assert "a" in result.reason
