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
from sqlalchemy.orm import Session

from reprompt_core.budget import BudgetTracker
from reprompt_core.optimizer.loop import (
    OptimizationResult,
    StageAttempt,
    StageOptimizationInput,
    run_optimizer,
)

from reprompt_api import models
from reprompt_api.db import SessionLocal
from reprompt_api.llm_context import complete_with_workspace_credentials

__all__ = ["run_optimizer_for_migration"]

logger = logging.getLogger(__name__)


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

        # Use first model as judge for consistent cross-model scoring.
        judge_model = (
            migration.target_model_config.get("judge_model") or target_models[0]
        )

        db_stages = db.scalars(
            select(models.Stage)
            .where(models.Stage.pipeline_id == pipeline.id)
            .order_by(models.Stage.id)
        ).all()

        # Total units of work: each model runs against every stage.
        total_work = len(db_stages) * len(target_models)
        stage_id_to_name: dict[int, str] = {s.id: s.name for s in db_stages}

        _state: dict = {"last_stage_id": None, "work_done": 0}

        def on_attempt(attempt: StageAttempt) -> None:
            db.add(
                models.Candidate(
                    migration_id=migration.id,
                    stage_id=attempt.stage_id,
                    target_model=target_model,
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

        budget = BudgetTracker(budget_usd=migration.budget)
        total_cost = 0.0
        any_stopped_early = False
        final_stop_reason: str | None = None

        for target_model in target_models:
            if budget.is_exhausted:
                any_stopped_early = True
                final_stop_reason = "budget_exhausted"
                break

            stages = _build_stage_inputs(db, pipeline.id, db_stages, target_model)
            if not stages:
                logger.warning(
                    "No benchmark records for pipeline %d — skipping model %s",
                    pipeline.id,
                    target_model,
                )
                continue

            result: OptimizationResult = run_optimizer(
                stages,
                call=lambda model, messages, **kw: complete_with_workspace_credentials(
                    db, workspace, model, messages, **kw
                ),
                budget=budget,
                judge_model=judge_model,
                strategy=strategy,
                parity_threshold=migration.parity_threshold,
                on_attempt=on_attempt,
            )

            total_cost += result.total_cost_usd
            if result.stopped_early:
                any_stopped_early = True
                final_stop_reason = result.stop_reason

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
                examples=[{"input": r.input, "output": r.output} for r in records],
            )
        )

    return result
