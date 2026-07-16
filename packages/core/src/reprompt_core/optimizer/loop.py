"""M3 optimizer loop — the "try it, score it, keep the best" search per
stage, per ``reprompt-parity-engine-plan.md`` §3(c)-(d).

Two strategies (``strategy="simple"|"prism"`` on :func:`run_optimizer`),
selected by the caller (``apps/api``'s ``OPTIMIZER_STRATEGY`` env var):

* **simple** (default) — one mutation call
  (:func:`reprompt_core.optimizer.mutator.generate_prompt_mutations`), then
  straight to the sweep. Implemented by ``_optimize_stage_simple``.
* **prism** — our own implementation of PromptWizard's published
  technique (mutate, score, critique, refine, iterate), built entirely on
  this engine's own universal ``llm/client.py`` rather than depending on
  their package (see ``DEV_TRACKER.md`` for the full "why Prism" and
  "why not DSPy/genetic search" rationale). Implemented by
  ``_optimize_stage_prism``: generate variants -> cheap-score (no judge)
  -> critique/refine the weakest, bounded by ``max_refine_rounds`` with
  plateau early-stopping -> full sweep -> optional few-shot selection.

Both strategies share everything downstream of "which prompt variants do
we try" — :func:`run_sweep_for_stage` (model-card transform, template
render, param/format sweep, scoring, budget accounting, selection) is one
implementation neither strategy duplicates or can silently drift from.

Per stage, "simple" runs:

1. **Prompt mutation** (:mod:`reprompt_core.optimizer.mutator`) — propose a
   few rewritten prompt variants; degrades to the original prompt alone if
   mutation fails (never aborts the stage over this).
2. **Model-card transform** (:func:`reprompt_core.llm.model_card.apply_model_card_transform`)
   — per-model-family rewrite (XML tags for Claude, etc), applied to every
   prompt candidate.
3. **Template render** (:func:`_render_template`, new — see below) against
   one representative benchmark example for the stage.
4. **Param/format sweep** (:func:`reprompt_core.sweep.generate_param_format_grid`)
   — a bounded sample of the grid is tried per prompt candidate (the full
   cross product of prompt variants × full grid is not run — see
   ``max_sweep_candidates_per_prompt``, kept small deliberately so a
   migration's real spend stays bounded without relying solely on the
   budget hard-stop).
5. **Score** (:mod:`reprompt_core.scoring`, gated judge calls via
   :mod:`reprompt_core.judge`) and **select** (:func:`reprompt_core.selection.select_best_candidate`)
   the winner.

One representative example per stage, not multi-example holdout validation
--------------------------------------------------------------------------
Per-attempt scoring here compares against exactly one benchmark example per
stage (the first one supplied). Multi-example / holdout validation across
the whole pipeline is explicitly a *later* milestone's job — the project's
own build plan describes M4 as "3-pass migration: teacher-forced →
end-to-end → holdout" — so this is the intended M3 scope, not a shortcut.

Template rendering — a genuinely new capability
------------------------------------------------
Nothing in this codebase has ever rendered a ``{{variable}}`` prompt
template before now — every previously-stored ``StageRecord.rendered_prompt``
was already rendered by the *source* system at capture time (see
``trace.py``'s ``Stage.prompt_template`` docstring). Testing a *new*
(possibly mutated) template against a real input needs an actual render
step, so :func:`_render_template` implements one: flat, top-level
``{{key}}`` substitution against the example's ``input`` dict only — no
nesting, loops, or conditionals. An unresolved placeholder is left as-is
rather than raising, since a mutation variant is free-form model output and
imperfect placeholder preservation is a scoring signal (a worse candidate),
not a hard error.

``packages/core`` stays headless
----------------------------------
No DB, no FastAPI import here (per the working rules for ``packages/core``).
Progress and persistence are the caller's job via the optional
``on_attempt`` callback — ``apps/api/src/reprompt_api/optimizer_runner.py``
supplies one that writes ``Candidate`` rows and updates ``Migration``
progress fields, mirroring the existing ``rubric_generator.py`` (core,
pure) / ``rubrics.py`` (api, persists) split already in this codebase. One
stage's failure is caught and recorded, never allowed to abort the whole
run (``reprompt-master-build-prompt.md``'s own M3 constraint).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from typing import Any, Literal, NamedTuple, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from reprompt_core.budget import BudgetTracker
from reprompt_core.deterministic import DeterministicCheck, evaluate_deterministic_checks, parse_deterministic_checks
from reprompt_core.embedding import embedding_similarity
from reprompt_core.judge import JudgeResponseError, JudgeResult, judge_pairwise, judge_single_pass
from reprompt_core.llm.client import LLMResponse
from reprompt_core.llm.model_card import apply_model_card_transform
from reprompt_core.optimizer.mutator import (
    MutationExample,
    PromptMutationError,
    critique_and_refine,
    generate_prompt_mutations,
    select_few_shot_examples,
)
from reprompt_core.scoring import CompositeScore, compute_composite_score, score_candidate, should_run_judge
from reprompt_core.selection import ScoredSweepCandidate, select_best_candidate
from reprompt_core.sweep import SweepCandidate, generate_param_format_grid

__all__ = [
    "StageOptimizationInput",
    "StageAttempt",
    "StagePhaseEvent",
    "StageResult",
    "OptimizationResult",
    "run_optimizer",
    "run_sweep_for_stage",
    "DEFAULT_NUM_PROMPT_VARIANTS",
    "DEFAULT_MAX_SWEEP_CANDIDATES_PER_PROMPT",
    "DEFAULT_MAX_REFINE_ROUNDS",
    "PLATEAU_EPSILON",
]

logger = logging.getLogger(__name__)

DEFAULT_NUM_PROMPT_VARIANTS = 3
DEFAULT_MAX_SWEEP_CANDIDATES_PER_PROMPT = 6
"""Caps how many of `generate_param_format_grid`'s (up to 24, by default)
points are actually attempted per prompt candidate. Real spend per stage
is roughly `(num_prompt_variants + 1) * max_sweep_candidates_per_prompt`
calls (plus the mutation call itself) — kept small by default so a
migration's cost stays predictable; BudgetTracker.is_exhausted remains the
authoritative hard stop regardless of this default."""

DEFAULT_MAX_REFINE_ROUNDS = 3
"""Prism-only. Bounds how many critique-then-refine rounds run before the
final full sweep. See ``_optimize_stage_prism`` and ``DEV_TRACKER.md``'s
"Loop & harness engineering discipline" section. Raised from 1 to 3 as part
of the Phase 1 quality fixes (see ``DEV_TRACKER.md``'s dated Phase 1
section) — at 1, the round loop below could only ever execute once, which
made the plateau-detection logic (``candidate_baseline``/``PLATEAU_EPSILON``)
dead code: there was never a second round to compare a candidate's score
against. The plateau check plus ``budget.is_exhausted`` already bound the
cost of unhelpful further rounds, so this is safe to raise without a new
cost-control mechanism."""

PLATEAU_EPSILON = 0.02
"""Prism-only. If a round's cheap-score improvement over the previous
round is below this, stop refining that candidate early even if
``max_refine_rounds`` would allow another round — see ``DEV_TRACKER.md``'s
early-stopping-on-plateau design note (same 0-1 scale as every other score
in this codebase)."""

NEAR_DUPLICATE_SIMILARITY_THRESHOLD = 0.97
"""Prism and simple both. A new mutation/refinement variant whose embedding
similarity (:func:`reprompt_core.embedding.embedding_similarity` — local,
free, no API key) to an already-kept candidate exceeds this is dropped as a
near-duplicate before it can consume a full sweep slot — see
``_is_near_duplicate`` and ``DEV_TRACKER.md``'s Phase 1 quality-fixes note.
0.97 is deliberately high: this must only catch genuinely near-identical
rewrites (differing by a sentence or two), not merely similar-topic
variants — mutation is supposed to produce real diversity (see
``mutator.py``'s system prompt), and this check exists to catch wasted
sweep slots, not to second-guess the mutator's own diversity."""

_MAX_MUTATION_EXAMPLES = 5
"""How many benchmark examples are shown to the mutator model for context
— capped for the same reason `rubric_generator.DEFAULT_MAX_SAMPLES` is."""

_CHEAP_SCORE_TEMPERATURE = 0.2
"""Prism-only. Fixed param point used for the cheap-score ranking pass
(step 2 of the per-stage algorithm) — deliberately not the full sweep grid,
which only runs once on the final candidate set (step 5)."""


# ---------------------------------------------------------------------------
# Public data shapes
# ---------------------------------------------------------------------------


class StageOptimizationInput(BaseModel):
    """Everything :func:`run_optimizer` needs for one stage, already
    fetched by the caller (this module makes no DB queries of its own —
    packages/core convention, same as ``rubric_generator.py``)."""

    model_config = ConfigDict(extra="forbid")

    stage_id: int = Field(description="Opaque identifier passed through to StageAttempt/StageResult untouched.")
    stage_name: str
    original_prompt_template: str
    target_model: str = Field(description="LiteLLM model string this stage is being migrated to.")
    rubric: dict[str, Any] = Field(
        default_factory=dict,
        description='{"deterministic_checks": [...], "judge_criteria": [...]} — same shape as Rubric rows.',
    )
    examples: list[MutationExample | dict[str, Any]] = Field(
        min_length=1,
        description="Real benchmark input/output pairs for this stage. The first is used as the "
        "representative example this stage's attempts are scored against — see module docstring.",
    )


class StageAttempt(BaseModel):
    """One executed, scored (prompt, param) combination — what ``on_attempt``
    receives and what a caller persists as a ``Candidate`` row."""

    model_config = ConfigDict(extra="forbid")

    stage_id: int
    prompt_variant: str
    params: dict[str, Any]
    format_mode: str
    scores: dict[str, float | bool | None] = Field(
        description="Deterministic/judge/embedding/final component scores (see run_sweep_for_stage), "
        "plus judge_disagreement/judge_low_confidence (float|bool|None, set only when a real judge "
        "call ran — see judge.JudgeResult.disagreement/low_confidence and DEV_TRACKER.md's Phase 1 "
        "quality-fixes note on why these are now plumbed through instead of computed then discarded).",
    )
    cost_usd: float
    latency_ms: float
    few_shot_examples: list[dict[str, Any]] | None = Field(
        default=None,
        description="Set only when Prism's include_few_shot=True and this attempt is the stage's "
        "winning candidate — the real benchmark examples selected as few-shot context. Never "
        "populated for non-winning attempts or the 'simple' strategy.",
    )


StagePhase = Literal["mutating", "cheap_scoring", "critiquing", "refining", "sweeping", "scoring"]
"""One stage's internal phase, in the order a run actually moves through
them (see ``StagePhaseEvent`` and each strategy function's own comments):
``"simple"`` only ever fires ``mutating`` -> ``sweeping`` -> ``scoring``
(all three shared with "prism" via ``run_sweep_for_stage``, which is the
function that fires ``sweeping``/``scoring`` for *both* strategies so they
can never drift). ``"prism"`` additionally cycles ``cheap_scoring`` ->
``critiquing`` -> ``refining`` once per critique/refine round (bounded by
``max_refine_rounds``, see that constant) before its own ``sweeping``/
``scoring`` pass."""


class StagePhaseEvent(NamedTuple):
    """Fired via the optional ``on_phase`` callback at each phase
    transition within a stage — finer-grained than ``on_attempt`` (which
    only fires once per finished, scored sweep attempt and says nothing
    about what's happening during mutation or a critique/refine round).
    Plain ``NamedTuple``, no DB/FastAPI imports — same headless-``packages/
    core`` convention as every other public shape in this module; a caller
    (``apps/api``'s ``optimizer_runner.py``) turns this into UI-visible
    progress, this module has no opinion on how it's displayed.

    ``detail``, added for the "live reasoning feed" phase (see
    ``DEV_TRACKER.md``'s Phase B note): an optional text payload for
    phases where real LLM-generated reasoning is available at the moment
    the event fires. Currently only ``"refining"`` (Prism) populates it —
    with the critique text from :func:`~reprompt_core.optimizer.mutator.critique_and_refine`
    (falling back to a short judge-reasoning summary if the critique text
    itself came back empty) — since that's the only phase transition where
    real free-text reasoning actually exists at fire time. Every other
    phase/strategy leaves it ``None``; existing callers that only read
    ``.stage_id``/``.phase`` are unaffected.
    """

    stage_id: int
    phase: StagePhase
    detail: str | None = None


class StageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: int
    best: StageAttempt | None = Field(description="None if no attempt succeeded for this stage.")
    attempts_tried: int
    met_threshold: bool
    selection_reason: str
    error: str | None = Field(default=None, description="Set if this stage failed unexpectedly (caught, not propagated).")


class OptimizationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_results: list[StageResult]
    total_cost_usd: float
    stopped_early: bool
    stop_reason: str | None = None


# ---------------------------------------------------------------------------
# Template rendering / format-mode wrapping — see module docstring
# ---------------------------------------------------------------------------

_TEMPLATE_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _render_template(template: str, input_data: dict[str, Any] | str) -> str:
    """Flat ``{{key}}`` substitution against ``input_data``. See module
    docstring's "Template rendering" section for why this exists and its
    deliberate scope (no nesting/loops, unresolved keys left as-is)."""
    if not isinstance(input_data, dict):
        return template

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in input_data:
            value = input_data[key]
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return match.group(0)

    return _TEMPLATE_VAR.sub(_sub, template)


def _apply_format_mode(prompt: str, format_mode: str) -> str:
    """Turn a sweep grid point's ``format_mode`` into an actual prompt
    effect. ``reprompt_core.sweep`` deliberately only *generates* this
    dimension (see that module's docstring: "executing a candidate... is
    the M3 optimizer loop's job") — nothing else in the codebase does this
    yet, so this is a new, intentionally minimal implementation: an
    appended instruction, not a heavier per-format wrapping/parsing
    scheme, consistent with ``llm/model_card.py``'s rules also being
    simple textual rewrites."""
    if format_mode == "xml":
        return f"{prompt}\n\nRespond using well-formed XML tags for the output structure."
    if format_mode == "markdown":
        return f"{prompt}\n\nRespond using Markdown formatting (headers/lists) for the output structure."
    if format_mode == "json":
        return f"{prompt}\n\nRespond with valid JSON only."
    return prompt  # "plain" - no change


_T = TypeVar("_T")


def _sample_evenly(items: Sequence[_T], max_count: int) -> list[_T]:
    """Evenly-spaced subset of ``items``, preserving order. Returns all of
    ``items`` unchanged if there are already fewer than ``max_count``."""
    if max_count <= 0 or not items:
        return []
    if len(items) <= max_count:
        return list(items)
    step = len(items) / max_count
    return [items[int(i * step)] for i in range(max_count)]


def _example_dict(example: MutationExample | dict[str, Any]) -> dict[str, Any]:
    if isinstance(example, MutationExample):
        return {"input": example.input, "output": example.output}
    return example


def _judge_reasoning_summary(judge_result: JudgeResult | None) -> str | None:
    """Short human-readable summary of a :class:`~reprompt_core.judge.JudgeResult`
    for a ``StagePhaseEvent.detail`` payload — the ``"refining"`` phase's
    fallback when the critique text itself came back empty (see that
    phase's own comment in ``_optimize_stage_prism``). ``None`` in, ``None``
    out; never raises."""
    if judge_result is None or not judge_result.criteria:
        return None
    lead = judge_result.criteria[0]
    return f"AI judge ({judge_result.overall_score:.2f}) — {lead.name}: {lead.reasoning}"


def _is_near_duplicate(candidate: str, existing: Sequence[str]) -> bool:
    """True if ``candidate``'s embedding similarity to any prompt text in
    ``existing`` exceeds :data:`NEAR_DUPLICATE_SIMILARITY_THRESHOLD`.

    Dedup before this check was exact-string-match only (``if variant not in
    prompt_candidates``) — two near-identical mutation/refinement variants
    (differing by a sentence) would each still consume a full sweep slot.
    This is a small, local, no-cost check (bge-m3 runs locally, no API key)
    run before a new variant is added to the candidate set. Never raises —
    an empty candidate/existing string has no well-defined embedding
    (:func:`~reprompt_core.embedding.embedding_similarity` raises
    ``ValueError`` for that), which is treated as "not a duplicate" here
    rather than propagated, since an empty variant is already a degenerate
    case the downstream sweep will simply score poorly on its own.
    """
    for other in existing:
        try:
            similarity = embedding_similarity(other, candidate)
        except ValueError:
            continue
        if similarity > NEAR_DUPLICATE_SIMILARITY_THRESHOLD:
            return True
    return False


# ---------------------------------------------------------------------------
# Shared sweep/score/select — reused by both the in-house and the
# PromptWizard backend (reprompt_core.optimizer.promptwizard). Only *how
# prompt_candidates gets generated* differs between backends; everything
# from "apply the model-card transform" onward is one shared implementation
# so the two backends can never silently drift in scoring/selection
# behavior.
# ---------------------------------------------------------------------------


def run_sweep_for_stage(
    stage_input: StageOptimizationInput,
    prompt_candidates: Sequence[str],
    *,
    call: Callable[..., LLMResponse],
    budget: BudgetTracker,
    judge_model: str,
    parity_threshold: float,
    max_sweep_candidates_per_prompt: int,
    on_attempt: Callable[[StageAttempt], None] | None,
    on_phase: Callable[[StagePhaseEvent], None] | None = None,
) -> StageResult:
    """Run the param/format sweep, scoring, and selection for one stage
    against an already-decided list of candidate prompt texts.

    This is the backend-agnostic half of stage optimization — everything
    downstream of "which prompt variants do we try" (model-card transform,
    template render, param/format sweep, scoring, budget accounting,
    selection). ``prompt_candidates[0]`` is treated as the "original"
    prompt for attempt-labeling purposes (``params["source"]`` on the
    resulting :class:`StageAttempt` is ``"original"`` for it, ``"mutation"``
    for the rest) — callers should always include the stage's real
    original prompt template as the first entry, even if a mutation step
    failed and it ends up being the *only* entry.

    ``on_phase``, if given, fires ``"sweeping"`` once on entry (this is the
    shared function both strategies call for their param/format grid pass)
    and ``"scoring"`` once the grid is done, right before selection — see
    :class:`StagePhaseEvent`.
    """
    if on_phase is not None:
        on_phase(StagePhaseEvent(stage_id=stage_input.stage_id, phase="sweeping"))

    example = _example_dict(stage_input.examples[0])
    example_input = example.get("input", {})
    benchmark_output = example["output"]

    original_prompt = prompt_candidates[0] if prompt_candidates else stage_input.original_prompt_template

    deterministic_checks: Sequence[DeterministicCheck] = parse_deterministic_checks(
        stage_input.rubric.get("deterministic_checks") or []
    )
    judge_criteria = stage_input.rubric.get("judge_criteria") or []

    stage_attempts: list[tuple[ScoredSweepCandidate, StageAttempt]] = []
    attempts_tried = 0

    for prompt_text in prompt_candidates:
        if budget.is_exhausted:
            break

        transformed_prompt = apply_model_card_transform(prompt_text, stage_input.target_model)
        rendered_base = _render_template(transformed_prompt, example_input)

        grid = generate_param_format_grid(stage_input.target_model)
        valid_points = [c for c in grid if c.is_valid]
        sampled_points = _sample_evenly(valid_points, max_sweep_candidates_per_prompt)

        for sweep_candidate in sampled_points:
            if budget.is_exhausted:
                break

            final_prompt = _apply_format_mode(rendered_base, sweep_candidate.format_mode)

            try:
                response = call(
                    stage_input.target_model,
                    [{"role": "user", "content": final_prompt}],
                    temperature=sweep_candidate.temperature,
                    response_format={"type": "json_object"} if sweep_candidate.structured_output_mode else None,
                )
            except Exception as exc:  # noqa: BLE001 - one attempt's transport failure must not abort the stage
                logger.warning(
                    "Attempt failed for stage %s candidate %s: %s", stage_input.stage_id, sweep_candidate.id, exc,
                )
                continue

            attempts_tried += 1
            candidate_output = response.content
            completion_cost = response.cost_usd or 0.0

            deterministic_result = evaluate_deterministic_checks(
                candidate_output, deterministic_checks, input=example_input
            )
            should_run, _reason = should_run_judge(deterministic_result)

            judge_score: float | None = None
            judge_cost = 0.0
            judge_latency = 0.0
            judge_disagreement: float | None = None
            judge_low_confidence: bool | None = None
            if should_run and judge_criteria:
                try:
                    judge_result = judge_pairwise(
                        benchmark_output, candidate_output, judge_criteria,
                        model=judge_model, input=example_input,
                    )
                    judge_score = judge_result.overall_score
                    judge_cost = judge_result.cost_usd or 0.0
                    judge_latency = judge_result.latency_ms
                    judge_disagreement = judge_result.disagreement
                    judge_low_confidence = judge_result.low_confidence
                except Exception as exc:  # noqa: BLE001 - a failed judge call degrades the score, doesn't abort
                    logger.warning(
                        "Judge call failed for stage %s candidate %s: %s",
                        stage_input.stage_id, sweep_candidate.id, exc,
                    )

            composite: CompositeScore = score_candidate(
                benchmark_output=benchmark_output,
                candidate_output=candidate_output,
                deterministic_checks=deterministic_checks,
                input=example_input,
                judge_score=judge_score,
            )

            total_cost = completion_cost + judge_cost
            total_latency = response.latency_ms + judge_latency
            budget.record_spend(total_cost, candidate_id=sweep_candidate.id)

            scored_candidate = ScoredSweepCandidate(candidate=sweep_candidate, score=composite)
            attempt = StageAttempt(
                stage_id=stage_input.stage_id,
                prompt_variant=prompt_text,
                params={
                    "temperature": sweep_candidate.temperature,
                    "structured_output_mode": sweep_candidate.structured_output_mode,
                    "source": "original" if prompt_text == original_prompt else "mutation",
                },
                format_mode=sweep_candidate.format_mode,
                scores={
                    "deterministic": composite.deterministic_score,
                    "judge": composite.judge_score,
                    "embedding_sim": composite.embedding_score,
                    "final": composite.final_score,
                    "judge_disagreement": judge_disagreement,
                    "judge_low_confidence": judge_low_confidence,
                },
                cost_usd=total_cost,
                latency_ms=total_latency,
            )
            stage_attempts.append((scored_candidate, attempt))
            if on_attempt is not None:
                on_attempt(attempt)

    if on_phase is not None:
        on_phase(StagePhaseEvent(stage_id=stage_input.stage_id, phase="scoring"))

    if not stage_attempts:
        return StageResult(
            stage_id=stage_input.stage_id,
            best=None,
            attempts_tried=attempts_tried,
            met_threshold=False,
            selection_reason="No candidates were successfully attempted (every call failed, or the "
            "budget was exhausted before any attempt completed).",
        )

    selection = select_best_candidate([sc for sc, _ in stage_attempts], parity_threshold)
    winning_attempt = next(attempt for sc, attempt in stage_attempts if sc is selection.selected)

    return StageResult(
        stage_id=stage_input.stage_id,
        best=winning_attempt,
        attempts_tried=attempts_tried,
        met_threshold=selection.met_threshold,
        selection_reason=selection.reason,
    )


# ---------------------------------------------------------------------------
# "simple" strategy: generates prompt_candidates via one mutator call, then
# delegates to the shared run_sweep_for_stage above.
# ---------------------------------------------------------------------------


def _optimize_stage_simple(
    stage_input: StageOptimizationInput,
    *,
    call: Callable[..., LLMResponse],
    budget: BudgetTracker,
    judge_model: str,
    mutator_model: str | None,
    parity_threshold: float,
    num_prompt_variants: int,
    max_sweep_candidates_per_prompt: int,
    on_attempt: Callable[[StageAttempt], None] | None,
    on_phase: Callable[[StagePhaseEvent], None] | None = None,
) -> StageResult:
    if on_phase is not None:
        on_phase(StagePhaseEvent(stage_id=stage_input.stage_id, phase="mutating"))

    prompt_candidates: list[str] = [stage_input.original_prompt_template]
    try:
        mutation = generate_prompt_mutations(
            stage_input.original_prompt_template,
            stage_input.target_model,
            stage_input.rubric,
            [_example_dict(e) for e in stage_input.examples[:_MAX_MUTATION_EXAMPLES]],
            call=call,
            mutator_model=mutator_model,
            num_variants=num_prompt_variants,
        )
        budget.record_spend(mutation.cost_usd or 0.0, candidate_id=f"stage-{stage_input.stage_id}-mutation")
        for variant in mutation.variants:
            if variant not in prompt_candidates and not _is_near_duplicate(variant, prompt_candidates):
                prompt_candidates.append(variant)
    except PromptMutationError as exc:
        logger.warning(
            "Prompt mutation failed for stage %s (%s): %s — continuing with the original prompt only.",
            stage_input.stage_id, stage_input.stage_name, exc,
        )

    return run_sweep_for_stage(
        stage_input,
        prompt_candidates,
        call=call,
        budget=budget,
        judge_model=judge_model,
        parity_threshold=parity_threshold,
        max_sweep_candidates_per_prompt=max_sweep_candidates_per_prompt,
        on_attempt=on_attempt,
        on_phase=on_phase,
    )


# ---------------------------------------------------------------------------
# "prism" strategy: multi-round mutate -> cheap-score -> critique -> refine,
# then delegates to the same shared run_sweep_for_stage for the final full
# sweep/score/select pass. See DEV_TRACKER.md's Phase 1/2 spec for the full
# per-stage algorithm this implements step by step.
# ---------------------------------------------------------------------------


def _cheap_score_candidate(
    prompt_text: str,
    stage_input: StageOptimizationInput,
    example_input: dict[str, Any] | str,
    benchmark_output: str,
    deterministic_checks: Sequence[DeterministicCheck],
    *,
    call: Callable[..., LLMResponse],
    budget: BudgetTracker,
) -> tuple[float, str | None, CompositeScore | None]:
    """One real completion call at a fixed param point (no judge, no sweep
    grid) plus free local scoring — Prism's cheap ranking pass (step 2).

    Returns ``(cheap_score, candidate_output, composite)``. On a transport
    failure, returns ``(0.0, None, None)`` — treated as the worst possible
    rank, never retried (this is a ranking pass, not a real attempt; a
    candidate that can't even be ranked simply won't be picked for
    refinement). Real spend is recorded via ``budget.record_spend()``
    regardless of whether the call's content ends up useful, per this
    module's harness-discipline rule.
    """
    transformed_prompt = apply_model_card_transform(prompt_text, stage_input.target_model)
    rendered = _render_template(transformed_prompt, example_input)

    try:
        response = call(stage_input.target_model, [{"role": "user", "content": rendered}], temperature=_CHEAP_SCORE_TEMPERATURE)
    except Exception as exc:  # noqa: BLE001 - a failed ranking call just means this candidate ranks worst
        logger.warning("Cheap-score call failed for stage %s: %s", stage_input.stage_id, exc)
        return 0.0, None, None

    budget.record_spend(response.cost_usd or 0.0, candidate_id=f"stage-{stage_input.stage_id}-cheapscore")

    candidate_output = response.content
    deterministic_result = evaluate_deterministic_checks(candidate_output, deterministic_checks, input=example_input)
    embedding_score = embedding_similarity(benchmark_output, candidate_output)
    composite = compute_composite_score(deterministic_result, embedding_score, judge_score=None)
    cheap_score = 0.5 * composite.deterministic_score + 0.5 * composite.embedding_score
    return cheap_score, candidate_output, composite


def _optimize_stage_prism(
    stage_input: StageOptimizationInput,
    *,
    call: Callable[..., LLMResponse],
    budget: BudgetTracker,
    judge_model: str,
    mutator_model: str | None,
    parity_threshold: float,
    num_prompt_variants: int,
    max_sweep_candidates_per_prompt: int,
    max_refine_rounds: int,
    include_few_shot: bool,
    on_attempt: Callable[[StageAttempt], None] | None,
    on_phase: Callable[[StagePhaseEvent], None] | None = None,
) -> StageResult:
    example = _example_dict(stage_input.examples[0])
    example_input = example.get("input", {})
    benchmark_output = example["output"]
    deterministic_checks: Sequence[DeterministicCheck] = parse_deterministic_checks(
        stage_input.rubric.get("deterministic_checks") or []
    )
    limited_examples = stage_input.examples[:_MAX_MUTATION_EXAMPLES]

    # Step 1: generate variants (round 1) - same call as "simple"'s only step.
    if on_phase is not None:
        on_phase(StagePhaseEvent(stage_id=stage_input.stage_id, phase="mutating"))

    prompt_candidates: list[str] = [stage_input.original_prompt_template]
    try:
        mutation = generate_prompt_mutations(
            stage_input.original_prompt_template,
            stage_input.target_model,
            stage_input.rubric,
            [_example_dict(e) for e in limited_examples],
            call=call,
            mutator_model=mutator_model,
            num_variants=num_prompt_variants,
        )
        budget.record_spend(mutation.cost_usd or 0.0, candidate_id=f"stage-{stage_input.stage_id}-mutation")
        for variant in mutation.variants:
            if variant not in prompt_candidates and not _is_near_duplicate(variant, prompt_candidates):
                prompt_candidates.append(variant)
    except PromptMutationError as exc:
        logger.warning(
            "Prompt mutation failed for stage %s (%s): %s — continuing with the original prompt only.",
            stage_input.stage_id, stage_input.stage_name, exc,
        )

    judge_criteria = stage_input.rubric.get("judge_criteria") or []

    # Steps 2-4: bounded critique/refine rounds, with plateau early-stopping
    # (see DEV_TRACKER.md's "Loop & harness engineering discipline" #1).
    #
    # candidate_baseline maps a candidate's text -> the cheap_score it needs
    # to beat (by more than PLATEAU_EPSILON) to justify refining it further.
    # Set when a candidate is CREATED by refinement, to its parent's score -
    # not looked up by the candidate's own text from a previous round, since
    # each round's refined candidates have entirely new text that never
    # reappears (a text-keyed "previous score for this exact text" lookup
    # would never match across rounds). Round-1 candidates (original +
    # mutations) have no baseline, so they always get a first refinement
    # attempt regardless of score.
    refined_variants: list[str] = []
    candidate_baseline: dict[str, float] = {}
    candidates_to_rank = list(prompt_candidates)

    for _round_num in range(max_refine_rounds):
        if budget.is_exhausted or not candidates_to_rank:
            break

        if on_phase is not None:
            on_phase(StagePhaseEvent(stage_id=stage_input.stage_id, phase="cheap_scoring"))

        ranked: list[tuple[str, float, CompositeScore, str | None]] = []
        for prompt_text in candidates_to_rank:
            if budget.is_exhausted:
                break
            cheap_score, candidate_output, composite = _cheap_score_candidate(
                prompt_text, stage_input, example_input, benchmark_output, deterministic_checks,
                call=call, budget=budget,
            )
            if composite is not None:
                ranked.append((prompt_text, cheap_score, composite, candidate_output))

        if not ranked:
            break

        ranked.sort(key=lambda entry: entry[1])  # ascending - weakest first
        weakest = ranked[:2]

        if on_phase is not None:
            on_phase(StagePhaseEvent(stage_id=stage_input.stage_id, phase="critiquing"))

        refining_phase_fired = False
        next_round_candidates: list[str] = []
        for prompt_text, cheap_score, composite, candidate_output in weakest:
            baseline = candidate_baseline.get(prompt_text)
            if baseline is not None and (cheap_score - baseline) < PLATEAU_EPSILON:
                continue  # this lineage's last refinement didn't help enough - stop refining it further

            if budget.is_exhausted:
                break

            # Fix (Phase 1 quality fixes): run one real, single-pass judge
            # call on this weakest candidate before critiquing it, so the
            # critique reasons against the judge's actual per-criterion
            # feedback (the largest term in DEFAULT_WEIGHTS - see scoring.py)
            # instead of always being told "the judge was not run", which is
            # what happened when this cheap-score ranking pass's own
            # judge_score=None was the only signal ever threaded into
            # critique_and_refine. Bounded cost: at most one extra judge
            # call per weakest candidate per round (<=2 per round), no swap
            # (judge_single_pass, not judge_pairwise - the swap's bias-
            # cancelling value is saved for the final, persisted sweep score).
            judge_result: JudgeResult | None = None
            if judge_criteria and candidate_output is not None and not budget.is_exhausted:
                try:
                    judge_result = judge_single_pass(
                        benchmark_output, candidate_output, judge_criteria,
                        model=judge_model, input=example_input,
                    )
                    budget.record_spend(
                        judge_result.cost_usd or 0.0, candidate_id=f"stage-{stage_input.stage_id}-critique-judge"
                    )
                except JudgeResponseError as exc:
                    failed_cost = exc.response.cost_usd if exc.response is not None else 0.0
                    budget.record_spend(
                        failed_cost or 0.0, candidate_id=f"stage-{stage_input.stage_id}-critique-judge"
                    )
                    logger.warning(
                        "Judge call failed during Prism critique ranking for stage %s (%s): %s — "
                        "critiquing without judge reasoning.",
                        stage_input.stage_id, stage_input.stage_name, exc,
                    )
                except Exception as exc:  # noqa: BLE001 - transport failure, degrade gracefully, no cost to record
                    logger.warning(
                        "Judge call failed during Prism critique ranking for stage %s (%s): %s — "
                        "critiquing without judge reasoning.",
                        stage_input.stage_id, stage_input.stage_name, exc,
                    )

            try:
                refinement = critique_and_refine(
                    prompt_text, composite, limited_examples, stage_input.rubric, stage_input.target_model,
                    call=call, mutator_model=mutator_model, judge_result=judge_result,
                )
                budget.record_spend(refinement.cost_usd or 0.0, candidate_id=f"stage-{stage_input.stage_id}-refine")

                # Fire "refining" only now (not before the call, as before this
                # phase gained a `detail` payload) — this is the first point in
                # the round where real critique text actually exists to attach.
                # Still fires at most once per round (refining_phase_fired),
                # same as before; if every candidate's critique_and_refine call
                # in this round fails, the round simply has no "refining" event
                # instead of one with detail=None - there is nothing to plumb
                # in that case anyway.
                if on_phase is not None and not refining_phase_fired:
                    detail = refinement.critique or _judge_reasoning_summary(judge_result)
                    on_phase(StagePhaseEvent(stage_id=stage_input.stage_id, phase="refining", detail=detail))
                    refining_phase_fired = True

                refined = refinement.variants[0]
                already_kept = prompt_candidates + refined_variants
                if (
                    refined not in prompt_candidates
                    and refined not in refined_variants
                    and not _is_near_duplicate(refined, already_kept)
                ):
                    refined_variants.append(refined)
                    candidate_baseline[refined] = cheap_score  # must beat the parent's score to refine again
                    next_round_candidates.append(refined)
            except PromptMutationError as exc:
                logger.warning(
                    "Critique/refine failed for stage %s (%s): %s — keeping the un-refined candidate.",
                    stage_input.stage_id, stage_input.stage_name, exc,
                )

        if not next_round_candidates:
            break  # nothing usable came out of this round - no point trying another
        candidates_to_rank = next_round_candidates

    # Step 5: full sweep + score + select - the same shared function "simple" uses.
    result = run_sweep_for_stage(
        stage_input,
        prompt_candidates + refined_variants,
        call=call,
        budget=budget,
        judge_model=judge_model,
        parity_threshold=parity_threshold,
        max_sweep_candidates_per_prompt=max_sweep_candidates_per_prompt,
        on_attempt=on_attempt,
        on_phase=on_phase,
    )

    # Step 6: optional few-shot selection on the winning candidate only.
    if include_few_shot and result.best is not None and not budget.is_exhausted:
        try:
            selected = select_few_shot_examples(
                result.best.prompt_variant, stage_input.examples,
                call=call, model=mutator_model or stage_input.target_model,
            )
            result.best.few_shot_examples = [_example_dict(e) for e in selected]
        except Exception as exc:  # noqa: BLE001 - optional enhancement, never fail the stage over this
            logger.warning(
                "Few-shot selection failed for stage %s (%s): %s — leaving the winning prompt as-is.",
                stage_input.stage_id, stage_input.stage_name, exc,
            )

    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_optimizer(
    stages: Sequence[StageOptimizationInput],
    *,
    call: Callable[..., LLMResponse],
    budget: BudgetTracker,
    judge_model: str,
    strategy: Literal["simple", "prism"] = "simple",
    mutator_model: str | None = None,
    parity_threshold: float = 0.95,
    num_prompt_variants: int = DEFAULT_NUM_PROMPT_VARIANTS,
    max_sweep_candidates_per_prompt: int = DEFAULT_MAX_SWEEP_CANDIDATES_PER_PROMPT,
    max_refine_rounds: int = DEFAULT_MAX_REFINE_ROUNDS,
    include_few_shot: bool = False,
    on_attempt: Callable[[StageAttempt], None] | None = None,
    on_phase: Callable[[StagePhaseEvent], None] | None = None,
) -> OptimizationResult:
    """Run the M3 optimizer loop across every stage of a migration.

    Parameters
    ----------
    stages:
        Already-fetched per-stage input (see :class:`StageOptimizationInput`)
        — this function makes no DB queries of its own.
    call:
        Injected LLM-calling callable, ``call(model, messages, **kwargs) ->
        LLMResponse`` — pass :func:`reprompt_core.llm.client.complete`
        directly, or a closure wrapping
        ``complete_with_workspace_credentials`` (apps/api). Used for every
        real model call this loop makes: mutation, sweep attempts, and
        (via :func:`reprompt_core.judge.judge_pairwise`, which calls
        :func:`reprompt_core.llm.client.complete` directly) judge calls.
    budget:
        Caller-owned :class:`~reprompt_core.budget.BudgetTracker` — real
        spend (mutation + every attempt + every judge call) is recorded
        against it as the run proceeds. ``budget.is_exhausted`` is checked
        before starting each new stage and each new attempt within a
        stage; once tripped, no further attempts are made and the run
        finishes with whatever stages already have a result.
    judge_model:
        LiteLLM model string for the judge — a required BYOK choice, no
        default (same reasoning as ``judge.judge_pairwise``'s own
        ``model`` parameter).
    strategy:
        ``"simple"`` (default) — one mutation call, then the sweep.
        ``"prism"`` — bounded multi-round mutate/critique/refine before
        the sweep. See ``DEV_TRACKER.md`` for the full design rationale
        (why Prism exists, why not DSPy/genetic search).
    max_refine_rounds, include_few_shot:
        Prism-only, ignored for ``strategy="simple"``. See
        :data:`DEFAULT_MAX_REFINE_ROUNDS` and ``_optimize_stage_prism``.
    on_attempt:
        Optional callback invoked once per successfully-scored attempt,
        in the order attempts complete — the caller's hook for progress
        reporting and persistence (e.g. writing a ``Candidate`` row). Not
        called for attempts that failed transport-side (never scored).
    on_phase:
        Optional callback invoked at each phase transition *within* a
        stage — coarser than a per-attempt signal, but fires during
        mutation and (for "prism") each critique/refine round, which
        ``on_attempt`` alone says nothing about. See
        :class:`StagePhaseEvent`. No-op-safe: omitting it changes nothing
        about how either strategy runs.

    Returns
    -------
    :class:`OptimizationResult` — one :class:`StageResult` per input
    stage, in order. A stage's own unexpected failure is caught and
    recorded on its result (``error`` set, ``best=None``) rather than
    aborting the run — later stages still run.
    """
    stage_results: list[StageResult] = []
    stop_reason: str | None = None

    for stage_input in stages:
        if budget.is_exhausted:
            stop_reason = "budget_exhausted"
            break
        try:
            if strategy == "prism":
                result = _optimize_stage_prism(
                    stage_input,
                    call=call,
                    budget=budget,
                    judge_model=judge_model,
                    mutator_model=mutator_model,
                    parity_threshold=parity_threshold,
                    num_prompt_variants=num_prompt_variants,
                    max_sweep_candidates_per_prompt=max_sweep_candidates_per_prompt,
                    max_refine_rounds=max_refine_rounds,
                    include_few_shot=include_few_shot,
                    on_attempt=on_attempt,
                    on_phase=on_phase,
                )
            else:
                result = _optimize_stage_simple(
                    stage_input,
                    call=call,
                    budget=budget,
                    judge_model=judge_model,
                    mutator_model=mutator_model,
                    parity_threshold=parity_threshold,
                    num_prompt_variants=num_prompt_variants,
                    max_sweep_candidates_per_prompt=max_sweep_candidates_per_prompt,
                    on_attempt=on_attempt,
                    on_phase=on_phase,
                )
        except Exception as exc:  # noqa: BLE001 - one stage's failure must never abort the whole run
            logger.error("Stage %s failed unexpectedly: %s", stage_input.stage_id, exc, exc_info=True)
            result = StageResult(
                stage_id=stage_input.stage_id,
                best=None,
                attempts_tried=0,
                met_threshold=False,
                selection_reason="",
                error=str(exc),
            )
        stage_results.append(result)

    stopped_early = stop_reason is not None or budget.is_exhausted
    if stop_reason is None and budget.is_exhausted:
        stop_reason = "budget_exhausted"

    return OptimizationResult(
        stage_results=stage_results,
        total_cost_usd=budget.spent_usd,
        stopped_early=stopped_early,
        stop_reason=stop_reason,
    )
