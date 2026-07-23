"""Wire the M3 optimizer engine into the app's DB and credential layer.

Single public entry point: ``run_optimizer_for_migration(migration_id)``.
Scheduled as a FastAPI ``BackgroundTasks`` task by
``POST /pipelines/{pid}/migrations/{mid}/start`` — runs after the HTTP
response is already sent, so it must open its own session (see below).

Role split (mirrors the existing rubric_generator.py / rubrics.py pattern):
* ``packages/core/optimizer/loop.py`` — pure engine, no DB, no FastAPI
* This file — thin shell that reads real DB rows, builds engine inputs,
  persists ``Candidate`` rows per attempt, and writes final status/cost
  fields onto ``Migration`` when done.

``packages/core`` stays headless: zero FastAPI/DB imports there.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from reprompt_core.budget import BudgetTracker
from reprompt_core.llm.model_select import select_model
from reprompt_core.optimizer.loop import (
    OptimizationResult,
    StageAttempt,
    StageOptimizationInput,
    StagePhaseEvent,
    StageResult,
    run_optimizer,
)
from reprompt_core.optimizer.seam import SeamExample, SeamInput, evaluate_seam

from reprompt_api import models
from reprompt_api.db import SessionLocal
from reprompt_api.llm_context import complete_with_workspace_credentials
from reprompt_api.system_models import system_model_override

# NOTE: reprompt_api.migrations.get_available_models is imported lazily
# inside _run() below, not here at module level - migrations.py itself
# imports run_optimizer_for_migration (this module) at its own module level
# for its BackgroundTasks.add_task() call, so a top-level import here would
# be a circular import (ImportError on a partially-initialized module).
# Deferring the import to call-time, after both modules have finished
# loading, is the standard fix and requires no restructuring of either file.

__all__ = ["run_optimizer_for_migration"]

logger = logging.getLogger(__name__)

MAX_ACTIVITY_LOG_ENTRIES = 100
"""Caps Migration.activity_log length - a long migration (many stages *
target models * critique/refine rounds) fires many on_phase events; without
a cap the JSON column would grow unbounded. Only the most recent entries
matter for the live activity-log UI, so older entries are dropped from the
front as new ones are appended (see on_phase below)."""


def run_optimizer_for_migration(migration_id: int) -> None:
    """Background-task entry point.

    Opens its own ``Session`` — FastAPI ``BackgroundTasks`` run after the
    originating request has returned, which already closed the
    request-scoped ``get_db()`` session.  Reusing a closed session raises;
    a fresh ``SessionLocal()`` is the only correct choice here.
    """
    db = SessionLocal()
    try:
        _run(db, migration_id)
    finally:
        db.close()


def _get_target_models(config: dict) -> list[str]:
    """Backward-compat reader for both config shapes:
    - New: {"models": ["gpt-4o", "claude-haiku"]}
    - Old: {"default": "gpt-4o", "stages": {...}}
    """
    if "models" in config:
        return list(config["models"])
    default = config.get("default", "")
    return [default] if default else []


def _get_stage_overrides(config: dict) -> dict[str, list[str]]:
    """Per-stage advanced override: {"<stage.id>": ["model1", "model2"]}.

    Absent/empty for the common case (no advanced customization) - every
    stage then falls back to the global ``_get_target_models`` list, exactly
    as before this field existed. See ``migrations.py``'s
    ``TargetModelConfig.stage_overrides`` docstring for the full contract.
    """
    return config.get("stage_overrides") or {}


def _run(db: Session, migration_id: int) -> None:  # noqa: C901
    migration = db.get(models.Migration, migration_id)
    if migration is None:
        logger.error("run_optimizer_for_migration: Migration %d not found — aborting", migration_id)
        return

    try:
        pipeline = db.get(models.Pipeline, migration.pipeline_id)
        if pipeline is None:
            raise RuntimeError(f"Pipeline {migration.pipeline_id} not found")

        workspace = db.scalar(select(models.Workspace))
        if workspace is None:
            raise RuntimeError(
                "No workspace found — run scripts/setup.sh and log in before starting a migration"
            )

        strategy = os.environ.get("OPTIMIZER_STRATEGY", "simple")
        target_models = _get_target_models(migration.target_model_config)

        if not target_models:
            raise RuntimeError("Migration has no target models configured")

        # Judge/mutator are Reprompt's OWN harness infrastructure (scoring
        # candidate outputs / mutating-critiquing-refining candidate
        # prompts) - deliberately decoupled from `target_models` above
        # (the user's own choice of model(s) being tested), so a target
        # model never silently grades or refines its own output. Priority
        # order: (1) an explicit override in this migration's own
        # target_model_config always wins outright; (2) an operator-set
        # REPROMPT_JUDGE_MODEL/REPROMPT_MUTATOR_MODEL env var, if set, pins
        # every migration on this deployment to that one model (see
        # reprompt_api.system_models); (3) otherwise auto-select
        # independently from the workspace's own available models (never
        # from target_models) via the same select_model() pattern already
        # used for rubric generation - see reprompt_api.migrations.
        # get_available_models and reprompt_core.llm.model_select.
        # select_model. See DEV_TRACKER.md's "Fix judge/mutator
        # self-grading bias" and "System model config" entries for the
        # full rationale.
        from reprompt_api.migrations import get_available_models  # local import - see note above imports

        available_models = [option.model for option in get_available_models(db, workspace)]
        judge_model = (
            migration.target_model_config.get("judge_model")
            or system_model_override("judge")
            or select_model("judge", available_models, target_models=target_models)
        )
        mutator_model = (
            migration.target_model_config.get("mutator_model")
            or system_model_override("mutator")
            or select_model("mutator", available_models, target_models=target_models)
        )

        db_stages = db.scalars(
            select(models.Stage)
            .where(models.Stage.pipeline_id == pipeline.id)
            .order_by(models.Stage.id)
        ).all()

        # Per-stage advanced override (DEV_TRACKER.md's "Per-stage target
        # model override"): a stage keyed here tries only its own model list
        # instead of the global `target_models` list. Absent/empty for the
        # common case - every stage then behaves exactly as before this
        # field existed.
        stage_overrides = _get_stage_overrides(migration.target_model_config)
        override_stages = [s for s in db_stages if str(s.id) in stage_overrides]
        default_stages = [s for s in db_stages if str(s.id) not in stage_overrides]

        # Total units of work: default stages run once per global target
        # model, override stages run once per their own override model.
        total_work = len(default_stages) * len(target_models) + sum(
            len(stage_overrides[str(s.id)]) for s in override_stages
        )
        stage_id_to_name: dict[int, str] = {s.id: s.name for s in db_stages}

        # `current_target_model` is written right before every run_optimizer
        # call below (both the global-model loop and the per-stage-override
        # loop) so on_attempt always records the model that actually
        # produced the attempt, regardless of which loop is running.
        _state: dict = {"last_stage_id": None, "work_done": 0, "current_target_model": None}

        def on_attempt(attempt: StageAttempt) -> None:
            db.add(
                models.Candidate(
                    migration_id=migration.id,
                    stage_id=attempt.stage_id,
                    target_model=attempt.target_model,
                    prompt_variant=attempt.prompt_variant,
                    params=attempt.params,
                    format=attempt.format_mode,
                    scores=attempt.scores,
                    cost=attempt.cost_usd,
                    latency=attempt.latency_ms,
                )
            )
            if _state["last_stage_id"] != attempt.stage_id:
                _state["last_stage_id"] = attempt.stage_id
                _state["work_done"] += 1
                migration.progress_stage_name = stage_id_to_name.get(attempt.stage_id, "")
                migration.progress_current = _state["work_done"]
                migration.progress_total = total_work
            db.commit()

        def on_phase(event: StagePhaseEvent) -> None:
            # Finer-grained than on_attempt - fires during mutation and each
            # Prism critique/refine round, not just once per finished attempt.
            # progress_stage_name is set independently by on_attempt above;
            # this only tracks the sub-step *within* whatever stage is
            # currently running. Committed at the same cadence as
            # progress_stage_name (every write) so a poller sees it live.
            migration.progress_substep = event.phase

            # Phase B: also append to the running activity log - real LLM
            # reasoning (event.detail, when the phase carries it - see
            # StagePhaseEvent's docstring in packages/core) previously had
            # nowhere to land once on_phase returned. Reassigning the whole
            # list (not .append()) so SQLAlchemy's change-tracking on a JSON
            # column actually sees the mutation - in-place mutation of a
            # JSON-mapped list/dict is a well-known SQLAlchemy footgun that
            # silently no-ops on commit.
            log = list(migration.activity_log or [])
            log.append(
                {
                    "stage_id": event.stage_id,
                    "phase": event.phase,
                    "detail": event.detail,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            migration.activity_log = log[-MAX_ACTIVITY_LOG_ENTRIES:]

            db.commit()

        budget = BudgetTracker(budget_usd=migration.budget)
        total_cost = 0.0
        any_stopped_early = False
        final_stop_reason: str | None = None

        # Skip entirely (not just per-model) when every stage has its own
        # override - avoids both a wasted no-op iteration per target model
        # and a misleading "no benchmark records" warning for stages that
        # were never meant to run against the global list at all.
        if default_stages:
            for target_model in target_models:
                if budget.is_exhausted:
                    any_stopped_early = True
                    final_stop_reason = "budget_exhausted"
                    break

                stages = _build_stage_inputs(db, pipeline.id, default_stages, target_model)
                if not stages:
                    logger.warning(
                        "No benchmark records for pipeline %d — skipping model %s",
                        pipeline.id,
                        target_model,
                    )
                    continue

                _state["current_target_model"] = target_model
                result: OptimizationResult = run_optimizer(
                    stages,
                    call=lambda model, messages, **kw: complete_with_workspace_credentials(
                        db, workspace, model, messages, **kw
                    ),
                    budget=budget,
                    judge_model=judge_model,
                    mutator_model=mutator_model,
                    strategy=strategy,
                    parity_threshold=migration.parity_threshold,
                    on_attempt=on_attempt,
                    on_phase=on_phase,
                )
                _persist_holdout_scores(db, migration.id, result.stage_results, target_model)

                total_cost += result.total_cost_usd
                if result.stopped_early:
                    any_stopped_early = True
                    final_stop_reason = result.stop_reason

        # Per-stage overrides: each such stage tries only its own model
        # list, one run_optimizer call per (stage, override model) pair -
        # isolated per stage since each stage in this set has a distinct
        # candidate list, unlike the shared-list batching above. No-op when
        # stage_overrides is empty (the common case), so the default path's
        # behavior/output is unchanged from before this loop existed.
        for stage in override_stages:
            if budget.is_exhausted:
                any_stopped_early = True
                final_stop_reason = "budget_exhausted"
                break

            for override_model in stage_overrides[str(stage.id)]:
                if budget.is_exhausted:
                    any_stopped_early = True
                    final_stop_reason = "budget_exhausted"
                    break

                stage_inputs = _build_stage_inputs(db, pipeline.id, [stage], override_model)
                if not stage_inputs:
                    logger.warning(
                        "No benchmark records for pipeline %d, stage %d — skipping override model %s",
                        pipeline.id,
                        stage.id,
                        override_model,
                    )
                    continue

                _state["current_target_model"] = override_model
                result = run_optimizer(
                    stage_inputs,
                    call=lambda model, messages, **kw: complete_with_workspace_credentials(
                        db, workspace, model, messages, **kw
                    ),
                    budget=budget,
                    judge_model=judge_model,
                    mutator_model=mutator_model,
                    strategy=strategy,
                    parity_threshold=migration.parity_threshold,
                    on_attempt=on_attempt,
                    on_phase=on_phase,
                )
                _persist_holdout_scores(db, migration.id, result.stage_results, override_model)

                total_cost += result.total_cost_usd
                if result.stopped_early:
                    any_stopped_early = True
                    final_stop_reason = result.stop_reason

        # Phase 4 seam regression — runs after all stages have been optimized.
        if not budget.is_exhausted:
            _run_seam_regression(
                db, pipeline.id, migration.id, budget, complete_with_workspace_credentials, workspace,
                parity_threshold=migration.parity_threshold,
            )

        migration.status = "completed" if not any_stopped_early else "stopped_early"
        migration.total_cost_usd = total_cost
        migration.stopped_early = any_stopped_early
        migration.stop_reason = final_stop_reason
        migration.completed_at = datetime.now(timezone.utc)
        migration.progress_current = total_work
        migration.progress_total = total_work
        db.commit()

    except Exception as exc:  # noqa: BLE001
        logger.error("Migration %d failed unexpectedly: %s", migration_id, exc, exc_info=True)
        try:
            migration.status = "failed"
            migration.stop_reason = str(exc)[:255]
            migration.completed_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:  # noqa: BLE001
            logger.error("Could not write failed status for migration %d — DB may be in a bad state", migration_id)


def _run_seam_regression(
    db: Session,
    pipeline_id: int,
    migration_id: int,
    budget: BudgetTracker,
    complete_fn: object,
    workspace: models.Workspace,
    *,
    parity_threshold: float,
) -> None:
    """Phase 4: run seam checks for every (upstream_winner, downstream_stage) pair.

    For each stage that has a winning Candidate, find its downstream dependents,
    build SeamInput from the benchmark records, call evaluate_seam, and persist
    the result as a SeamCheckResult row. Failures are caught per-pair so one bad
    seam doesn't abort the rest.
    """
    db_stages = db.scalars(
        select(models.Stage)
        .where(models.Stage.pipeline_id == pipeline_id)
        .options(joinedload(models.Stage.dependents))
        .order_by(models.Stage.id)
    ).all()

    # Build stage map and winner map.
    stage_by_id: dict[int, models.Stage] = {s.id: s for s in db_stages}
    # Winner per stage_id: the Candidate with the highest final score.
    winner_by_stage: dict[int, models.Candidate] = {}
    for stage in db_stages:
        candidates = db.scalars(
            select(models.Candidate)
            .where(
                models.Candidate.migration_id == migration_id,
                models.Candidate.stage_id == stage.id,
            )
            .order_by(models.Candidate.id)
        ).all()
        if candidates:
            winner_by_stage[stage.id] = max(candidates, key=lambda c: c.scores.get("final") or 0.0)

    def call(model: str, messages: list, **kw: object) -> object:
        return complete_with_workspace_credentials(db, workspace, model, messages, **kw)  # type: ignore[arg-type]

    for stage in db_stages:
        if stage.id not in winner_by_stage:
            continue  # no winner — nothing to propagate downstream
        winner = winner_by_stage[stage.id]

        for downstream in stage.dependents:
            if budget.is_exhausted:
                return
            try:
                # Gather benchmark records for both stages on the same traces.
                up_records = db.scalars(
                    select(models.StageRecord)
                    .join(models.Trace, models.StageRecord.trace_id == models.Trace.id)
                    .join(models.BenchmarkSet, models.Trace.benchmark_set_id == models.BenchmarkSet.id)
                    .where(
                        models.BenchmarkSet.pipeline_id == pipeline_id,
                        models.StageRecord.stage_id == stage.id,
                    )
                    .options(joinedload(models.StageRecord.trace))
                    .order_by(models.StageRecord.id)
                    .limit(4)
                ).all()

                down_records_by_trace = {
                    r.trace_id: r
                    for r in db.scalars(
                        select(models.StageRecord)
                        .where(
                            models.StageRecord.stage_id == downstream.id,
                            models.StageRecord.trace_id.in_([r.trace_id for r in up_records]),
                        )
                    ).all()
                }

                examples = [
                    SeamExample(
                        upstream_input=ur.input,
                        upstream_baseline_output=ur.output,
                        downstream_input=down_records_by_trace[ur.trace_id].input,
                        downstream_baseline_output=down_records_by_trace[ur.trace_id].output,
                    )
                    for ur in up_records
                    if ur.trace_id in down_records_by_trace
                ]

                if not examples:
                    db.add(models.SeamCheckResult(
                        migration_id=migration_id,
                        upstream_stage_id=stage.id,
                        downstream_stage_id=downstream.id,
                        parity_score=None,
                        passed=False,
                        substitution_applied=False,
                        reason="No shared benchmark traces found for this seam pair.",
                    ))
                    db.commit()
                    continue

                rubric = db.scalar(select(models.Rubric).where(models.Rubric.stage_id == downstream.id))
                seam_in = SeamInput(
                    upstream_stage_id=stage.id,
                    upstream_source_id=stage.source_id,
                    upstream_winning_prompt=winner.prompt_variant,
                    upstream_target_model=winner.target_model,
                    upstream_params=winner.params,
                    downstream_stage_id=downstream.id,
                    downstream_original_prompt=downstream.prompt_template,
                    downstream_original_model=downstream.model,
                    downstream_rubric={
                        "deterministic_checks": rubric.deterministic_checks if rubric else [],
                        "judge_criteria": rubric.judge_criteria if rubric else [],
                    },
                    examples=examples,
                    parity_threshold=parity_threshold,
                )
                result = evaluate_seam(seam_in, call=call, budget=budget)
                db.add(models.SeamCheckResult(
                    migration_id=migration_id,
                    upstream_stage_id=result.upstream_stage_id,
                    downstream_stage_id=result.downstream_stage_id,
                    parity_score=result.parity_score,
                    passed=result.passed,
                    substitution_applied=result.substitution_applied,
                    reason=result.reason,
                ))
                db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Seam check failed for stages %d→%d in migration %d: %s",
                    stage.id, downstream.id, migration_id, exc,
                )


def _persist_holdout_scores(
    db: Session,
    migration_id: int,
    stage_results: list[StageResult],
    target_model: str,
) -> None:
    """Write holdout_score onto the winning Candidate row for each stage.

    Matches the winner by (migration_id, stage_id, target_model, prompt_variant)
    — the same combination the results endpoint uses to identify the winner.
    Called once per run_optimizer invocation (one per target model / override).
    """
    for sr in stage_results:
        if sr.best is None or sr.holdout_score is None:
            continue
        candidate = db.scalar(
            select(models.Candidate)
            .where(
                models.Candidate.migration_id == migration_id,
                models.Candidate.stage_id == sr.stage_id,
                models.Candidate.target_model == target_model,
                models.Candidate.prompt_variant == sr.best.prompt_variant,
            )
            .order_by(models.Candidate.id.desc())
            .limit(1)
        )
        if candidate is not None:
            candidate.holdout_score = sr.holdout_score
    db.commit()


def _build_stage_inputs(
    db: Session,
    pipeline_id: int,
    db_stages: list[models.Stage],
    target_model: str,
) -> list[StageOptimizationInput]:
    """Build optimizer inputs for one target model across all pipeline stages.

    Skips stages with no benchmark records (logs a warning rather than raising).
    """
    result: list[StageOptimizationInput] = []
    for stage in db_stages:
        rubric = db.scalar(select(models.Rubric).where(models.Rubric.stage_id == stage.id))

        records = db.scalars(
            select(models.StageRecord)
            .join(models.Trace, models.StageRecord.trace_id == models.Trace.id)
            .join(models.BenchmarkSet, models.Trace.benchmark_set_id == models.BenchmarkSet.id)
            .where(
                models.BenchmarkSet.pipeline_id == pipeline_id,
                models.StageRecord.stage_id == stage.id,
            )
            .options(joinedload(models.StageRecord.trace))
            .order_by(models.StageRecord.id)
            .limit(8)
        ).all()

        if not records:
            logger.warning(
                "Stage %d (%s) has no benchmark records — skipping",
                stage.id,
                stage.name,
            )
            continue

        # M4 holdout split: prefer explicitly-flagged holdout traces; fall back
        # to keeping the last record as holdout when none are flagged and there
        # are at least 2 records. With only 1 record there is nothing to hold out.
        explicit_holdout = [r for r in records if r.trace.is_holdout]
        train_records = [r for r in records if not r.trace.is_holdout]
        if not explicit_holdout and len(records) >= 2:
            # Automatic split: last record withheld, rest used for training.
            train_records, explicit_holdout = list(records[:-1]), [records[-1]]

        result.append(
            StageOptimizationInput(
                stage_id=stage.id,
                stage_name=stage.name,
                original_prompt_template=stage.prompt_template,
                target_model=target_model,
                rubric={
                    "deterministic_checks": rubric.deterministic_checks if rubric else [],
                    "judge_criteria": rubric.judge_criteria if rubric else [],
                },
                examples=[{"input": r.input, "output": r.output} for r in train_records],
                holdout_examples=[{"input": r.input, "output": r.output} for r in explicit_holdout],
            )
        )

    return result
