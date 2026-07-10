"""Budget accounting for the M3 optimizer loop's candidate sweep.

Per ``refract-master-build-prompt.md`` §5 M3(d) ("budget accounting with
hard stop") and ``refract-parity-engine-plan.md``'s Migration model
(``budget`` — see ``apps/api/src/refract_api/models.py``'s
``Migration.budget``, "max optimization spend in $, hard stop"), this
module tracks real spend against a fixed $ ceiling and answers "can we
afford to try one more candidate" / "are we out of budget" for a caller
(the not-yet-built M3 optimizer loop, a Celery task) that evaluates
candidates one at a time.

Zero FastAPI imports, no LLM calls, no network — pure local bookkeeping.

Design decision: what "hard stop" means operationally
------------------------------------------------------------
A tracker like this only ever learns a candidate's *real* cost *after* the
model call already happened — ``LLMResponse.cost_usd``
(:class:`refract_core.llm.client.LLMResponse`) is populated post-hoc, once
the provider has already been paid. By the time :meth:`BudgetTracker.record_spend`
is called, the money is already spent; refusing to *record* it would not
un-spend it, it would just leave this tracker's books wrong.

So this module splits "hard stop" into two distinct operations that a real
caller uses at two distinct points in its loop:

* **Before** attempting a candidate: :meth:`BudgetTracker.can_afford` (pure,
  non-mutating pre-check against an estimate) or its raising sibling
  :meth:`BudgetTracker.assert_can_afford`, for a caller that wants a hard
  ``raise`` instead of an ``if`` at the top of a loop iteration.
* **After** a candidate actually ran: :meth:`BudgetTracker.record_spend`
  records the real charge unconditionally — it never refuses, never raises
  for "going over budget" — and returns a :class:`SpendRecord` whose
  ``pushed_over_budget`` flag (mirrored by :attr:`BudgetTracker.is_exhausted`
  right after the call) is the actual hard-stop signal: it tells the caller
  "record this real spend, then don't attempt any *more* candidates."

This is the only design that matches what "hard stop" can mean for
after-the-fact cost data: stop *starting new work*, not "reject a
completed charge".
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from refract_core.llm.registry import get_model_capabilities
from refract_core.sweep import SweepCandidate

__all__ = [
    "BudgetExceededError",
    "SpendRecord",
    "BudgetTracker",
    "estimate_cost_usd",
    "filter_affordable_candidates",
]


class BudgetExceededError(RuntimeError):
    """Raised only by :meth:`BudgetTracker.assert_can_afford`.

    Never raised by :meth:`BudgetTracker.record_spend` — see the module
    docstring's hard-stop design decision. This is the opt-in raising path
    for a caller that wants a hard gate *before* attempting a candidate,
    not a signal about real spend already recorded.
    """


class SpendRecord(BaseModel):
    """One recorded charge against a :class:`BudgetTracker`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cost_usd: float = Field(ge=0)
    candidate_id: str | None = None
    pushed_over_budget: bool = Field(
        description="True if the tracker is at-or-over budget (is_exhausted) immediately after "
        "this charge was applied — check this (or tracker.is_exhausted) to decide whether to "
        "stop attempting further candidates. Does not distinguish 'this charge was the one that "
        "tipped it over' from 'it was already over before this charge' — both mean the same "
        "thing operationally: stop now."
    )


class BudgetTracker(BaseModel):
    """Accumulates real spend against a fixed $ budget for one migration's optimizer run.

    See the module docstring for the hard-stop semantics. A real Celery
    task loop looks like::

        tracker = BudgetTracker(budget_usd=migration.budget)
        for candidate in candidates:
            if tracker.is_exhausted:
                break
            estimate = estimate_cost_usd(candidate.model, expected_input_tokens=..., expected_output_tokens=...)
            if estimate is not None and not tracker.can_afford(estimate):
                continue  # skip this one; a cheaper candidate later might still fit
            response = complete(candidate.model, messages, temperature=candidate.temperature, ...)
            tracker.record_spend(response.cost_usd or 0.0, candidate_id=candidate.id)
        # tracker.spent_usd / tracker.is_exhausted now reflect real spend.
    """

    model_config = ConfigDict(extra="forbid")

    budget_usd: float = Field(gt=0, description="Hard $ ceiling for this migration's optimization spend.")
    spent_usd: float = Field(default=0.0, ge=0, description="Real spend recorded so far via record_spend.")
    records: list[SpendRecord] = Field(default_factory=list)

    @property
    def remaining_usd(self) -> float:
        """Budget left. Can go negative once over-spent — see module docstring."""
        return self.budget_usd - self.spent_usd

    @property
    def is_exhausted(self) -> bool:
        """True once accumulated real spend has reached or passed the budget.

        This is the hard-stop signal a caller's loop checks to decide
        whether to attempt another candidate.
        """
        return self.spent_usd >= self.budget_usd

    def can_afford(self, estimated_cost_usd: float) -> bool:
        """Conservative pre-check: would this estimated cost still fit in what's left?

        Pure — never mutates the tracker. ``estimated_cost_usd`` is
        whatever the caller believes the next attempt will cost (e.g. from
        :func:`estimate_cost_usd`, a running average of past candidates, or
        a flat worst-case guess); this function trusts it as given and does
        not itself call out to the registry or any model.
        """
        if estimated_cost_usd < 0:
            raise ValueError("estimated_cost_usd must be >= 0")
        return estimated_cost_usd <= self.remaining_usd

    def assert_can_afford(self, estimated_cost_usd: float) -> None:
        """Raising variant of :meth:`can_afford`.

        Raises :class:`BudgetExceededError` if the estimate would not fit
        in the remaining budget. For a caller that wants a hard gate at the
        top of a loop iteration instead of an ``if``/``continue``. Never
        called internally by :meth:`record_spend` — recording real,
        already-incurred spend must always succeed (see module docstring).
        """
        if not self.can_afford(estimated_cost_usd):
            raise BudgetExceededError(
                f"Estimated cost ${estimated_cost_usd:.4f} exceeds remaining budget "
                f"${self.remaining_usd:.4f} (of ${self.budget_usd:.4f} total, "
                f"${self.spent_usd:.4f} already spent)."
            )

    def record_spend(self, cost_usd: float, *, candidate_id: str | None = None) -> SpendRecord:
        """Record a real, already-incurred charge.

        Never refuses on "this would exceed budget" — see the module
        docstring's hard-stop design decision; the money is already spent
        with the provider by the time this is called. Only raises
        ``ValueError`` for a malformed input (negative cost), which is a
        caller bug, not a budget event.

        Returns the :class:`SpendRecord` for this charge; check
        ``record.pushed_over_budget`` (or :attr:`is_exhausted` right after
        calling this) to know whether to stop attempting further
        candidates.
        """
        if cost_usd < 0:
            raise ValueError("cost_usd must be >= 0")
        self.spent_usd += cost_usd
        record = SpendRecord(
            cost_usd=cost_usd,
            candidate_id=candidate_id,
            pushed_over_budget=self.is_exhausted,
        )
        self.records.append(record)
        return record


def estimate_cost_usd(
    model: str,
    *,
    expected_input_tokens: int,
    expected_output_tokens: int,
) -> float | None:
    """Rough pre-call cost estimate from the registry's per-token pricing.

    Optional convenience for the pre-check
    (:meth:`BudgetTracker.can_afford` / :meth:`BudgetTracker.assert_can_afford`)
    — callers are never required to have an estimate; recording real spend
    via :meth:`BudgetTracker.record_spend` never needs one.

    Returns ``None`` if the registry has no pricing data for ``model`` (an
    unrecognized model string, or any model LiteLLM doesn't carry cost data
    for) — treat ``None`` as "can't estimate this one", not as "$0"; a
    caller that gets ``None`` back should either skip the pre-check for
    this candidate or fall back to a flat worst-case guess of its own.
    """
    if expected_input_tokens < 0:
        raise ValueError("expected_input_tokens must be >= 0")
    if expected_output_tokens < 0:
        raise ValueError("expected_output_tokens must be >= 0")

    capabilities = get_model_capabilities(model)
    if capabilities.input_cost_per_token is None or capabilities.output_cost_per_token is None:
        return None
    return (
        expected_input_tokens * capabilities.input_cost_per_token
        + expected_output_tokens * capabilities.output_cost_per_token
    )


def filter_affordable_candidates(
    candidates: Sequence[SweepCandidate],
    tracker: BudgetTracker,
    *,
    estimated_cost_per_candidate: float = 0.0,
) -> list[SweepCandidate]:
    """Preview which valid candidates the tracker currently has room to attempt.

    Pure — never mutates ``tracker``, makes no model calls. Thin glue
    between :mod:`refract_core.sweep` (candidate generation) and this
    module (budget accounting), for a caller that wants to know "which of
    these candidates are even worth trying right now" before it starts
    making real LLM calls:

    * ``is_valid=False`` candidates (pre-known-invalid — see
      ``refract_core.sweep``) are always excluded; they were never going
      to be attempted regardless of budget.
    * Walking ``candidates`` in order, this keeps a running hypothetical
      total at a flat ``estimated_cost_per_candidate`` and stops including
      candidates once that running total would exceed
      ``tracker.remaining_usd`` — mirroring a sequential loop that stops
      once budget runs out, not a bin-packing selection of the "best"
      affordable subset. A later candidate that would individually still
      fit is not included once an earlier one has (hypothetically) used up
      the remaining budget.

    ``estimated_cost_per_candidate`` defaults to ``0.0``, which degenerates
    this to "just the ``is_valid`` filter" for a caller that doesn't have a
    per-candidate cost estimate yet (e.g. :func:`estimate_cost_usd`
    returned ``None``) — every valid candidate is "affordable" against a
    flat $0 estimate.
    """
    if estimated_cost_per_candidate < 0:
        raise ValueError("estimated_cost_per_candidate must be >= 0")

    affordable: list[SweepCandidate] = []
    running_total = 0.0
    for candidate in candidates:
        if not candidate.is_valid:
            continue
        running_total += estimated_cost_per_candidate
        if running_total > tracker.remaining_usd:
            break
        affordable.append(candidate)
    return affordable
