"""New migration wizard endpoints (screen 5 / M2).

Per ``reprompt-master-build-prompt.md`` §4 screen 5 and §5's M2/M3 boundary:
this module is only responsible for the wizard that *creates* a Migration
record with its configuration (target model per stage, budget, parity
threshold). It does not run anything — there is no status transition logic
here. Actually optimizing stages against the new target model(s) is M3/M4's
job; ``Migration.status`` is created as ``"pending"`` and stays there.

``target_model_config`` JSON shape
-----------------------------------
Matches the shape already documented as an example in ``models.py``::

    {
        "default": "gpt-4o-mini",
        "stages": {"3": "gemini/gemini-2.0-flash"}
    }

* ``default`` — the bulk-set model string (a LiteLLM model id), applied to
  every stage that has no override.
* ``stages`` — optional per-stage overrides, keyed by the stage's **database
  id** (as a string, since JSON object keys are always strings) mapping to a
  LiteLLM model string. Every key must reference a stage that belongs to
  this pipeline — a stage id from a different pipeline (or one that doesn't
  exist at all) is rejected with a 422 that names the offending id(s), not
  silently accepted or 500'd.

Model picker data source
-------------------------
``GET /pipelines/{pipeline_id}/models`` returns a small curated list of
LiteLLM model strings spanning the major hosted providers plus a couple of
local/open options, enriched with capability facts pulled live from
``reprompt_core.llm.registry.get_model_capabilities`` (itself a thin,
never-raising wrapper over LiteLLM's own model metadata). This is
deliberately not the full model-card registry described for M3 — just
enough for the picker to show cost/context window/JSON-mode support per the
screen 5 spec. Any model LiteLLM doesn't fully recognize still comes back
with a row (degrading to ``None``/``False`` fields), matching
``get_model_capabilities``'s own "never raises for an unrecognized model"
contract — the picker should show fewer facts, not break.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from reprompt_core.llm.registry import get_model_capabilities

from reprompt_api import models
from reprompt_api.db import get_db
from reprompt_api.optimizer_runner import run_optimizer_for_migration

router = APIRouter(prefix="/pipelines", tags=["migrations"])

# A deliberately small, curated cross-section of LiteLLM model strings for
# the picker — not an attempt to enumerate every model LiteLLM knows about.
# Spans the major hosted providers plus a couple of local/open options (no
# API key required), per the task's own examples.
CURATED_MODELS: list[str] = [
    "gpt-4o",
    "gpt-4o-mini",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
    "gemini/gemini-2.0-flash",
    "gemini/gemini-2.0-flash-lite",
    "ollama/llama3.1",
    "ollama/qwen2.5:14b",
]


class ModelOption(BaseModel):
    model: str
    provider: str | None
    input_cost_per_1m: float | None
    output_cost_per_1m: float | None
    max_input_tokens: int | None
    max_output_tokens: int | None
    supports_json_mode: bool
    supports_function_calling: bool
    requires_api_key: bool


class TargetModelConfig(BaseModel):
    """List of target models the optimizer will try per stage, keeping the
    best-scoring result. Replaces the old single-default + per-stage-override
    shape — backward-compat reading of the old shape is handled in
    ``optimizer_runner._get_target_models``."""

    models: list[str] = Field(min_length=1)


class MigrationCreate(BaseModel):
    target_model_config: TargetModelConfig
    budget: float = Field(gt=0, description="Max optimization spend in $ - a hard stop.")
    parity_threshold: float = Field(default=0.95, ge=0, le=1)


class MigrationOut(BaseModel):
    id: int
    pipeline_id: int
    target_model_config: dict
    budget: float
    parity_threshold: float
    status: str
    total_cost_usd: float | None = None
    stopped_early: bool = False
    stop_reason: str | None = None
    progress_stage_name: str | None = None
    progress_current: int | None = None
    progress_total: int | None = None
    # Live sub-step within progress_stage_name - one of
    # reprompt_core.optimizer.loop.StagePhase ("mutating"/"cheap_scoring"/
    # "critiquing"/"refining"/"sweeping"/"scoring"), written by
    # optimizer_runner.py's on_phase closure. Null before a run starts.
    progress_substep: str | None = None
    # Chronological {"stage_id", "phase", "detail", "timestamp"} entries -
    # same polling pattern as progress_substep/stage_states, just a running
    # list instead of a single latest value. Null before a run starts,
    # capped at the last 100 entries by optimizer_runner.py's on_phase
    # closure. See DEV_TRACKER.md's "Phase B" note.
    activity_log: list[dict] | None = None
    completed_at: datetime.datetime | None = None
    # Derived, not stored: {stage_id (as string, matching the DAG canvas's
    # React Flow node ids) -> "idle" | "running" | "done" | "failed"}. See
    # `_compute_stage_states` for the derivation rule — computed fresh on
    # every read from the same progress_* fields optimizer_runner.py already
    # writes sequentially; no new DB columns.
    stage_states: dict[str, str] = Field(default_factory=dict)


def _get_pipeline_or_404(db: Session, pipeline_id: int) -> models.Pipeline:
    pipeline = db.get(models.Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    return pipeline


def _to_option(model: str) -> ModelOption:
    caps = get_model_capabilities(model)
    input_cost_per_1m = (
        caps.input_cost_per_token * 1_000_000 if caps.input_cost_per_token is not None else None
    )
    output_cost_per_1m = (
        caps.output_cost_per_token * 1_000_000 if caps.output_cost_per_token is not None else None
    )
    return ModelOption(
        model=model,
        provider=caps.provider,
        input_cost_per_1m=input_cost_per_1m,
        output_cost_per_1m=output_cost_per_1m,
        max_input_tokens=caps.max_input_tokens,
        max_output_tokens=caps.max_output_tokens,
        supports_json_mode=caps.supports_json_mode,
        supports_function_calling=caps.supports_function_calling,
        requires_api_key=caps.requires_api_key,
    )


def _compute_stage_states(
    db_stages: list[models.Stage], migration: models.Migration
) -> dict[str, str]:
    """Derive a per-stage run state from the Migration's existing sequential
    progress fields — no new DB columns, pure read-time derivation.

    ``db_stages`` must be in the same order optimizer_runner.py iterates them
    in (``Stage`` ordered by ``id`` — see ``optimizer_runner._run``'s
    ``db_stages`` query, reused as-is here rather than inventing a second
    ordering). Keys are the stage's DB id as a string, matching the DAG
    canvas's React Flow node ids (``String(stage.id)`` in
    ``pipeline-detail.tsx``).

    Rule: stages before ``progress_stage_name`` = "done", the stage matching
    it = "running" (or "failed"/"done" once the run is terminal), stages
    after = "idle". ``status == "completed"`` short-circuits to all "done".
    Before anything has run (``progress_stage_name`` is still None), every
    stage is "idle".
    """
    if migration.status == "completed":
        return {str(stage.id): "done" for stage in db_stages}

    if not migration.progress_stage_name:
        return {str(stage.id): "idle" for stage in db_stages}

    current_index = next(
        (i for i, s in enumerate(db_stages) if s.name == migration.progress_stage_name),
        None,
    )

    states: dict[str, str] = {}
    for i, stage in enumerate(db_stages):
        if current_index is None:
            states[str(stage.id)] = "idle"
        elif i < current_index:
            states[str(stage.id)] = "done"
        elif i == current_index:
            if migration.status == "failed":
                states[str(stage.id)] = "failed"
            elif migration.status == "stopped_early":
                # The stage the run stopped on already had at least one
                # attempt recorded before the budget hard-stop fired.
                states[str(stage.id)] = "done"
            else:
                states[str(stage.id)] = "running"
        else:
            states[str(stage.id)] = "idle"
    return states


def _to_out(db: Session, migration: models.Migration) -> MigrationOut:
    db_stages = db.scalars(
        select(models.Stage)
        .where(models.Stage.pipeline_id == migration.pipeline_id)
        .order_by(models.Stage.id)
    ).all()
    return MigrationOut(
        id=migration.id,
        pipeline_id=migration.pipeline_id,
        target_model_config=migration.target_model_config,
        budget=migration.budget,
        parity_threshold=migration.parity_threshold,
        status=migration.status,
        total_cost_usd=migration.total_cost_usd,
        stopped_early=migration.stopped_early,
        stop_reason=migration.stop_reason,
        progress_stage_name=migration.progress_stage_name,
        progress_current=migration.progress_current,
        progress_total=migration.progress_total,
        progress_substep=migration.progress_substep,
        activity_log=migration.activity_log,
        completed_at=migration.completed_at,
        stage_states=_compute_stage_states(list(db_stages), migration),
    )


class StageResultOut(BaseModel):
    """One stage's before/after prompt for the results (diff) view.

    Display-only — no new optimizer/scoring logic. ``winning_prompt``/
    ``winning_model``/``score`` are read off whichever ``Candidate`` row for
    this ``(migration_id, stage_id)`` pair has the highest
    ``scores["final"]`` (the composite score ``packages/core``'s
    ``run_sweep_for_stage`` already writes onto every attempt — see
    ``reprompt_core.optimizer.loop``'s ``StageAttempt.scores`` and
    ``optimizer_runner.py``'s ``on_attempt`` closure that persists it
    verbatim as ``Candidate.scores``). There is no separate "winner" flag
    persisted on ``Candidate`` — recomputing "best by score" at read time
    is cheap (at most a few dozen rows per stage per migration) and keeps
    this endpoint a pure read, no new columns/migrations.
    """

    stage_id: int
    stage_name: str
    original_prompt: str
    winning_prompt: str
    winning_model: str
    score: float


def _get_migration_or_404(db: Session, pipeline_id: int, migration_id: int) -> models.Migration:
    migration = db.scalar(
        select(models.Migration).where(
            models.Migration.id == migration_id,
            models.Migration.pipeline_id == pipeline_id,
        )
    )
    if migration is None:
        raise HTTPException(
            status_code=404,
            detail=f"Migration {migration_id} not found for pipeline {pipeline_id}",
        )
    return migration


@router.get("/{pipeline_id}/models", response_model=list[ModelOption])
def list_model_options(pipeline_id: int, db: Session = Depends(get_db)) -> list[ModelOption]:
    """Model picker data source for the migration wizard's target-model step."""
    _get_pipeline_or_404(db, pipeline_id)
    return [_to_option(model) for model in CURATED_MODELS]


@router.post("/{pipeline_id}/migrations", response_model=MigrationOut, status_code=201)
def create_migration(
    pipeline_id: int, migration_in: MigrationCreate, db: Session = Depends(get_db)
) -> MigrationOut:
    """Create a Migration record from the wizard's final config. Does not
    start anything — see module docstring. Status is always "pending".
    """
    _get_pipeline_or_404(db, pipeline_id)

    migration = models.Migration(
        pipeline_id=pipeline_id,
        target_model_config=migration_in.target_model_config.model_dump(),
        budget=migration_in.budget,
        parity_threshold=migration_in.parity_threshold,
        status="pending",
    )
    db.add(migration)
    db.commit()
    db.refresh(migration)
    return _to_out(db, migration)


@router.get("/{pipeline_id}/migrations", response_model=list[MigrationOut])
def list_migrations(pipeline_id: int, db: Session = Depends(get_db)) -> list[MigrationOut]:
    _get_pipeline_or_404(db, pipeline_id)
    migrations = db.scalars(
        select(models.Migration)
        .where(models.Migration.pipeline_id == pipeline_id)
        .order_by(models.Migration.id)
    ).all()
    return [_to_out(db, migration) for migration in migrations]


@router.post("/{pipeline_id}/migrations/{migration_id}/start", response_model=MigrationOut)
def start_migration(
    pipeline_id: int,
    migration_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> MigrationOut:
    """Gate on approved rubrics, set status to running, then fire the
    optimizer as a background task.

    Status is written to the DB *before* the background task is scheduled
    so a client polling /status immediately after this call always sees
    ``"running"``, never a stale ``"pending"`` from a race with the task
    actually starting.
    """
    _get_pipeline_or_404(db, pipeline_id)
    migration = _get_migration_or_404(db, pipeline_id, migration_id)

    # Rubric approval gate: every stage must have a rubric row with approved=True.
    # Human sign-off on what "a good answer" looks like is a hard requirement
    # before the optimizer is allowed to spend real money searching.
    stages = db.scalars(
        select(models.Stage).where(models.Stage.pipeline_id == pipeline_id)
    ).all()

    unapproved: list[str] = []
    for stage in stages:
        rubric = db.scalar(
            select(models.Rubric).where(models.Rubric.stage_id == stage.id)
        )
        if rubric is None or not rubric.approved:
            unapproved.append(stage.name)

    if unapproved:
        raise HTTPException(
            status_code=422,
            detail=(
                f"All stage rubrics must be approved before starting a migration. "
                f"Unapproved: {', '.join(unapproved)}"
            ),
        )

    migration.status = "running"
    db.commit()
    db.refresh(migration)

    background_tasks.add_task(run_optimizer_for_migration, migration.id)
    return _to_out(db, migration)


@router.get("/{pipeline_id}/migrations/{migration_id}/status", response_model=MigrationOut)
def get_migration_status(
    pipeline_id: int,
    migration_id: int,
    db: Session = Depends(get_db),
) -> MigrationOut:
    """Plain read of the migration's current status and progress fields.

    No computation — just what ``optimizer_runner.py``'s background task
    last wrote.  Clients poll this on an interval (e.g. every 2 s) from
    the migration detail screen.
    """
    _get_pipeline_or_404(db, pipeline_id)
    migration = _get_migration_or_404(db, pipeline_id, migration_id)
    return _to_out(db, migration)


@router.get(
    "/{pipeline_id}/migrations/{migration_id}/results",
    response_model=list[StageResultOut],
)
def get_migration_results(
    pipeline_id: int,
    migration_id: int,
    db: Session = Depends(get_db),
) -> list[StageResultOut]:
    """Before/after prompt per stage — the winning ``Candidate`` (highest
    ``scores["final"]``) against ``Stage.prompt_template``.

    Not gated on ``Migration.status`` being terminal: a stage only appears
    once it has at least one ``Candidate`` row, which naturally means a
    non-terminal (``running``/``pending``) migration returns whichever
    stages have finished at least one attempt so far (often none yet, e.g.
    right after ``start``) rather than erroring or returning a fixed
    fully-populated shape — same "return what's available" contract this
    router's other read endpoints already follow. Once ``status`` reaches a
    terminal state this naturally returns the complete per-stage set.
    """
    _get_pipeline_or_404(db, pipeline_id)
    _get_migration_or_404(db, pipeline_id, migration_id)

    db_stages = db.scalars(
        select(models.Stage)
        .where(models.Stage.pipeline_id == pipeline_id)
        .order_by(models.Stage.id)
    ).all()

    results: list[StageResultOut] = []
    for stage in db_stages:
        candidates = db.scalars(
            select(models.Candidate)
            .where(
                models.Candidate.migration_id == migration_id,
                models.Candidate.stage_id == stage.id,
            )
            .order_by(models.Candidate.id)
        ).all()
        if not candidates:
            continue

        # Ties broken by input-list order (Candidate.id ascending, i.e. the
        # earliest-tried candidate wins) - same tie-break convention as
        # reprompt_core.selection.select_best_candidate (Python's max()
        # returns the first element attaining the maximum).
        best = max(candidates, key=lambda c: c.scores.get("final") or 0.0)
        results.append(
            StageResultOut(
                stage_id=stage.id,
                stage_name=stage.name,
                original_prompt=stage.prompt_template,
                winning_prompt=best.prompt_variant,
                winning_model=best.target_model,
                score=best.scores.get("final") or 0.0,
            )
        )

    return results
