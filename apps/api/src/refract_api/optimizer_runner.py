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

from refract_core.budget import BudgetTracker
from refract_core.optimizer.loop import (
    OptimizationResult,
    StageAttempt,
    StageOptimizationInput,
    run_optimizer,
)

from refract_api import models
from refract_api.db import SessionLocal
from refract_api.llm_context import complete_with_workspace_credentials

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


def _run(db: Session, migration_id: int) -> None:  # noqa: C901
    migration = db.get(models.Migration, migration_id)
    if migration is None:
        logger.error("run_optimizer_for_migration: Migration %d not found — aborting", migration_id)
        return

    try:
        pipeline = db.get(models.Pipeline, migration.pipeline_id)
        if pipeline is None:
            raise RuntimeError(f"Pipeline {migration.pipeline_id} not found")

        # Single-workspace MVP: every install has exactly one Workspace (the
        # 1:1 user:workspace cardinality is enforced by UniqueConstraint on
        # Workspace.owner_user_id — see models.py).  Teams/multi-workspace is
        # an explicitly post-MVP item; this unconditional scalar() is correct
        # and honest here rather than silently assuming a workspace_id we
        # don't have on Migration.
        workspace = db.scalar(select(models.Workspace))
        if workspace is None:
            raise RuntimeError(
                "No workspace found — run scripts/setup.sh and log in before starting a migration"
            )

        strategy = os.environ.get("OPTIMIZER_STRATEGY", "simple")
        stages = _build_stage_inputs(db, migration, pipeline.id)

        if not stages:
            raise RuntimeError(
                f"Pipeline {pipeline.id} has no stages with benchmark records — "
                "import traces before starting a migration"
            )

        # Judge model: use an explicit override from target_model_config if
        # present, otherwise default to the migration's own target model.
        # No new config surface needed for Phase 4 — documented fallback.
        judge_model = (
            migration.target_model_config.get("judge_model")
            or migration.target_model_config["default"]
        )

        total_stages = len(stages)
        stage_id_to_name: dict[int, str] = {s.stage_id: s.stage_name for s in stages}

        # Mutable state shared with the on_attempt closure — Python closures
        # rebind names in the enclosing scope via nonlocal, but a dict is
        # cleaner than multiple nonlocal declarations here.
        _state: dict = {"last_stage_id": None, "stages_done": 0}

        def on_attempt(attempt: StageAttempt) -> None:
            db.add(
                models.Candidate(
                    migration_id=migration.id,
                    stage_id=attempt.stage_id,
                    prompt_variant=attempt.prompt_variant,
                    params=attempt.params,
                    format=attempt.format_mode,   # Candidate.format, not format_mode
                    scores=attempt.scores,
                    cost=attempt.cost_usd,        # Candidate.cost, not cost_usd
                    latency=attempt.latency_ms,   # Candidate.latency, not latency_ms
                )
            )

            # Progress: detect stage transitions so the /status endpoint shows
            # which stage is actively being worked on, updated per stage not
            # per attempt (too chatty otherwise — per DEV_TRACKER.md Phase 4).
            if _state["last_stage_id"] is not None and _state["last_stage_id"] != attempt.stage_id:
                _state["stages_done"] += 1

            if _state["last_stage_id"] != attempt.stage_id:
                _state["last_stage_id"] = attempt.stage_id
                migration.progress_stage_name = stage_id_to_name.get(attempt.stage_id, "")
                migration.progress_current = _state["stages_done"]
                migration.progress_total = total_stages

            db.commit()

        result: OptimizationResult = run_optimizer(
            stages,
            call=lambda model, messages, **kw: complete_with_workspace_credentials(
                db, workspace, model, messages, **kw
            ),
            budget=BudgetTracker(budget_usd=migration.budget),
            judge_model=judge_model,
            strategy=strategy,
            parity_threshold=migration.parity_threshold,
            on_attempt=on_attempt,
        )

        migration.status = "completed" if not result.stopped_early else "stopped_early"
        migration.total_cost_usd = result.total_cost_usd
        migration.stopped_early = result.stopped_early
        migration.stop_reason = result.stop_reason
        migration.completed_at = datetime.now(timezone.utc)
        migration.progress_current = total_stages
        migration.progress_total = total_stages
        db.commit()

    except Exception as exc:  # noqa: BLE001 — any unhandled exception must leave the DB legible
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
    migration: models.Migration,
    pipeline_id: int,
) -> list[StageOptimizationInput]:
    """Build the per-stage optimizer inputs from real DB rows.

    Skips any stage that has no benchmark records (logs a warning rather
    than raising — a stage with no data to score against can't contribute
    to a migration, but other stages can still run).

    Field-name note: ``StageAttempt`` uses ``cost_usd``/``latency_ms``/
    ``format_mode``; ``Candidate`` uses ``cost``/``latency``/``format`` —
    the mapping is handled in the ``on_attempt`` closure above, not here.
    """
    stages = db.scalars(
        select(models.Stage)
        .where(models.Stage.pipeline_id == pipeline_id)
        .order_by(models.Stage.id)
    ).all()

    result: list[StageOptimizationInput] = []
    for stage in stages:
        target_model = migration.target_model_config.get("stages", {}).get(
            str(stage.id), migration.target_model_config["default"]
        )

        rubric = db.scalar(select(models.Rubric).where(models.Rubric.stage_id == stage.id))

        # Pipeline -> BenchmarkSet -> Trace -> StageRecord, filtered by
        # stage_id.  Same join pattern rubric_generator.py uses; same 8-row
        # cap (DEFAULT_MAX_SAMPLES convention).
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
                "Stage %d (%s) has no benchmark records — skipping this stage",
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
