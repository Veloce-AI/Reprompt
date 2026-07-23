"""Phase 8 — executable assertions.

Translates :class:`~reprompt_core.contract.mine.AssertionSpec` rows (mined
by Phase 5 and approved via the HITL gate in contracts.py) into
:mod:`reprompt_core.deterministic` predicates, runs them against a candidate
output, and returns a structured pass/fail result the optimizer loop uses to
decide whether to backtrack.

Only the three kinds the contract miner actually emits today
(``required_keys``, ``regex``, ``enum_values``) are translated; unknown
kinds are silently skipped so a future new kind never blocks an optimizer
run before its predicate is wired in here.

Zero FastAPI imports, per the working rules for ``packages/core``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from reprompt_core.contract.mine import AssertionSpec
from reprompt_core.deterministic import (
    DeterministicCheck,
    EnumValuesCheck,
    EvaluationResult,
    RegexCheck,
    RequiredKeysCheck,
    evaluate_deterministic_checks,
)

__all__ = ["AssertionFailure", "AssertionRunResult", "run_assertions"]


class AssertionFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assertion_id: int | None
    kind: str
    reason: str


class AssertionRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    failures: list[AssertionFailure]


def _spec_to_check(assertion: AssertionSpec) -> DeterministicCheck | None:
    """Translate one AssertionSpec into a typed DeterministicCheck.

    Returns None for unknown kinds — callers skip None entries rather than
    raising, so an unrecognised kind never aborts evaluation.
    """
    kind = assertion.kind
    params = assertion.spec

    if kind == "required_keys":
        keys = params.get("keys") or []
        if keys:
            return RequiredKeysCheck(keys=list(keys))
    elif kind == "regex":
        pattern = params.get("pattern")
        if pattern:
            return RegexCheck(pattern=str(pattern))
    elif kind == "enum_values":
        field = params.get("field")
        values = params.get("values")
        if field and values:
            return EnumValuesCheck(field=str(field), allowed_values=list(values))
    return None


def run_assertions(
    output: str,
    assertion_specs: list[AssertionSpec],
    *,
    input: Any = None,  # noqa: A002 — mirrors evaluate_deterministic_checks naming
) -> AssertionRunResult:
    """Run all assertion specs against one candidate output.

    Translatable specs are evaluated via
    :func:`reprompt_core.deterministic.evaluate_deterministic_checks`.
    Un-translatable kinds (unrecognised or missing required params) are
    silently skipped — a spec that can't be evaluated today should not
    block the optimizer.

    ``input`` is forwarded to ``evaluate_deterministic_checks`` and used
    only by ``no_hallucinated_ids``-type checks (none of the three miner
    kinds need it today, but it's here for forward compatibility).

    Parameters
    ----------
    output:
        The candidate output string to evaluate.
    assertion_specs:
        Approved :class:`~reprompt_core.contract.mine.AssertionSpec` rows
        to enforce. The ``id`` field on each (set by the API layer from
        the DB row's primary key) is passed through to
        :class:`AssertionFailure` so the caller can link failures back to
        specific DB rows for counterexample persistence.
    input:
        Optional stage input value (forwarded to the deterministic checks).
    """
    checks: list[DeterministicCheck] = []
    index_to_id: dict[int, int | None] = {}

    for spec in assertion_specs:
        check = _spec_to_check(spec)
        if check is not None:
            index_to_id[len(checks)] = spec.id
            checks.append(check)

    if not checks:
        return AssertionRunResult(passed=True, failures=[])

    eval_result: EvaluationResult = evaluate_deterministic_checks(output, checks, input=input)

    failures: list[AssertionFailure] = []
    for i, check_result in enumerate(eval_result.results):
        if not check_result.passed:
            failures.append(
                AssertionFailure(
                    assertion_id=index_to_id.get(i),
                    kind=check_result.type,
                    reason=check_result.reason,
                )
            )

    return AssertionRunResult(passed=not failures, failures=failures)
