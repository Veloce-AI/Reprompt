"""In-house prompt mutator — M3's "propose rewritten prompt variants" step.

Originally scoped (per the build spec this module replaces) to wrap
Microsoft's PromptWizard. Dropped after reading PromptWizard's actual
source (``promptwizard/glue/common/llm/llm_mgr.py``): it's hardcoded to
call OpenAI/Azure OpenAI's SDK directly with no pluggable LLM interface, so
routing it through a different provider would require running an actual
LiteLLM proxy — which conflicts both with this product's "any provider,
including customer self-hosted endpoints" requirement (the proxy trick only
bridges OpenAI-protocol-compatible backends) and with the explicit
"no proxy sidecar" constraint. This module gets the same practical outcome
— an LLM proposes improved prompt variants given a rubric and real examples
— as a single call through the engine's own already-universal
``llm/client.py``, so it works with any provider/self-hosted endpoint the
target model does, with zero special-casing, and needs no external
framework, submodule, or license review at all.

Same call-injection convention as ``rubric_generator.py``: ``call`` is
``Callable[..., LLMResponse]``, so a caller passes
:func:`reprompt_core.llm.client.complete` directly, or a closure wrapping
``reprompt_api.llm_context.complete_with_workspace_credentials``. Zero
FastAPI imports, per the working rules for ``packages/core``.

Retry policy mirrors ``rubric_generator.py``: one corrective retry only
when the model's output is unusable (bad JSON, or zero variants), never
when it's merely partial (e.g. it returned fewer variants than asked for —
using what's usable is better than discarding it and paying for a retry).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from reprompt_core.judge import JudgeResult
from reprompt_core.llm.client import LLMResponse
from reprompt_core.scoring import CompositeScore

__all__ = [
    "MutationExample",
    "PromptMutationResult",
    "PromptMutationError",
    "generate_prompt_mutations",
    "critique_and_refine",
    "select_few_shot_examples",
    "DEFAULT_MUTATOR_TEMPERATURE",
    "DEFAULT_NUM_VARIANTS",
]

DEFAULT_MUTATOR_TEMPERATURE = 0.7
"""Unlike rubric generation's temperature=0 (a single "analyze and
summarize" call), mutation wants real variety across the returned variants
— a single deterministic rewrite would defeat the point of generating
several candidates to try."""

DEFAULT_NUM_VARIANTS = 3


class MutationExample(BaseModel):
    """One benchmark input/output pair shown to the mutator model as
    context for what the rewritten prompt still needs to produce. Same
    minimal shape as ``rubric_generator.StageOutputSample`` — this module
    makes no DB queries of its own; the caller fetches real
    ``StageRecord`` rows and narrows them down to this shape."""

    model_config = ConfigDict(extra="ignore")

    input: dict[str, Any] | str = Field(default_factory=dict)
    output: str


class PromptMutationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variants: list[str] = Field(min_length=1)
    model: str = Field(description="The model that actually produced the (accepted) variants.")
    cost_usd: float | None = Field(description="Combined cost across the initial call and the retry, if one occurred.")
    latency_ms: float = Field(description="Combined wall-clock latency across the initial call and the retry, if one occurred.")
    critique: str | None = Field(
        default=None,
        description="Why the candidate scored the way it did, in the model's own words — only "
        "populated by critique_and_refine (which always has something to critique); left None by "
        "generate_prompt_mutations, which has no prior candidate to critique. Previously computed "
        "then discarded (only refined_prompt survived) - see DEV_TRACKER.md's Phase B note.",
    )


class PromptMutationError(Exception):
    """The mutator model's output could not be turned into any usable
    prompt variant, even after one corrective retry.

    Distinct from :mod:`reprompt_core.llm.client`'s transport-error taxonomy
    — see ``rubric_generator.RubricGenerationError`` for the same split.
    Errors raised by the injected ``call`` callable itself are not caught
    here and propagate to the caller unchanged; the optimizer loop treats
    this specific exception as "degrade to the original prompt only", not
    as a reason to abort the whole stage.
    """


class _RawMutationOutput(BaseModel):
    """Structured JSON response requested from the mutator model."""

    model_config = ConfigDict(extra="ignore")

    variants: list[str] = Field(default_factory=list)


def _parse_raw_output(content: str) -> tuple[_RawMutationOutput | None, str | None]:
    """Returns ``(parsed, None)`` on success or ``(None, error_message)`` on failure. Never raises."""
    try:
        return _RawMutationOutput.model_validate_json(content), None
    except (ValidationError, ValueError) as exc:
        return None, str(exc)


def _sum_optional(a: float | None, b: float | None) -> float | None:
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)


_SYSTEM_PROMPT_TEMPLATE = (
    "You are an expert prompt engineer helping migrate one stage of an LLM "
    "pipeline to a different, cheaper target model. You will be shown the "
    "stage's original prompt template, a rubric describing what a correct "
    "output looks like, and a handful of real input/output examples the "
    "original prompt reliably produces. Propose {num_variants} rewritten "
    "prompt variants for the TARGET model that are as likely as possible "
    "to keep producing outputs matching the rubric and examples.\n\n"
    "Keep every {{{{variable}}}} placeholder from the original prompt "
    "template exactly as-is (same names, same double-curly-brace syntax) "
    "— do not invent new placeholders or remove ones the examples rely on. "
    "Only change wording, structure, and instructions around them.\n\n"
    "Vary the variants meaningfully from each other (different levels of "
    "explicitness, different instruction ordering, few-shot vs zero-shot "
    "framing) rather than producing near-duplicates.\n\n"
    'Respond with JSON only, matching this schema: {{"variants": '
    '[<prompt text 1>, <prompt text 2>, ...]}}.'
)


def _format_input(value: dict[str, Any] | str) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _format_rubric(rubric: dict[str, Any]) -> str:
    lines: list[str] = []
    checks = rubric.get("deterministic_checks") or []
    if checks:
        lines.append("Deterministic checks the output must satisfy:")
        lines.extend(f"  - {check}" for check in checks)
    criteria = rubric.get("judge_criteria") or []
    if criteria:
        lines.append("Quality criteria a judge will score against:")
        for criterion in criteria:
            name = criterion.get("name", "") if isinstance(criterion, dict) else ""
            description = criterion.get("description", "") if isinstance(criterion, dict) else ""
            lines.append(f"  - {name}: {description}")
    return "\n".join(lines) if lines else "(no rubric provided)"


def _build_messages(
    prompt_template: str,
    target_model: str,
    rubric: dict[str, Any],
    examples: Sequence[MutationExample],
    num_variants: int,
    *,
    corrective_note: str | None = None,
) -> list[dict[str, str]]:
    parts: list[str] = [
        f"ORIGINAL PROMPT TEMPLATE:\n{prompt_template}",
        f"TARGET MODEL: {target_model}",
        _format_rubric(rubric),
    ]

    example_blocks = [
        f"EXAMPLE {i}:\nINPUT:\n{_format_input(ex.input)}\nOUTPUT:\n{ex.output}"
        for i, ex in enumerate(examples, start=1)
    ]
    if example_blocks:
        parts.append(
            f"Below are {len(examples)} example input/output pair(s) the original "
            "prompt reliably produces:\n\n" + "\n\n".join(example_blocks)
        )

    if corrective_note:
        parts.append(f"IMPORTANT — your previous response could not be used: {corrective_note}")

    return [
        {"role": "system", "content": _SYSTEM_PROMPT_TEMPLATE.format(num_variants=num_variants)},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


class _RawCritiqueOutput(BaseModel):
    """Structured JSON response requested from the critique/refine call."""

    model_config = ConfigDict(extra="ignore")

    critique: str = ""
    refined_prompt: str = ""


class _RawFewShotSelection(BaseModel):
    """Structured JSON response requested from the few-shot selection call.

    Indices, not text — the model picks *which* already-real examples to
    use by position, never generates new example text. This makes "only
    ever returns entries actually present in the input" true by
    construction (an out-of-range or malformed index is simply dropped),
    rather than relying on fuzzy text matching against the model's output.
    """

    model_config = ConfigDict(extra="ignore")

    indices: list[int] = Field(default_factory=list)


def _format_score_feedback(score: CompositeScore, judge_result: JudgeResult | None = None) -> str:
    """Human-readable summary of why a candidate scored the way it did —
    the concrete context :func:`critique_and_refine` shows the model, drawn
    directly from :class:`~reprompt_core.scoring.CompositeScore` rather than
    a bare number, so the critique step can reason about *specific* failed
    checks/criteria instead of guessing from a score alone.

    ``judge_result``, when supplied, is a real
    :class:`~reprompt_core.judge.JudgeResult` (e.g. from
    :func:`reprompt_core.judge.judge_single_pass`) obtained for this specific
    candidate — its per-criterion ``reasoning`` text is included so the
    critique step can reason against the actual dominant scoring signal
    (the judge is ``DEFAULT_WEIGHTS.judge``'s largest weight — see
    ``scoring.py``) instead of always being told the judge "was not run",
    which is what happened before this was threaded through (see
    ``DEV_TRACKER.md``'s Phase 1 quality-fixes note)."""
    lines: list[str] = [f"Overall score: {score.final_score:.2f} (0.0-1.0 scale)"]

    if score.gated:
        lines.append(f"HARD GATE FAILED: {score.gate_reason}")

    failures = score.deterministic.failures
    if failures:
        lines.append("Failed deterministic checks:")
        lines.extend(f"  - {f.label}: {f.reason}" for f in failures)
    elif score.deterministic.results:
        lines.append("All deterministic checks passed.")

    lines.append(f"Embedding similarity to benchmark output: {score.embedding_score:.2f}")

    if judge_result is not None:
        lines.append(f"AI judge overall score: {judge_result.overall_score:.2f}")
        lines.append("AI judge per-criterion reasoning:")
        for criterion in judge_result.criteria:
            lines.append(f"  - {criterion.name} (score {criterion.score:.2f}): {criterion.reasoning}")
        if judge_result.low_confidence:
            lines.append(
                "Note: this judge call showed high disagreement risk; treat the reasoning above "
                "as directional, not definitive."
            )
    elif score.judge_score is not None:
        lines.append(f"AI judge score: {score.judge_score:.2f}")
    elif not score.gated:
        lines.append("AI judge was not run for this candidate (skipped or not yet available).")

    return "\n".join(lines)


_CRITIQUE_SYSTEM_PROMPT = (
    "You are an expert prompt engineer reviewing a candidate prompt that "
    "underperformed during a model migration. You will be shown the "
    "candidate prompt, exactly why it scored the way it did (which checks "
    "failed and why, or how similar/different it was from the proven-good "
    "benchmark), the rubric it's being measured against, and real "
    "input/output examples the ORIGINAL (pre-migration) prompt reliably "
    "produces.\n\n"
    "Do two things:\n"
    "1. Write a short, specific critique — why did THIS candidate likely "
    "score the way it did, given the concrete failures/scores shown? "
    "Reference the actual failed checks or score gaps, not generic advice.\n"
    "2. Propose ONE refined prompt that directly addresses that critique. "
    "Keep every {{variable}} placeholder from the candidate exactly as-is "
    "(same names, same double-curly-brace syntax) — do not invent new "
    "placeholders or remove ones the examples rely on.\n\n"
    'Respond with JSON only, matching this schema: {"critique": '
    '"<your critique>", "refined_prompt": "<the refined prompt text>"}.'
)


def _build_critique_messages(
    prompt_variant: str,
    score: CompositeScore,
    examples: Sequence[MutationExample],
    rubric: dict[str, Any],
    target_model: str,
    *,
    judge_result: JudgeResult | None = None,
    corrective_note: str | None = None,
) -> list[dict[str, str]]:
    parts: list[str] = [
        f"CANDIDATE PROMPT (for target model {target_model}):\n{prompt_variant}",
        f"WHY IT SCORED THE WAY IT DID:\n{_format_score_feedback(score, judge_result)}",
        _format_rubric(rubric),
    ]

    example_blocks = [
        f"EXAMPLE {i}:\nINPUT:\n{_format_input(ex.input)}\nOUTPUT:\n{ex.output}"
        for i, ex in enumerate(examples, start=1)
    ]
    if example_blocks:
        parts.append(
            f"Below are {len(examples)} example input/output pair(s) the ORIGINAL "
            "prompt reliably produces:\n\n" + "\n\n".join(example_blocks)
        )

    if corrective_note:
        parts.append(f"IMPORTANT — your previous response could not be used: {corrective_note}")

    return [
        {"role": "system", "content": _CRITIQUE_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _parse_critique_output(content: str) -> tuple[_RawCritiqueOutput | None, str | None]:
    try:
        parsed = _RawCritiqueOutput.model_validate_json(content)
    except (ValidationError, ValueError) as exc:
        return None, str(exc)
    if not parsed.refined_prompt.strip():
        return None, "refined_prompt was empty."
    return parsed, None


def critique_and_refine(
    prompt_variant: str,
    score: CompositeScore,
    original_examples: Sequence[MutationExample | dict[str, Any]],
    rubric: dict[str, Any],
    target_model: str,
    *,
    call: Callable[..., LLMResponse],
    mutator_model: str | None = None,
    temperature: float = DEFAULT_MUTATOR_TEMPERATURE,
    timeout: float | None = None,
    judge_result: JudgeResult | None = None,
) -> PromptMutationResult:
    """Prism's critique-then-refine step (see ``DEV_TRACKER.md``'s Phase 1
    spec for the full design rationale).

    One LLM call: given a prompt variant that scored poorly, exactly why it
    scored that way (``score`` — see :func:`_format_score_feedback`), and
    real examples the original prompt reliably produces, produce a short
    critique and ONE refined prompt addressing it. Same
    retry-once-on-total-failure convention as :func:`generate_prompt_mutations`.

    ``judge_result``, when supplied by the caller (``loop.py``'s
    ``_optimize_stage_prism``, which runs one real single-pass judge call —
    :func:`reprompt_core.judge.judge_single_pass` — on each of the round's
    weakest candidates before critiquing them), is threaded into the
    critique prompt via :func:`_format_score_feedback` so the critique
    reasons against the judge's actual per-criterion feedback — the
    dominant term in the real composite score formula (see
    ``scoring.DEFAULT_WEIGHTS``) — instead of being told the judge simply
    "was not run". ``None`` (the default) preserves the prior behavior for
    any caller that doesn't have a judge result available.

    Returns
    -------
    :class:`PromptMutationResult` whose ``variants`` list always has
    exactly one entry (the refined prompt) — reuses the same result type
    as :func:`generate_prompt_mutations` so callers can treat both
    uniformly.

    Raises
    ------
    :class:`PromptMutationError`
        The model's output could not be turned into a usable refined
        prompt, even after one corrective retry. Callers (``loop.py``)
        treat this as "keep the un-refined candidate" for this round, not
        a reason to abort the stage.
    """
    coerced = [e if isinstance(e, MutationExample) else MutationExample.model_validate(e) for e in original_examples]
    model_for_call = mutator_model or target_model

    messages = _build_critique_messages(prompt_variant, score, coerced, rubric, target_model, judge_result=judge_result)
    response = call(
        model_for_call,
        messages,
        temperature=temperature,
        timeout=timeout,
        response_format=_RawCritiqueOutput,
    )

    raw_output, parse_error = _parse_critique_output(response.content)
    cost_usd = response.cost_usd
    latency_ms = response.latency_ms
    resolved_model = response.model

    if raw_output is None:
        retry_messages = _build_critique_messages(
            prompt_variant, score, coerced, rubric, target_model,
            judge_result=judge_result, corrective_note=parse_error,
        )
        retry_response = call(
            model_for_call,
            retry_messages,
            temperature=temperature,
            timeout=timeout,
            response_format=_RawCritiqueOutput,
        )
        cost_usd = _sum_optional(cost_usd, retry_response.cost_usd)
        latency_ms = latency_ms + retry_response.latency_ms
        resolved_model = retry_response.model

        raw_output, retry_parse_error = _parse_critique_output(retry_response.content)
        if raw_output is None:
            raise PromptMutationError(
                f"Prompt mutator model '{model_for_call}' returned no usable critique/refinement on "
                f"both the initial attempt and one corrective retry. Last error: {retry_parse_error}"
            )

    return PromptMutationResult(
        variants=[raw_output.refined_prompt],
        model=resolved_model,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        critique=raw_output.critique.strip() or None,
    )


_FEW_SHOT_SYSTEM_PROMPT = (
    "You will be shown a prompt and a numbered list of real input/output "
    "examples available for it. Pick the {max_examples} examples (by "
    "number) that would be most illustrative as few-shot context appended "
    "to the prompt — the ones that best demonstrate correct behavior, "
    "especially any edge cases. Pick ONLY from the numbered examples "
    "shown — never invent new ones.\n\n"
    'Respond with JSON only, matching this schema: {{"indices": '
    "[<example number>, ...]}} using the example numbers as shown "
    "(starting at 1)."
)


def select_few_shot_examples(
    prompt: str,
    examples: Sequence[MutationExample | dict[str, Any]],
    *,
    call: Callable[..., LLMResponse],
    model: str,
    max_examples: int = 2,
    temperature: float = 0.0,
    timeout: float | None = None,
) -> list[MutationExample]:
    """Pick the most illustrative real benchmark examples to use as
    few-shot context for the winning prompt (Prism-only, optional — see
    ``DEV_TRACKER.md``'s Phase 1 spec).

    Picks by index from ``examples``, never fabricates new example text —
    see :class:`_RawFewShotSelection`'s docstring for why that's true by
    construction, not just by convention. Deterministic (``temperature=0``)
    since this is a selection task, not a creative one.

    Degrades gracefully rather than raising: if the model's output can't be
    parsed or selects nothing valid (even after one retry), falls back to
    the first ``max_examples`` of ``examples`` as-is — this is an optional
    quality enhancement (``include_few_shot`` defaults to ``False`` on the
    caller), not something worth failing a whole stage over.
    """
    coerced = [e if isinstance(e, MutationExample) else MutationExample.model_validate(e) for e in examples]
    if not coerced:
        return []
    if len(coerced) <= max_examples:
        return coerced

    numbered = "\n\n".join(
        f"EXAMPLE {i}:\nINPUT:\n{_format_input(ex.input)}\nOUTPUT:\n{ex.output}"
        for i, ex in enumerate(coerced, start=1)
    )
    messages = [
        {"role": "system", "content": _FEW_SHOT_SYSTEM_PROMPT.format(max_examples=max_examples)},
        {"role": "user", "content": f"PROMPT:\n{prompt}\n\n{numbered}"},
    ]

    for _attempt in range(2):  # initial + one retry, same convention as elsewhere in this module
        try:
            response = call(model, messages, temperature=temperature, timeout=timeout, response_format=_RawFewShotSelection)
            parsed = _RawFewShotSelection.model_validate_json(response.content)
        except Exception:  # noqa: BLE001 - any failure here (transport or parse) just falls through to retry/fallback
            continue
        selected = [coerced[i - 1] for i in parsed.indices if 1 <= i <= len(coerced)]
        if selected:
            return selected[:max_examples]

    return coerced[:max_examples]


def generate_prompt_mutations(
    prompt_template: str,
    target_model: str,
    rubric: dict[str, Any],
    examples: Sequence[MutationExample | dict[str, Any]],
    *,
    call: Callable[..., LLMResponse],
    mutator_model: str | None = None,
    num_variants: int = DEFAULT_NUM_VARIANTS,
    temperature: float = DEFAULT_MUTATOR_TEMPERATURE,
    timeout: float | None = None,
) -> PromptMutationResult:
    """Propose ``num_variants`` rewritten prompt variants for ``target_model``.

    Parameters
    ----------
    prompt_template:
        The stage's original prompt template (with ``{{variable}}``
        placeholders) to rewrite.
    target_model:
        LiteLLM model string the variants are being written for.
    rubric:
        ``{"deterministic_checks": [...], "judge_criteria": [...]}`` —
        same shape as ``Rubric.deterministic_checks``/``judge_criteria``
        (apps/api). Either key may be absent/empty.
    examples:
        Already-fetched benchmark input/output pairs (see
        :class:`MutationExample`) — this function makes no DB queries of
        its own. May be empty (the model is simply given no examples).
    call:
        Injected LLM-calling callable — pass
        :func:`reprompt_core.llm.client.complete` directly, or a closure
        wrapping ``complete_with_workspace_credentials`` (see module
        docstring).
    mutator_model:
        Which model actually performs the rewriting. Defaults to
        ``target_model`` itself (reuses the same BYOK credential the
        optimizer already has scoped for that provider, so no second
        provider key is required just to mutate a prompt).

    Raises
    ------
    :class:`PromptMutationError`
        The model's output could not be turned into any usable variant,
        even after one corrective retry.
    Whatever ``call`` itself raises
        Propagates unchanged — this function does not catch or retry
        transport errors, only off-schema *content* from a successful call.
    """
    coerced = [e if isinstance(e, MutationExample) else MutationExample.model_validate(e) for e in examples]
    model_for_call = mutator_model or target_model

    messages = _build_messages(prompt_template, target_model, rubric, coerced, num_variants)
    response = call(
        model_for_call,
        messages,
        temperature=temperature,
        timeout=timeout,
        response_format=_RawMutationOutput,
    )

    raw_output, parse_error = _parse_raw_output(response.content)
    cost_usd = response.cost_usd
    latency_ms = response.latency_ms
    resolved_model = response.model

    needs_retry = raw_output is None or not raw_output.variants

    if needs_retry:
        corrective_note = parse_error or "No prompt variants were returned."
        retry_messages = _build_messages(
            prompt_template, target_model, rubric, coerced, num_variants, corrective_note=corrective_note
        )
        retry_response = call(
            model_for_call,
            retry_messages,
            temperature=temperature,
            timeout=timeout,
            response_format=_RawMutationOutput,
        )
        cost_usd = _sum_optional(cost_usd, retry_response.cost_usd)
        latency_ms = latency_ms + retry_response.latency_ms
        resolved_model = retry_response.model

        retry_raw, retry_parse_error = _parse_raw_output(retry_response.content)
        if retry_raw is None or not retry_raw.variants:
            raise PromptMutationError(
                f"Prompt mutator model '{model_for_call}' returned no usable prompt variants on "
                f"both the initial attempt and one corrective retry. Last error: "
                f"{retry_parse_error or 'empty variants list'}"
            )
        raw_output = retry_raw

    assert raw_output is not None  # for type-checkers: every path above either sets this or raises

    return PromptMutationResult(
        variants=raw_output.variants,
        model=resolved_model,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
    )
