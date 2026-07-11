"""LLM-powered rubric generator — the "RUBRIC ENGINE" of
``refract-parity-engine-plan.md`` §3 and M2 of ``refract-master-build-prompt.md``
§5: "one strong-model call per stage analyzing that stage's outputs across
all traces, emitting structured rubric (deterministic checks / weighted
judge criteria / downstream contract) as validated JSON."

Every actual model call goes through an injected ``call`` callable — this
module never touches ``litellm`` (or any provider) directly, and has
**zero FastAPI imports**, per the working rules for ``packages/core``.

Dependency injection, same spirit as ``scoring.py``'s injectable judge
callable
-------------------------------------------------------------------------
:func:`generate_rubric` takes ``call: Callable[..., LLMResponse]`` rather
than importing :func:`refract_core.llm.client.complete` itself, so a caller
can pass either ``complete`` directly (packages/core callers, CLI, tests) or
a closure around ``refract_api.llm_context.complete_with_workspace_credentials``
(apps/api, which needs a *workspace's* BYOK key scoped into the call) — the
two have different signatures (``complete(model, messages, **kw)`` vs.
``complete_with_workspace_credentials(db, workspace, model, messages, **kw)``),
so apps/api wires the gap with a small closure:
``lambda model, messages, **kw: complete_with_workspace_credentials(db, workspace, model, messages, **kw)``.
This keeps this module fully unaware of FastAPI, SQLAlchemy sessions, or
workspace credential storage — exactly the same boundary ``judge.py``/
``scoring.py`` already draw.

Raw LLM output vs. the strict ``deterministic.py`` check types
-------------------------------------------------------------------------
The model is asked (via ``response_format``) for a *looser* JSON shape
(:class:`_RawRubricOutput` — every deterministic-check field optional, no
discriminated union) than :mod:`refract_core.deterministic`'s strict
discriminated-union :data:`~refract_core.deterministic.DeterministicCheck`
type. This mirrors how ``judge.py`` separates the LLM's raw per-criterion
output (:class:`~refract_core.judge._CriterionJudgment`) from the final
computed result: a strict discriminated union is exactly the kind of schema
LLMs are prone to producing "almost-but-not-quite" (a stray extra field, a
regex check missing ``must_match``, ...), and ``response_format`` JSON-mode
compliance does not guarantee it validates against a *discriminated* union.
:func:`generate_rubric` therefore always runs a translation step
(``_translate_raw_check``) from the raw per-check dict down to only the
fields that check ``type`` actually uses, then validates the translated
list via :func:`refract_core.deterministic.parse_deterministic_checks`
before returning anything.

Handling invalid deterministic_checks output — the documented decision
-------------------------------------------------------------------------
Three options were on the table: hard-fail the whole generation, silently
drop bad checks, or retry once with a corrective note. This module does a
mix, in this order, per call:

1. **Fast path**: translate + validate the whole batch at once. If it all
   validates, done — no retry, no drops.
2. **Partial salvage, no retry**: if the batch fails but at least one
   individual check validates on its own, keep every check that validates
   in isolation and drop the rest, each with a human-readable reason
   recorded in :attr:`RubricGenerationResult.dropped_checks`. This is the
   common real-world case (four good checks, one with a typo'd field name)
   — retrying the *entire* (possibly expensive, ~85s-latency) call over one
   bad check is wasteful when 4/5 of the value is already usable.
3. **One corrective retry**: only when *every* proposed check was invalid
   (a systematic misunderstanding of the schema, not a one-off typo) or the
   response wasn't valid JSON at all. A single retry is made with the
   validation error appended to the prompt as a corrective note. If the
   retry also fails, :class:`RubricGenerationError` is raised — at that
   point there's nothing usable to silently return, and pretending a
   generation succeeded with an empty rubric would be worse than a clear
   error surfaced to the caller (apps/api turns this into a 422 — see
   ``refract_api.rubrics``).

``judge_criteria`` and ``downstream_contract`` are not subject to this
salvage logic — they're already loosely typed (a plain list of
``{name, weight, description}`` / a plain list of strings, per
``apps/api/src/refract_api/rubrics.py`` and ``seed_rubrics.py``) with no
discriminated union to fail against, so Pydantic's own field validation on
:class:`_RawRubricOutput` is sufficient.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from refract_core.deterministic import DeterministicCheck, parse_deterministic_checks
from refract_core.llm.client import LLMResponse

__all__ = [
    "StageOutputSample",
    "RubricGenerationResult",
    "RubricGenerationError",
    "generate_rubric",
    "DEFAULT_GENERATOR_TEMPERATURE",
    "DEFAULT_MAX_SAMPLES",
]

DEFAULT_GENERATOR_TEMPERATURE = 0.0
"""Rubric generation defaults to temperature 0 — this is a single
"analyze and summarize" call, not a creative task, and a deterministic,
reproducible rubric for the same inputs is more useful than sampling
variety."""

DEFAULT_MAX_SAMPLES = 8
"""Default cap on how many trace samples are included in the prompt. A
stage's benchmark set can have 20-100 traces (per the plan's BenchmarkSet
sizing) — sending all of them to the model would blow up prompt size/cost
for diminishing signal past a representative handful. Callers with a
specific reason to see more/fewer can override via ``max_samples``."""


class StageOutputSample(BaseModel):
    """One trace's input/output pair for a stage — the minimal slice of a
    ``StageRecord`` (see ``refract_core.trace.StageRecord`` /
    ``refract_api.models.StageRecord``) the generator actually needs.
    Deliberately not the full ``StageRecord`` (no ``rendered_prompt``,
    ``tokens``, ``latency_ms``, ``cost``) — the rubric only cares what went
    in and what came out, and callers (apps/api) fetch the real DB rows and
    narrow them down to this shape rather than this module doing its own
    DB query (see module docstring: pure/testable, already-fetched data in).
    """

    model_config = ConfigDict(extra="ignore")

    input: dict[str, Any] | str = Field(default_factory=dict)
    output: str


class RubricGenerationResult(BaseModel):
    """The validated result of one :func:`generate_rubric` call.

    ``deterministic_checks`` is already validated against
    :mod:`refract_core.deterministic`'s real check types and dumped back to
    plain dicts (``by_alias=True`` — e.g. ``schema_`` -> ``"schema"`` —
    matching the exact shape ``refract_api.rubrics``/``seed_rubrics`` store
    in ``Rubric.deterministic_checks``). ``judge_criteria`` matches the
    ``{name, weight, description}`` shape already in use across
    ``refract_api.rubrics``/``seed_rubrics``/``refract_core.judge``.
    """

    model_config = ConfigDict(extra="forbid")

    deterministic_checks: list[dict[str, Any]]
    judge_criteria: list[dict[str, Any]]
    downstream_contract: list[str]
    model: str = Field(description="The model that actually produced the (accepted) rubric content.")
    cost_usd: float | None = Field(description="Combined cost across the initial call and the retry, if one occurred.")
    latency_ms: float = Field(description="Combined wall-clock latency across the initial call and the retry, if one occurred.")
    dropped_checks: list[str] = Field(
        default_factory=list,
        description="Human-readable reasons any proposed deterministic check was dropped as invalid. "
        "Empty when every proposed check validated.",
    )


class RubricGenerationError(Exception):
    """The generator model's output could not be turned into a usable rubric
    at all, even after one corrective retry.

    Covers: response text that isn't valid JSON on both attempts, or every
    proposed deterministic check being invalid on both attempts. Deliberately
    a separate error category from :mod:`refract_core.llm.client`'s
    transport-error taxonomy (:class:`~refract_core.llm.client.TransientLLMError` /
    :class:`~refract_core.llm.client.PermanentLLMError`) — those are about
    *reaching* the model; this is about the model answering unusably once
    reached. Errors raised by the injected ``call`` callable itself are not
    caught here and propagate to the caller unchanged.
    """


# ---------------------------------------------------------------------------
# Raw (loose) LLM output shape — see module docstring's translation section.
# ---------------------------------------------------------------------------


class _RawDeterministicCheck(BaseModel):
    """One deterministic check as the model is free to propose it — every
    field optional (only the fields relevant to ``type`` are populated) so a
    single ``response_format`` schema can cover all six check types without
    a discriminated union the model would need to get exactly right on the
    first try."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    type: str
    id: str | None = None
    label: str | None = None
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    keys: list[str] | None = None
    pattern: str | None = None
    must_match: bool | None = None
    field: str | None = None
    flags: list[str] | None = None
    min_length: int | None = None
    max_length: int | None = None
    unit: str | None = None
    allowed_values: list[Any] | None = None
    id_pattern: str | None = None
    fields: list[str] | None = None
    ignore_case: bool | None = None


class _RawJudgeCriterion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    weight: float = Field(ge=0)
    description: str = ""


class _RawRubricOutput(BaseModel):
    """Structured JSON response requested from the generator model via
    ``response_format``."""

    model_config = ConfigDict(extra="ignore")

    deterministic_checks: list[_RawDeterministicCheck] = Field(default_factory=list)
    judge_criteria: list[_RawJudgeCriterion] = Field(default_factory=list)
    downstream_contract: list[str] = Field(default_factory=list)


# Which of _RawDeterministicCheck's optional fields are meaningful for each
# concrete check `type` — see refract_core.deterministic for the canonical
# definition of each. Only these (plus the always-present id/label/type) are
# carried into the translated dict, so e.g. a stray `keys` value the model
# left over from a different check type never leaks into a `regex` check.
_CHECK_TYPE_FIELDS: dict[str, tuple[str, ...]] = {
    "json_schema": ("schema",),
    "required_keys": ("keys",),
    "regex": ("pattern", "must_match", "field", "flags"),
    "length_bounds": ("min_length", "max_length", "unit", "field"),
    "enum_values": ("field", "allowed_values"),
    "no_hallucinated_ids": ("id_pattern", "fields", "ignore_case"),
}


def _translate_raw_check(raw: _RawDeterministicCheck) -> dict[str, Any]:
    """Narrow a loosely-typed raw check down to exactly the fields its
    declared ``type`` uses, dropping everything else (including fields left
    over from a type the model considered and didn't use)."""
    dumped = raw.model_dump(by_alias=True, exclude_none=True)
    check_type = dumped.get("type", "")
    translated: dict[str, Any] = {"type": check_type}
    if "id" in dumped:
        translated["id"] = dumped["id"]
    if "label" in dumped:
        translated["label"] = dumped["label"]
    for key in _CHECK_TYPE_FIELDS.get(check_type, ()):
        if key in dumped:
            translated[key] = dumped[key]
    return translated


def _translate_and_validate_checks(
    raw_checks: Sequence[_RawDeterministicCheck],
) -> tuple[list[DeterministicCheck], list[str]]:
    """Translate + validate raw checks against the real
    :mod:`refract_core.deterministic` types.

    Fast path: validate the whole translated batch at once (cheap, and
    preserves each check's own error message grouped together if it fails).
    Fallback: validate each translated check individually, keeping only the
    ones that validate on their own and recording a human-readable reason
    for each one dropped. See module docstring for the full policy.
    """
    translated = [_translate_raw_check(raw) for raw in raw_checks]
    if not translated:
        return [], []

    try:
        return parse_deterministic_checks(translated), []
    except ValidationError:
        pass

    valid: list[DeterministicCheck] = []
    dropped: list[str] = []
    for raw_dict in translated:
        try:
            valid.extend(parse_deterministic_checks([raw_dict]))
        except ValidationError as exc:
            dropped.append(f"Dropped invalid check {raw_dict!r}: {exc}")
    return valid, dropped


def _parse_raw_output(content: str) -> tuple[_RawRubricOutput | None, str | None]:
    """Returns ``(parsed, None)`` on success or ``(None, error_message)`` on failure. Never raises."""
    try:
        return _RawRubricOutput.model_validate_json(content), None
    except (ValidationError, ValueError) as exc:
        return None, str(exc)


def _sum_optional(a: float | None, b: float | None) -> float | None:
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are an expert rubric author for a model-migration parity engine. "
    "You will be shown one stage of a multi-stage LLM pipeline: its prompt "
    "template and a handful of real benchmark outputs (proven-good "
    "reference behavior) produced by running that prompt across different "
    "inputs. Your job is to reverse-engineer, from these examples, a "
    "structured rubric that captures what makes an output for this stage "
    "correct — so that a DIFFERENT model's output for the SAME stage can "
    "later be checked against it for parity.\n\n"
    "Produce exactly three things as JSON:\n\n"
    "1. deterministic_checks — cheap, code-checkable rules that EVERY "
    "benchmark example you were shown actually satisfies. Only include a "
    "check if you are confident all of the examples satisfy it — a check "
    "that would fail even one of the examples you were shown is worse than "
    "no check at all. An empty list is completely fine if nothing is safely "
    "checkable this way. Each check must use exactly one of these six "
    "shapes (use the exact field names given, omit fields that don't apply "
    "to the type you chose):\n"
    '   - {"type": "json_schema", "schema": <small JSON-Schema-like dict '
    "with type/properties/required/items/enum keys, recursively>}\n"
    '   - {"type": "required_keys", "keys": [<dot-path keys that must be '
    "present in the parsed JSON output, e.g. \"currency\" or \"items.0.sku\">]}\n"
    '   - {"type": "regex", "pattern": "<python re pattern>", "must_match": '
    "<bool, default true>, \"field\": <optional dot-path to check instead of "
    "the raw output text>}\n"
    '   - {"type": "length_bounds", "min_length": <int or omit>, '
    '"max_length": <int or omit>, "unit": "chars" or "words", "field": '
    "<optional dot-path>}\n"
    '   - {"type": "enum_values", "field": "<dot-path>", "allowed_values": '
    "[<literal values the field may take>]}\n"
    '   - {"type": "no_hallucinated_ids", "fields": <optional list of '
    'dot-paths to check instead of regex-scanning raw text>, "ignore_case": '
    "<bool, default true>} — flags ids/entities the output references that "
    "don't appear anywhere in the input.\n\n"
    "2. judge_criteria — a short list (2-5) of weighted, semantic quality "
    'criteria a human/LLM judge would use to compare a candidate output '
    'against these benchmarks: {"name": str, "weight": non-negative number, '
    '"description": str}. Weights are relative to each other and do not '
    "need to sum to 1.\n\n"
    "3. downstream_contract — a plain list of field names (dot-paths, if the "
    "output is structured JSON) that a NEXT pipeline stage would actually "
    "need to consume from this stage's output — the fields that truly "
    "matter, not the whole shape. If the output is not structured JSON, "
    "this can be an empty list.\n\n"
    "Respond with JSON only, matching the given schema exactly."
)


def _format_input(value: dict[str, Any] | str) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _build_messages(
    stage_name: str,
    stage_model: str,
    prompt_template: str,
    samples: Sequence[StageOutputSample],
    *,
    corrective_note: str | None = None,
) -> list[dict[str, str]]:
    parts: list[str] = [
        f"STAGE NAME: {stage_name}",
        f"MODEL THAT PRODUCED THESE BENCHMARK OUTPUTS: {stage_model}",
        f"PROMPT TEMPLATE FOR THIS STAGE:\n{prompt_template}",
    ]

    example_blocks = [
        f"EXAMPLE {i}:\nINPUT:\n{_format_input(sample.input)}\nOUTPUT:\n{sample.output}"
        for i, sample in enumerate(samples, start=1)
    ]
    parts.append(
        f"Below are {len(samples)} example input/output pair(s) from real benchmark "
        "traces for this stage (proven-good reference behavior):\n\n" + "\n\n".join(example_blocks)
    )

    if corrective_note:
        parts.append(f"IMPORTANT — your previous response could not be used: {corrective_note}")

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------


def generate_rubric(
    stage_name: str,
    stage_model: str,
    prompt_template: str,
    samples: Sequence[StageOutputSample | dict[str, Any]],
    *,
    call: Callable[..., LLMResponse],
    generator_model: str,
    temperature: float = DEFAULT_GENERATOR_TEMPERATURE,
    max_samples: int = DEFAULT_MAX_SAMPLES,
    timeout: float | None = None,
) -> RubricGenerationResult:
    """Analyze one stage's benchmark outputs across all its traces and emit
    a structured rubric (deterministic checks / weighted judge criteria /
    downstream contract), per M2's "one strong-model call per stage"
    (see module docstring for the retry/salvage policy on invalid checks).

    Parameters
    ----------
    stage_name, stage_model, prompt_template:
        Identify the stage being analyzed — the actual identity of the
        model that will be called for generation is ``generator_model``
        below, which need not be the same as ``stage_model`` (the model
        that *produced* the benchmark outputs being analyzed).
    samples:
        Already-fetched input/output pairs across the stage's traces (see
        :class:`StageOutputSample`) — this function makes no DB queries of
        its own (packages/core convention: pure/testable, caller fetches).
        Plain dicts are accepted and coerced. Must be non-empty.
    call:
        Injected LLM-calling callable, ``call(model, messages, **kwargs) ->
        LLMResponse`` — pass :func:`refract_core.llm.client.complete`
        directly, or a closure wrapping
        ``refract_api.llm_context.complete_with_workspace_credentials`` (see
        module docstring). Called once, or twice if exactly one corrective
        retry is triggered.
    generator_model:
        LiteLLM model string for the "strong model" doing the analysis —
        a required BYOK choice, no default (same reasoning as
        ``judge.judge_pairwise``'s ``model`` parameter).
    max_samples:
        Caps how many of ``samples`` are actually included in the prompt
        (see :data:`DEFAULT_MAX_SAMPLES`) — takes the first ``max_samples``
        as given; callers that want a specific subset (e.g. diverse/
        representative sampling) should pre-select before calling.

    Raises
    ------
    ValueError
        ``samples`` is empty.
    RubricGenerationError
        The model's output could not be turned into a usable rubric even
        after one corrective retry (see module docstring).
    Whatever ``call`` itself raises
        (e.g. :class:`~refract_core.llm.client.MissingAPIKeyError`,
        :class:`~refract_api.llm_context.ProviderKeyNotConfigured`,
        :class:`~refract_core.llm.client.TransientLLMError`) propagates
        unchanged — this function does not catch or retry transport errors,
        only off-schema *content* from a successful call.
    """
    if not samples:
        raise ValueError("generate_rubric requires at least one output sample")

    coerced = [s if isinstance(s, StageOutputSample) else StageOutputSample.model_validate(s) for s in samples]
    limited = coerced[:max_samples]

    messages = _build_messages(stage_name, stage_model, prompt_template, limited)
    response = call(
        generator_model,
        messages,
        temperature=temperature,
        timeout=timeout,
        response_format=_RawRubricOutput,
    )

    raw_output, parse_error = _parse_raw_output(response.content)
    cost_usd = response.cost_usd
    latency_ms = response.latency_ms
    resolved_model = response.model

    checks: list[DeterministicCheck] = []
    dropped_checks: list[str] = []
    if raw_output is not None:
        checks, dropped_checks = _translate_and_validate_checks(raw_output.deterministic_checks)

    # Retry exactly once, only for a systematic failure: unparseable JSON, or
    # every single proposed check turned out invalid. A *partial* salvage
    # (some checks valid, some dropped) does NOT retry — see module docstring.
    needs_retry = raw_output is None or bool(
        raw_output.deterministic_checks and not checks and dropped_checks
    )

    if needs_retry:
        corrective_note = parse_error or "; ".join(dropped_checks)
        retry_messages = _build_messages(
            stage_name, stage_model, prompt_template, limited, corrective_note=corrective_note
        )
        retry_response = call(
            generator_model,
            retry_messages,
            temperature=temperature,
            timeout=timeout,
            response_format=_RawRubricOutput,
        )
        cost_usd = _sum_optional(cost_usd, retry_response.cost_usd)
        latency_ms = latency_ms + retry_response.latency_ms
        resolved_model = retry_response.model

        retry_raw, retry_parse_error = _parse_raw_output(retry_response.content)
        if retry_raw is None:
            raise RubricGenerationError(
                f"Rubric generator model '{generator_model}' returned unusable output on "
                f"both the initial attempt and one corrective retry. Last error: {retry_parse_error}"
            )

        retry_checks, retry_dropped = _translate_and_validate_checks(retry_raw.deterministic_checks)
        if retry_raw.deterministic_checks and not retry_checks and retry_dropped:
            raise RubricGenerationError(
                "Rubric generator model "
                f"'{generator_model}' proposed only invalid deterministic checks on both the "
                f"initial attempt and one corrective retry. Last error(s): {'; '.join(retry_dropped)}"
            )

        raw_output = retry_raw
        checks, dropped_checks = retry_checks, retry_dropped

    assert raw_output is not None  # for type-checkers: every path above either sets this or raises

    return RubricGenerationResult(
        deterministic_checks=[check.model_dump(by_alias=True, exclude_none=True) for check in checks],
        judge_criteria=[criterion.model_dump() for criterion in raw_output.judge_criteria],
        downstream_contract=raw_output.downstream_contract,
        model=resolved_model,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        dropped_checks=dropped_checks,
    )
