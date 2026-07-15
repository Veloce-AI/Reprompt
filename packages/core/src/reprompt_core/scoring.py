"""Composite scorer — ties deterministic checks, embedding similarity, and
the pairwise LLM judge together per the evaluation engine formula.

Per ``reprompt-parity-engine-plan.md`` §3 ("EVALUATION ENGINE: Score =
w1*deterministic + w2*LLM-judge + w3*embedding-sim ... Deterministic checks
are free — run first, gate before spending judge tokens"), this module owns:

* the weighted composite formula (:func:`compute_composite_score`), and
* the free/cheap-first orchestration (:func:`score_candidate`) that runs
  :mod:`reprompt_core.deterministic` and :mod:`reprompt_core.embedding`
  directly (both are free/local), and only spends judge tokens
  (:mod:`reprompt_core.judge`) when :func:`should_run_judge` says it's worth
  it.

Zero FastAPI imports, per the working rules for ``packages/core``.

Design decision: deterministic gating (partial credit vs. hard gate)
-----------------------------------------------------------------------
The plan doesn't fully specify how a failing deterministic check should
affect the score, beyond "gate before spending judge tokens". This module
makes two distinct decisions:

1. **Most check failures are partial credit, not a hard stop.**
   :func:`deterministic_score` is the *fraction* of checks that passed
   (1.0 for an empty check list). A candidate that fails 1 of 5 length/regex
   checks still gets meaningful deterministic credit — the overall weighted
   formula already discounts it via ``w1``, so a second, binary hard-stop on
   top would double-punish minor misses the judge/embedding terms are better
   positioned to weigh in on anyway.

2. **``json_schema`` check failures are an absolute gate, regardless of weight.**
   If a rubric declares a ``json_schema`` check (i.e. this stage's output is
   *required* to be structured JSON of a given shape) and it fails, the
   output is structurally broken — there is nothing coherent for the judge
   or the embedding scorer to meaningfully compare against the benchmark.
   :func:`compute_composite_score` forces ``final_score = 0.0`` and
   :func:`should_run_judge` refuses to run in this case, no matter how the
   weights are configured. This is the "malformed/non-JSON output when JSON
   was required" case called out explicitly in the task brief. Every other
   check type (``required_keys``, ``regex``, ``length_bounds``,
   ``enum_values``, ``no_hallucinated_ids``) stays partial-credit — those
   describe *content* quality, not structural validity, and a rubric author
   who wants one of those to gate too can express it as a stricter
   ``json_schema`` check instead.

Design decision: gating the judge call
-----------------------------------------
:func:`should_run_judge` returns ``False`` (skip the judge) in two cases:
the hard-gate above, or the fraction of deterministic checks passed falling
below ``min_deterministic_score`` (default 0.5 — "more than half the
checks already failed, so this candidate is very unlikely to clear a parity
threshold even with a perfect judge score"). :func:`score_candidate` calls
this *before* invoking an injected ``run_judge`` callable, so a caller can
wire up a real (paid) judge call and trust that it will only actually fire
when there's a reasonable chance it matters — this is the concrete
"gate before spending judge tokens" mechanism the plan calls for.

Design decision: missing judge score defaults to 0, not omitted
--------------------------------------------------------------------
:func:`compute_composite_score` accepts ``judge_score: float | None``. When
it is ``None`` (deferred, skipped by the gate, or simply not configured —
e.g. no BYOK key set yet), the judge term contributes **0** to the weighted
sum rather than being dropped from the average. This is deliberately
pessimistic: the whole point of deferring/skipping the judge is "this
candidate already looks bad enough that spending tokens on it is wasteful",
so a missing judge score should never make ``final_score`` look *better*
than a candidate that was fully evaluated. The result's ``judge_skipped``
flag tells the caller (and, later, the UI) that this is not yet — or will
never be — a complete evaluation, so it isn't presented as a final verdict
by accident.

Default weights
-------------------
The plan states the formula but not concrete default weights. This module
defaults to ``deterministic=0.25, judge=0.45, embedding=0.30`` (see
:data:`DEFAULT_WEIGHTS`): the judge gets the plurality because it is the
only term that actually reads the rubric's semantic criteria and is
explicitly the plan's "richest" signal; embedding similarity is a decent
generic semantic backstop that's cheap enough to always compute so it gets
the next-largest share; deterministic checks get the smallest share on
*this* term deliberately, since their sharpest failure mode (structural
breakage) is already handled by the hard gate above rather than by this
weight — giving that same signal a large weight here as well would
double-count it. Weights need not sum to 1 — :func:`compute_composite_score`
always normalizes by ``weights.total``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from reprompt_core.deterministic import (
    CheckResult,
    DeterministicCheck,
    EvaluationResult,
    evaluate_deterministic_checks,
)
from reprompt_core.embedding import DEFAULT_EMBEDDING_MODEL, embedding_similarity

__all__ = [
    "ScoreWeights",
    "DEFAULT_WEIGHTS",
    "DEFAULT_MIN_DETERMINISTIC_SCORE_FOR_JUDGE",
    "HARD_GATE_CHECK_TYPES",
    "CompositeScore",
    "deterministic_score",
    "should_run_judge",
    "compute_composite_score",
    "score_candidate",
]

HARD_GATE_CHECK_TYPES = frozenset({"json_schema"})
"""Deterministic check types that act as an absolute gate on failure,
regardless of `ScoreWeights`. See the module docstring's "hard gate" design
decision."""


class ScoreWeights(BaseModel):
    """Weights for ``Score = w1*deterministic + w2*judge + w3*embedding_sim``.

    Need not sum to 1 — :func:`compute_composite_score` always divides by
    :attr:`total`. Frozen so a shared :data:`DEFAULT_WEIGHTS` instance can be
    safely used as a default argument without risk of a caller mutating it
    in place out from under other callers.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    deterministic: float = Field(default=0.25, ge=0, description="w1")
    judge: float = Field(default=0.45, ge=0, description="w2")
    embedding: float = Field(default=0.30, ge=0, description="w3")

    @property
    def total(self) -> float:
        return self.deterministic + self.judge + self.embedding


DEFAULT_WEIGHTS = ScoreWeights()
"""Product default weights. See the module docstring's "Default weights" section."""

DEFAULT_MIN_DETERMINISTIC_SCORE_FOR_JUDGE = 0.5
"""Below this fraction of deterministic checks passed, :func:`should_run_judge`
recommends skipping the judge call entirely. See the module docstring."""


def deterministic_score(result: EvaluationResult) -> float:
    """Fraction of deterministic checks that passed, in [0, 1].

    Vacuously 1.0 for an empty check list, mirroring
    ``EvaluationResult.passed``'s own vacuous-truth behavior for "no checks
    configured for this stage yet".
    """
    if not result.results:
        return 1.0
    passed = sum(1 for check in result.results if check.passed)
    return passed / len(result.results)


def _hard_gate_failure(result: EvaluationResult) -> CheckResult | None:
    """The first failing check whose type is in HARD_GATE_CHECK_TYPES, if any."""
    for check in result.results:
        if check.type in HARD_GATE_CHECK_TYPES and not check.passed:
            return check
    return None


def should_run_judge(
    deterministic_result: EvaluationResult,
    *,
    min_deterministic_score: float = DEFAULT_MIN_DETERMINISTIC_SCORE_FOR_JUDGE,
) -> tuple[bool, str | None]:
    """Whether it's worth spending judge tokens on this candidate at all.

    Returns ``(should_run, reason)`` — ``reason`` is ``None`` when
    ``should_run`` is ``True``, and a human-readable explanation (safe to
    show a non-technical user, same convention as
    ``reprompt_core.deterministic.CheckResult.reason``) when it's ``False``.
    """
    gate_failure = _hard_gate_failure(deterministic_result)
    if gate_failure is not None:
        return False, f"Hard gate failed: {gate_failure.label} — {gate_failure.reason}"

    score = deterministic_score(deterministic_result)
    if score < min_deterministic_score:
        return False, (
            f"Only {score:.0%} of deterministic checks passed (below the "
            f"{min_deterministic_score:.0%} threshold) — this candidate is very "
            "unlikely to reach parity even with a favorable judge score."
        )
    return True, None


class CompositeScore(BaseModel):
    """Structured breakdown of one candidate's composite score.

    Deliberately not a bare float — screen 7's stage detail drawer needs the
    per-component breakdown (rubric checklist pass/fail, not just a number),
    per the master build prompt's product surface spec.
    """

    model_config = ConfigDict(extra="forbid")

    deterministic: EvaluationResult
    deterministic_score: float = Field(ge=0, le=1, description="Fraction of deterministic checks passed.")
    embedding_score: float = Field(ge=0, le=1)
    judge_score: float | None = Field(default=None, ge=0, le=1)
    weights: ScoreWeights
    final_score: float = Field(ge=0, le=1)
    gated: bool = Field(description="True if a hard-gate check (see HARD_GATE_CHECK_TYPES) failed.")
    gate_reason: str | None = None
    judge_skipped: bool = Field(
        description="True if final_score was computed with no judge score contributing "
        "(judge_score was None) — either because it was gated/skipped, or simply not "
        "supplied yet. See the module docstring's 'missing judge score' design decision."
    )


def compute_composite_score(
    deterministic_result: EvaluationResult,
    embedding_sim: float,
    judge_score: float | None = None,
    *,
    weights: ScoreWeights = DEFAULT_WEIGHTS,
) -> CompositeScore:
    """Pure formula: ``Score = w1*deterministic + w2*judge + w3*embedding_sim``.

    No LLM calls, no embedding model — both scores are supplied by the
    caller (or by :func:`score_candidate`, which computes them). See the
    module docstring for the hard-gate and missing-judge-score design
    decisions this implements.

    Raises ``ValueError`` if ``weights.total`` is 0 (no signal to weight at
    all — a configuration error, not a scoreable candidate).
    """
    det_score = deterministic_score(deterministic_result)
    gate_failure = _hard_gate_failure(deterministic_result)

    if gate_failure is not None:
        return CompositeScore(
            deterministic=deterministic_result,
            deterministic_score=det_score,
            embedding_score=embedding_sim,
            judge_score=judge_score,
            weights=weights,
            final_score=0.0,
            gated=True,
            gate_reason=f"Hard gate failed: {gate_failure.label} — {gate_failure.reason}",
            judge_skipped=judge_score is None,
        )

    weight_total = weights.total
    if weight_total <= 0:
        raise ValueError("ScoreWeights must have at least one positive weight (w1+w2+w3 must be > 0)")

    judge_component = judge_score if judge_score is not None else 0.0
    final_score = (
        weights.deterministic * det_score
        + weights.judge * judge_component
        + weights.embedding * embedding_sim
    ) / weight_total

    return CompositeScore(
        deterministic=deterministic_result,
        deterministic_score=det_score,
        embedding_score=embedding_sim,
        judge_score=judge_score,
        weights=weights,
        final_score=final_score,
        gated=False,
        gate_reason=None,
        judge_skipped=judge_score is None,
    )


def score_candidate(
    *,
    benchmark_output: str,
    candidate_output: str,
    deterministic_checks: Sequence[DeterministicCheck],
    input: dict[str, Any] | str | None = None,  # noqa: A002 - mirrors StageRecord.input naming
    embedding_model_name: str = DEFAULT_EMBEDDING_MODEL,
    judge_score: float | None = None,
    run_judge: Callable[[], float] | None = None,
    weights: ScoreWeights = DEFAULT_WEIGHTS,
    min_deterministic_score_for_judge: float = DEFAULT_MIN_DETERMINISTIC_SCORE_FOR_JUDGE,
) -> CompositeScore:
    """End-to-end composite scoring for one benchmark/candidate output pair.

    Runs the free/cheap checks first — deterministic checks
    (:func:`reprompt_core.deterministic.evaluate_deterministic_checks`) and
    local embedding similarity
    (:func:`reprompt_core.embedding.embedding_similarity`) — then decides
    whether the (expensive) judge is worth calling at all:

    * If ``judge_score`` is already supplied, it's used directly and
      ``run_judge`` (if also given) is never called.
    * Else, if ``run_judge`` is given, :func:`should_run_judge` is consulted
      first; ``run_judge`` is only invoked if it returns ``True``. This is
      the concrete "gate before spending judge tokens" mechanism — wire a
      real (paid) judge call (e.g. ``lambda: judge_pairwise(...).overall_score``)
      as ``run_judge`` and it will only actually fire when there's a
      reasonable chance the result matters.
    * Else (neither supplied), the judge term is simply omitted
      (``judge_score=None`` downstream) — a fully valid state, e.g. before a
      BYOK judge model/key is configured at all.

    Raises ``ValueError`` from :func:`reprompt_core.embedding.embedding_similarity`
    if either output is empty/whitespace-only (that function's own documented
    behavior — an empty output is a distinct failure mode from "dissimilar
    output" and is not silently scored).
    """
    deterministic_result = evaluate_deterministic_checks(candidate_output, deterministic_checks, input=input)
    embedding_score = embedding_similarity(benchmark_output, candidate_output, model_name=embedding_model_name)

    resolved_judge_score = judge_score
    if resolved_judge_score is None and run_judge is not None:
        should_run, _reason = should_run_judge(
            deterministic_result, min_deterministic_score=min_deterministic_score_for_judge
        )
        if should_run:
            resolved_judge_score = run_judge()

    return compute_composite_score(
        deterministic_result,
        embedding_score,
        resolved_judge_score,
        weights=weights,
    )
