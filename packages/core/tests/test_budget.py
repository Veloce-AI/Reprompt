"""Tests for budget accounting (refract_core.budget).

No network calls: ``estimate_cost_usd`` goes through the real
``refract_core.llm.registry`` against LiteLLM's bundled static pricing
table (same convention as ``test_llm_registry.py``) — ``"gpt-4o"`` has
known per-token pricing there, ``"totally-not-a-real-model-xyz-123"`` does
not (LiteLLM's own "unrecognized model" case).
"""

from __future__ import annotations

import pytest

from refract_core.budget import (
    BudgetExceededError,
    BudgetTracker,
    estimate_cost_usd,
    filter_affordable_candidates,
)
from refract_core.sweep import SweepCandidate

PRICED_MODEL = "gpt-4o"
UNPRICED_MODEL = "totally-not-a-real-model-xyz-123"


def _candidate(candidate_id: str, *, is_valid: bool = True) -> SweepCandidate:
    return SweepCandidate(
        id=candidate_id,
        label=f"candidate {candidate_id}",
        model=PRICED_MODEL,
        temperature=0.5,
        format_mode="json",
        structured_output_mode=False,
        is_valid=is_valid,
        invalid_reason=None if is_valid else "test-forced invalid",
    )


# ---------------------------------------------------------------------------
# spend accumulation / remaining-budget checks
# ---------------------------------------------------------------------------


def test_starts_with_full_budget_and_no_spend() -> None:
    tracker = BudgetTracker(budget_usd=10.0)
    assert tracker.spent_usd == 0.0
    assert tracker.remaining_usd == 10.0
    assert tracker.is_exhausted is False


def test_record_spend_accumulates() -> None:
    tracker = BudgetTracker(budget_usd=10.0)
    tracker.record_spend(2.0)
    tracker.record_spend(3.5)
    assert tracker.spent_usd == pytest.approx(5.5)
    assert tracker.remaining_usd == pytest.approx(4.5)
    assert len(tracker.records) == 2


def test_record_spend_returns_a_record_with_candidate_id() -> None:
    tracker = BudgetTracker(budget_usd=10.0)
    record = tracker.record_spend(1.0, candidate_id="abc123")
    assert record.cost_usd == 1.0
    assert record.candidate_id == "abc123"
    assert record.pushed_over_budget is False


def test_can_afford_true_when_estimate_fits() -> None:
    tracker = BudgetTracker(budget_usd=10.0)
    tracker.record_spend(4.0)
    assert tracker.can_afford(5.0) is True
    assert tracker.can_afford(6.0) is True  # exactly remaining


def test_can_afford_false_when_estimate_exceeds_remaining() -> None:
    tracker = BudgetTracker(budget_usd=10.0)
    tracker.record_spend(4.0)
    assert tracker.can_afford(6.01) is False


def test_can_afford_rejects_negative_estimate() -> None:
    tracker = BudgetTracker(budget_usd=10.0)
    with pytest.raises(ValueError):
        tracker.can_afford(-1.0)


def test_record_spend_rejects_negative_cost() -> None:
    tracker = BudgetTracker(budget_usd=10.0)
    with pytest.raises(ValueError):
        tracker.record_spend(-0.01)


# ---------------------------------------------------------------------------
# over-budget behavior — the "hard stop" design decision
# ---------------------------------------------------------------------------


def test_record_spend_never_raises_when_it_pushes_over_budget() -> None:
    """Recording a real, already-incurred charge always succeeds, even if
    it takes spend past the budget — see the module's documented design
    decision (the money is already spent with the provider by this point)."""
    tracker = BudgetTracker(budget_usd=5.0)
    record = tracker.record_spend(7.0)  # no raise
    assert record.pushed_over_budget is True
    assert tracker.spent_usd == 7.0
    assert tracker.is_exhausted is True
    assert tracker.remaining_usd == pytest.approx(-2.0)


def test_is_exhausted_true_exactly_at_budget() -> None:
    tracker = BudgetTracker(budget_usd=5.0)
    tracker.record_spend(5.0)
    assert tracker.is_exhausted is True


def test_subsequent_record_spend_after_exhaustion_still_succeeds_and_signals() -> None:
    """A caller's loop is expected to check is_exhausted and break — but if
    it doesn't, record_spend still faithfully records reality rather than
    silently dropping the charge."""
    tracker = BudgetTracker(budget_usd=5.0)
    tracker.record_spend(5.0)
    assert tracker.is_exhausted is True
    record = tracker.record_spend(1.0)  # still no raise
    assert record.pushed_over_budget is True
    assert tracker.spent_usd == 6.0


def test_assert_can_afford_raises_budget_exceeded_error_when_over() -> None:
    tracker = BudgetTracker(budget_usd=5.0)
    tracker.record_spend(4.5)
    with pytest.raises(BudgetExceededError):
        tracker.assert_can_afford(1.0)


def test_assert_can_afford_does_not_raise_when_it_fits() -> None:
    tracker = BudgetTracker(budget_usd=5.0)
    tracker.record_spend(4.0)
    tracker.assert_can_afford(1.0)  # no raise


def test_assert_can_afford_never_mutates_tracker_state() -> None:
    tracker = BudgetTracker(budget_usd=5.0)
    with pytest.raises(BudgetExceededError):
        tracker.assert_can_afford(6.0)
    assert tracker.spent_usd == 0.0
    assert tracker.records == []


# ---------------------------------------------------------------------------
# optional cost-estimate pre-check convenience
# ---------------------------------------------------------------------------


def test_estimate_cost_usd_uses_registry_pricing_for_a_known_model() -> None:
    estimate = estimate_cost_usd(PRICED_MODEL, expected_input_tokens=1000, expected_output_tokens=500)
    assert estimate is not None
    assert estimate > 0.0


def test_estimate_cost_usd_returns_none_for_unpriced_model() -> None:
    assert estimate_cost_usd(UNPRICED_MODEL, expected_input_tokens=1000, expected_output_tokens=500) is None


def test_estimate_cost_usd_rejects_negative_token_counts() -> None:
    with pytest.raises(ValueError):
        estimate_cost_usd(PRICED_MODEL, expected_input_tokens=-1, expected_output_tokens=0)
    with pytest.raises(ValueError):
        estimate_cost_usd(PRICED_MODEL, expected_input_tokens=0, expected_output_tokens=-1)


def test_estimate_cost_usd_feeds_can_afford_end_to_end() -> None:
    tracker = BudgetTracker(budget_usd=100.0)
    estimate = estimate_cost_usd(PRICED_MODEL, expected_input_tokens=1000, expected_output_tokens=500)
    assert estimate is not None
    assert tracker.can_afford(estimate) is True  # $100 budget comfortably covers ~1.5k tokens of gpt-4o


# ---------------------------------------------------------------------------
# filter_affordable_candidates — sweep + budget glue
# ---------------------------------------------------------------------------


def test_filter_affordable_candidates_excludes_invalid_candidates() -> None:
    tracker = BudgetTracker(budget_usd=100.0)
    candidates = [_candidate("a"), _candidate("b", is_valid=False), _candidate("c")]
    result = filter_affordable_candidates(candidates, tracker, estimated_cost_per_candidate=0.0)
    assert [c.id for c in result] == ["a", "c"]


def test_filter_affordable_candidates_stops_once_running_total_exceeds_remaining() -> None:
    tracker = BudgetTracker(budget_usd=5.0)
    candidates = [_candidate("a"), _candidate("b"), _candidate("c"), _candidate("d")]
    # $2 each -> a ($2, total 2<=5 ok), b (total 4<=5 ok), c (total 6>5 stop)
    result = filter_affordable_candidates(candidates, tracker, estimated_cost_per_candidate=2.0)
    assert [c.id for c in result] == ["a", "b"]


def test_filter_affordable_candidates_never_mutates_tracker() -> None:
    tracker = BudgetTracker(budget_usd=5.0)
    candidates = [_candidate("a"), _candidate("b")]
    filter_affordable_candidates(candidates, tracker, estimated_cost_per_candidate=2.0)
    assert tracker.spent_usd == 0.0
    assert tracker.records == []


def test_filter_affordable_candidates_defaults_to_zero_cost_is_valid_only_filter() -> None:
    tracker = BudgetTracker(budget_usd=0.01)  # tiny budget
    candidates = [_candidate("a"), _candidate("b", is_valid=False), _candidate("c")]
    result = filter_affordable_candidates(candidates, tracker)  # no estimate given
    assert [c.id for c in result] == ["a", "c"]


def test_filter_affordable_candidates_rejects_negative_estimate() -> None:
    tracker = BudgetTracker(budget_usd=5.0)
    with pytest.raises(ValueError):
        filter_affordable_candidates([_candidate("a")], tracker, estimated_cost_per_candidate=-1.0)
