"""Candidate selection — the plan's own stated rule, as a pure function.

Per ``refract-parity-engine-plan.md`` §3 ("d. Select best candidate >=
parity_threshold or best within budget"), this module picks a winner from
a list of *already-scored* candidates. It does not run anything (no model
calls, no scoring) and does not know about :mod:`refract_core.budget`
internally — "best within budget" is realized by the caller only ever
handing this function the candidates it actually evaluated before running
out of budget or exhausting the sweep; by the time
:func:`select_best_candidate` runs, "within budget" has already happened
upstream. This keeps sweep generation, budget tracking, and selection as
three separable, independently testable units, per the task brief.

Zero FastAPI imports, per the working rules for ``packages/core``.

Design decision: eligibility, not just score, gates selection
--------------------------------------------------------------
A candidate can score well and still not be selectable — the concrete case
this module guards against is a :class:`~refract_core.sweep.SweepCandidate`
with ``is_valid=False`` (a pre-known-invalid combination, e.g.
structured-output-mode requested against a model that doesn't support it;
see ``refract_core.sweep``'s module docstring). Such a candidate should
never have been executed against a real model in the first place, so it
should never win a selection even if — through a test setup, a stale
score, or a future caller's mistake — it shows up in the ``scored`` list
with a high ``final_score``. :func:`select_best_candidate` therefore
partitions on ``candidate.is_valid`` first and only ever selects from the
eligible subset; this is a real state the type system allows (nothing
stops a caller from including an ``is_valid=False`` candidate in the input
list) and is exercised directly in the test suite.

Design decision: tie-breaking
-------------------------------
When two eligible candidates have the exact same ``final_score``, the
first one encountered in the *input list's order* wins — Python's
``max(..., key=...)`` returns the first element attaining the maximum when
there are ties, so this falls out of the implementation directly rather
than needing an explicit secondary sort key. This is deterministic (same
input list order always produces the same winner) but is a property of
*input order*, not of any other candidate attribute (id, params, etc.) —
callers that want a specific tie-break preference (e.g. "prefer lower
temperature" or "prefer the cheaper candidate") should pre-sort ``scored``
accordingly before calling this function.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from refract_core.scoring import CompositeScore
from refract_core.sweep import SweepCandidate

__all__ = ["ScoredSweepCandidate", "SelectionResult", "select_best_candidate"]


class ScoredSweepCandidate(BaseModel):
    """A :class:`~refract_core.sweep.SweepCandidate` paired with the
    :class:`~refract_core.scoring.CompositeScore` it received after being
    executed and evaluated.

    Uses ``CompositeScore`` directly (not a parallel shape) — it already
    carries ``final_score`` plus the full deterministic/judge/embedding
    breakdown the future stage-detail drawer needs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: SweepCandidate
    score: CompositeScore


class SelectionResult(BaseModel):
    """The outcome of :func:`select_best_candidate`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selected: ScoredSweepCandidate
    met_threshold: bool = Field(
        description="True if `selected.score.final_score >= parity_threshold`. False means "
        "`selected` is a best-effort fallback — the best-scoring eligible candidate seen, "
        "returned because the sweep/budget ran out before any candidate cleared the threshold."
    )
    reason: str = Field(description="Human-readable explanation of why this candidate was selected.")


def select_best_candidate(
    scored: Sequence[ScoredSweepCandidate],
    parity_threshold: float,
) -> SelectionResult:
    """Select best candidate >= parity_threshold, or best-within-budget otherwise.

    Implements ``refract-parity-engine-plan.md`` §3(d) literally:

    1. Partition ``scored`` into eligible (``candidate.is_valid``) and
       ineligible candidates — see the module docstring's eligibility
       design decision. Ineligible candidates are never selected,
       regardless of score.
    2. Among the eligible candidates, if any has
       ``score.final_score >= parity_threshold``, return the
       highest-scoring one (``met_threshold=True``).
    3. Otherwise, return the highest-scoring *eligible* candidate
       regardless of threshold (``met_threshold=False``) — this is the
       "best within budget" half of the rule: by the time this function is
       called, ``scored`` already reflects everything the caller managed
       to evaluate before its budget or sweep ran out (see module
       docstring — this function does not itself know about budget).

    Ties (equal ``final_score``) are broken by input-list order — see the
    module docstring's tie-breaking design decision.

    Raises
    ------
    ValueError
        If ``scored`` is empty, or if none of the candidates in ``scored``
        are eligible (``is_valid=True``) — there is nothing legitimate to
        select in either case. A real caller should never hit the second
        case: only valid candidates (per ``refract_core.sweep``) should
        ever be executed and scored to begin with.
    """
    if not scored:
        raise ValueError("select_best_candidate requires at least one scored candidate")

    eligible = [sc for sc in scored if sc.candidate.is_valid]
    if not eligible:
        raise ValueError(
            "No eligible (is_valid=True) candidates among the scored candidates — nothing to "
            "select. A real caller should never reach this: only valid candidates (see "
            "refract_core.sweep.SweepCandidate.is_valid) should ever be executed and scored."
        )

    above_threshold = [sc for sc in eligible if sc.score.final_score >= parity_threshold]
    if above_threshold:
        best = max(above_threshold, key=lambda sc: sc.score.final_score)
        return SelectionResult(
            selected=best,
            met_threshold=True,
            reason=(
                f"Candidate '{best.candidate.id}' ({best.candidate.label}) reached parity_threshold "
                f"(final_score={best.score.final_score:.4f} >= {parity_threshold:.4f})."
            ),
        )

    best = max(eligible, key=lambda sc: sc.score.final_score)
    return SelectionResult(
        selected=best,
        met_threshold=False,
        reason=(
            f"No eligible candidate reached parity_threshold ({parity_threshold:.4f}); returning the "
            f"best-scoring eligible candidate seen: '{best.candidate.id}' ({best.candidate.label}), "
            f"final_score={best.score.final_score:.4f}."
        ),
    )
