"""Pairwise LLM judge — the ``w2`` (LLM-judge) term of the evaluation engine.

Per ``reprompt-parity-engine-plan.md`` §3 ("Judge: pairwise comparison
(benchmark vs candidate), position-swapped to kill order bias, strong model
as judge (BYOK)"), this module compares one stage's benchmark output against
a candidate output on a rubric's weighted ``judge_criteria`` and returns a
structured, per-criterion score.

Every actual model call goes through :func:`reprompt_core.llm.client.complete`
— this module never touches ``litellm`` (or any provider) directly, and has
**zero FastAPI imports**, per the working rules for ``packages/core``.

``judge_criteria`` shape
-------------------------
Mirrors the shape already in use by ``Rubric.judge_criteria`` (see
``apps/api/src/reprompt_api/rubrics.py::JudgeCriterionIn`` and
``apps/api/src/reprompt_api/seed_rubrics.py::sample_judge_criteria``)::

    {"name": str, "weight": float (>= 0), "description": str}

Redefined here as :class:`JudgeCriterion` rather than imported from
``apps/api`` — ``packages/core`` is the headless engine; ``apps/api`` is a
thin HTTP shell over it, so the dependency only ever points one way.
``weight`` is *relative* among a stage's own criteria and does not need to
sum to 1 (see ``sample_judge_criteria``'s docstring) — :func:`judge_pairwise`
normalizes by the sum of weights actually present, not at authoring time.

Position-swap design (kills order bias)
-----------------------------------------
The plan calls for "pairwise comparison ... position-swapped to kill order
bias". Concretely, :func:`judge_pairwise` calls
:func:`reprompt_core.llm.client.complete` **twice** for the same
benchmark/candidate pair:

* Call 1: the benchmark output is presented as "OUTPUT 1", the candidate as
  "OUTPUT 2".
* Call 2: the same two outputs, but swapped — candidate as "OUTPUT 1",
  benchmark as "OUTPUT 2".

Both calls always label each output's *role* explicitly ("BENCHMARK OUTPUT
(proven-good reference)" / "CANDIDATE OUTPUT (being evaluated)") — that
labeling never swaps, because the judge task ("does the candidate match the
benchmark?") is inherently asymmetric and the model needs to know which is
which to answer it at all. What swaps is *presentation order* (which output
physically appears first), which is exactly the axis LLM judges are known to
carry position bias on. The two calls' scores are then averaged per
criterion — a simple, robust combination that cancels out a consistent
first/second-position preference in either direction.

Disagreement / low-confidence signal
--------------------------------------
Rather than silently averaging away a case where the two orderings produced
wildly different scores for the same criterion, :func:`judge_pairwise` also
computes ``disagreement`` — the *maximum*, not the mean, of the two orderings'
absolute score deltas across all criteria — and sets ``low_confidence=True``
if it exceeds ``disagreement_threshold`` (default 0.3). Max rather than mean
is deliberate: a single criterion the judge scored very differently
depending only on presentation order already means "this judgment isn't
reliable", even if every other criterion happened to agree — averaging that
away would hide exactly the failure mode position-swapping exists to catch.
The result is still returned (never discarded) with the averaged score, but
``low_confidence`` lets a caller flag the candidate for human review, retry
with a different judge model, or simply not auto-accept it.

Weighting design: model scores per-criterion, we do the arithmetic
----------------------------------------------------------------------
The judge model is asked to score each criterion independently (0.0-1.0)
plus a short reasoning, but is **not** asked to compute the final weighted
score itself. :func:`judge_pairwise` computes
``overall_score = sum(score_i * weight_i) / sum(weight_i)`` in Python. This
is deliberate: LLMs are unreliable at consistent weighted arithmetic
(especially across two separate calls that must combine sensibly), while our
own weights are exact data we already have. Keeping the model's job to
"judge quality per criterion" and our job to "do the math" also means the
weighting logic is unit-testable without any model calls at all.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from reprompt_core.llm import client as llm_client

__all__ = [
    "JudgeCriterion",
    "CriterionJudgment",
    "JudgeResult",
    "JudgeResponseError",
    "judge_pairwise",
    "DEFAULT_JUDGE_TEMPERATURE",
    "DEFAULT_DISAGREEMENT_THRESHOLD",
]

DEFAULT_JUDGE_TEMPERATURE = 0.0
"""Judge calls default to temperature 0 so that observed disagreement
between the two position-swapped calls reflects the order swap itself, not
ordinary sampling noise layered on top of it."""

DEFAULT_DISAGREEMENT_THRESHOLD = 0.3
"""Per-criterion score delta (0-1 scale) between the two orderings above
which :func:`judge_pairwise` sets ``low_confidence=True``. 0.3 is a
deliberately loose default (scores routinely wobble a little between calls);
it is meant to catch a judge that meaningfully flip-flopped, not float noise."""


class JudgeCriterion(BaseModel):
    """One weighted judge criterion. See module docstring for the shape note."""

    name: str = Field(min_length=1)
    weight: float = Field(ge=0)
    description: str = ""


class _CriterionJudgment(BaseModel):
    """One criterion's score from a single (single-ordering) judge call —
    the shape requested from the model via ``response_format``."""

    model_config = ConfigDict(extra="ignore")

    name: str
    score: float = Field(ge=0, le=1)
    reasoning: str = ""


class _JudgeCallOutput(BaseModel):
    """Structured JSON response requested from the judge model."""

    model_config = ConfigDict(extra="ignore")

    criteria: list[_CriterionJudgment]


class CriterionJudgment(BaseModel):
    """One criterion's final judgment, combined across both position-swapped calls."""

    model_config = ConfigDict(extra="forbid")

    name: str
    weight: float
    score: float = Field(ge=0, le=1, description="Average of the two orderings' scores for this criterion.")
    reasoning: str
    order_disagreement: float = Field(
        ge=0, le=1, description="Absolute difference between the two orderings' raw scores for this criterion."
    )


class JudgeResult(BaseModel):
    """The full result of one :func:`judge_pairwise` call."""

    model_config = ConfigDict(extra="forbid")

    overall_score: float = Field(ge=0, le=1, description="Weighted average of per-criterion scores.")
    criteria: list[CriterionJudgment]
    model: str
    disagreement: float = Field(
        ge=0, le=1, description="Max per-criterion order_disagreement across all criteria."
    )
    low_confidence: bool = Field(
        description="True if `disagreement` exceeded the disagreement_threshold — the two "
        "position-swapped calls meaningfully disagreed on at least one criterion."
    )
    cost_usd: float | None = Field(description="Combined cost of both calls, or None if cost was unknown for both.")
    latency_ms: float = Field(description="Combined wall-clock latency of both calls.")


class JudgeResponseError(Exception):
    """The judge model's structured response could not be used as-is.

    Covers response text that isn't valid JSON, that doesn't match the
    requested schema, or that's missing a score for one or more requested
    criteria — despite ``response_format`` having been requested. This is
    deliberately a separate error category from
    :mod:`reprompt_core.llm.client`'s transport-error taxonomy
    (:class:`~reprompt_core.llm.client.TransientLLMError` /
    :class:`~reprompt_core.llm.client.PermanentLLMError`): those are about
    *reaching* the model; this is about the model answering off-schema once
    reached. Errors raised by :func:`reprompt_core.llm.client.complete`
    itself are not caught here and propagate to the caller unchanged.
    """


def _coerce_criteria(judge_criteria: Sequence[JudgeCriterion | dict[str, Any]]) -> list[JudgeCriterion]:
    criteria = [c if isinstance(c, JudgeCriterion) else JudgeCriterion.model_validate(c) for c in judge_criteria]
    if not criteria:
        raise ValueError("judge_pairwise requires at least one judge criterion")
    return criteria


def _format_input(input_: str | dict[str, Any] | None) -> str | None:
    if input_ is None:
        return None
    if isinstance(input_, str):
        return input_
    return json.dumps(input_, ensure_ascii=False, indent=2)


_SYSTEM_PROMPT = (
    "You are an exacting evaluator for a model-migration parity engine. You are "
    "shown a BENCHMARK output (a proven-good reference for one stage of an LLM "
    "pipeline) and a CANDIDATE output (a new model's attempt at the same stage). "
    "Score how well the CANDIDATE achieves the same intent and quality as the "
    "BENCHMARK, against each weighted criterion listed below. Judge substance, "
    "not surface wording — the candidate does not need to match the benchmark's "
    "exact phrasing, structure, or length to score well on a criterion, only the "
    "quality that criterion actually describes. Score each criterion "
    "independently on a 0.0-1.0 scale, where 1.0 means the candidate fully "
    "matches the benchmark on that criterion and 0.0 means it completely fails "
    "it. Respond with JSON only, matching the given schema exactly — exactly one "
    "entry per criterion, using the exact criterion name given."
)


def _build_messages(
    criteria: list[JudgeCriterion],
    benchmark_output: str,
    candidate_output: str,
    input_: str | dict[str, Any] | None,
    *,
    benchmark_first: bool,
) -> list[dict[str, str]]:
    parts: list[str] = []

    input_text = _format_input(input_)
    if input_text is not None:
        parts.append(f"ORIGINAL INPUT TO THIS STAGE:\n{input_text}")

    benchmark_block = f"BENCHMARK OUTPUT (proven-good reference):\n{benchmark_output}"
    candidate_block = f"CANDIDATE OUTPUT (being evaluated for parity with the benchmark):\n{candidate_output}"
    if benchmark_first:
        parts.append(f"OUTPUT 1:\n{benchmark_block}")
        parts.append(f"OUTPUT 2:\n{candidate_block}")
    else:
        parts.append(f"OUTPUT 1:\n{candidate_block}")
        parts.append(f"OUTPUT 2:\n{benchmark_block}")

    criteria_lines = [
        f"{i}. {c.name} (weight={c.weight:g}): {c.description}"
        for i, c in enumerate(criteria, start=1)
    ]
    parts.append(
        "CRITERIA (score the CANDIDATE against each, relative to the BENCHMARK; "
        "weights show relative importance and do not need to sum to 1):\n" + "\n".join(criteria_lines)
    )

    parts.append(
        "Return JSON of the shape "
        '{"criteria": [{"name": "<exact criterion name>", "score": <0.0-1.0>, '
        '"reasoning": "<1-2 sentences>"}, ...]} with exactly one entry per '
        "criterion listed above, using the exact names given."
    )

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _run_judge_call(
    model: str,
    criteria: list[JudgeCriterion],
    benchmark_output: str,
    candidate_output: str,
    input_: str | dict[str, Any] | None,
    *,
    benchmark_first: bool,
    temperature: float,
    timeout: float | None,
) -> tuple[dict[str, _CriterionJudgment], Any]:
    messages = _build_messages(
        criteria, benchmark_output, candidate_output, input_, benchmark_first=benchmark_first
    )
    response = llm_client.complete(
        model,
        messages,
        temperature=temperature,
        timeout=timeout,
        response_format=_JudgeCallOutput,
    )

    try:
        parsed = _JudgeCallOutput.model_validate_json(response.content)
    except (ValidationError, ValueError) as exc:
        raise JudgeResponseError(
            f"Judge model '{model}' returned a response that doesn't match the "
            f"expected JSON schema: {exc}. Raw content: {response.content!r}"
        ) from exc

    by_normalized_name = {j.name.strip().lower(): j for j in parsed.criteria}
    missing = [c.name for c in criteria if c.name.strip().lower() not in by_normalized_name]
    if missing:
        raise JudgeResponseError(
            f"Judge model '{model}' did not return a score for criterion/criteria: "
            f"{', '.join(missing)}."
        )

    scores = {c.name: by_normalized_name[c.name.strip().lower()] for c in criteria}
    return scores, response


def judge_pairwise(
    benchmark_output: str,
    candidate_output: str,
    judge_criteria: Sequence[JudgeCriterion | dict[str, Any]],
    *,
    model: str,
    input: str | dict[str, Any] | None = None,  # noqa: A002 - mirrors StageRecord.input naming
    temperature: float = DEFAULT_JUDGE_TEMPERATURE,
    timeout: float | None = None,
    disagreement_threshold: float = DEFAULT_DISAGREEMENT_THRESHOLD,
) -> JudgeResult:
    """Score ``candidate_output`` against ``benchmark_output`` on weighted criteria.

    Makes exactly two calls to :func:`reprompt_core.llm.client.complete` — see
    the module docstring for the position-swap design. ``model`` is a
    required LiteLLM model string (e.g. ``"claude-sonnet-4-5"``,
    ``"gpt-4o"``) for the *judge*, independent of whichever model produced
    ``candidate_output``; there is no default, since which model is "strong
    enough to judge" is a BYOK choice the caller must make (plan §10, open
    question 1).

    Raises whatever :func:`reprompt_core.llm.client.complete` raises
    (``MissingAPIKeyError``, ``TransientLLMError``, ...) unmodified, and
    :class:`JudgeResponseError` if either call's response doesn't match the
    requested schema.
    """
    criteria = _coerce_criteria(judge_criteria)

    scores_benchmark_first, response_a = _run_judge_call(
        model,
        criteria,
        benchmark_output,
        candidate_output,
        input,
        benchmark_first=True,
        temperature=temperature,
        timeout=timeout,
    )
    scores_candidate_first, response_b = _run_judge_call(
        model,
        criteria,
        benchmark_output,
        candidate_output,
        input,
        benchmark_first=False,
        temperature=temperature,
        timeout=timeout,
    )

    judgments: list[CriterionJudgment] = []
    for criterion in criteria:
        judged_a = scores_benchmark_first[criterion.name]
        judged_b = scores_candidate_first[criterion.name]
        combined_score = (judged_a.score + judged_b.score) / 2
        order_disagreement = abs(judged_a.score - judged_b.score)

        reasoning_a = judged_a.reasoning.strip()
        reasoning_b = judged_b.reasoning.strip()
        if reasoning_a == reasoning_b or not reasoning_b:
            reasoning = reasoning_a
        elif not reasoning_a:
            reasoning = reasoning_b
        else:
            reasoning = f"[benchmark shown first] {reasoning_a} [candidate shown first] {reasoning_b}"

        judgments.append(
            CriterionJudgment(
                name=criterion.name,
                weight=criterion.weight,
                score=combined_score,
                reasoning=reasoning,
                order_disagreement=order_disagreement,
            )
        )

    weight_total = sum(c.weight for c in criteria)
    if weight_total > 0:
        overall_score = sum(j.score * j.weight for j in judgments) / weight_total
    else:
        # All criteria weighted 0 (unusual, but not invalid per the ">= 0"
        # constraint): fall back to a plain average rather than dividing by 0.
        overall_score = sum(j.score for j in judgments) / len(judgments)

    disagreement = max((j.order_disagreement for j in judgments), default=0.0)

    cost_a = response_a.cost_usd
    cost_b = response_b.cost_usd
    cost_usd = None if cost_a is None and cost_b is None else (cost_a or 0.0) + (cost_b or 0.0)

    return JudgeResult(
        overall_score=overall_score,
        criteria=judgments,
        model=response_a.model,
        disagreement=disagreement,
        low_confidence=disagreement > disagreement_threshold,
        cost_usd=cost_usd,
        latency_ms=response_a.latency_ms + response_b.latency_ms,
    )
