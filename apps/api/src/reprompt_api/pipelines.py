"""Pipeline import, listing, DAG, and (M5 BYOK proof-of-concept) test-prompt
endpoints.
"""

from __future__ import annotations

import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from reprompt_core import CycleError, TraceFile, TraceFileError, build_dag, parse_trace_file
from reprompt_core.llm.client import PermanentLLMError, RepromptLLMError, TransientLLMError
from reprompt_core.trace import TokenUsage

from reprompt_api import models
from reprompt_api.auth import get_current_user
from reprompt_api.crypto import EncryptionNotConfigured
from reprompt_api.db import get_db
from reprompt_api.ingest import StageDriftError, persist_trace_file
from reprompt_api.llm_context import ProviderKeyNotConfigured, complete_with_workspace_credentials

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


class ImportResult(BaseModel):
    pipeline_id: int
    name: str
    stage_count: int
    trace_count: int


class RunOut(BaseModel):
    id: int
    name: str
    created_at: datetime.datetime
    trace_count: int


class PipelineSummary(BaseModel):
    id: int
    name: str
    stage_count: int
    models_used: list[str]
    benchmark_query_count: int


class PipelineUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class DagLayer(BaseModel):
    stage_ids: list[int]


class StageInfo(BaseModel):
    id: int
    name: str
    model: str
    avg_tokens_in: float
    avg_tokens_out: float
    avg_latency_ms: float


class DagEdge(BaseModel):
    from_stage_id: int
    to_stage_id: int


class DagResponse(BaseModel):
    pipeline_id: int
    layers: list[DagLayer]
    stages: dict[int, StageInfo]  # stage id -> info, for canvas node rendering
    edges: list[DagEdge]


async def _parse_upload_to_trace_file(file: UploadFile) -> TraceFile:
    """Shared UploadFile -> validated TraceFile path for both /import and
    /{pipeline_id}/import. Raises HTTPException(422) on any validation
    failure — never a raw stack trace or a generic 500.
    """
    raw_bytes = await file.read()
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=422, detail=f"Uploaded file is not valid UTF-8 text: {exc}"
        ) from exc

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422, detail=f"Uploaded file is not valid JSON: {exc}"
        ) from exc

    try:
        return parse_trace_file(data)
    except TraceFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/import", response_model=ImportResult, status_code=201)
async def import_pipeline(
    file: UploadFile, db: Session = Depends(get_db)
) -> ImportResult:
    """Upload a trace-format JSON file, creating a brand-new Pipeline.
    Validates against the canonical schema (packages/core) before
    persisting anything. On any validation failure, returns 422 with a
    field-level error message — never a raw stack trace or a generic 500.
    """
    trace_file = await _parse_upload_to_trace_file(file)

    try:
        pipeline = persist_trace_file(db, trace_file)
    except CycleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ImportResult(
        pipeline_id=pipeline.id,
        name=pipeline.name,
        stage_count=len(trace_file.pipeline.stages),
        trace_count=len(trace_file.traces),
    )


@router.post("/{pipeline_id}/import", response_model=ImportResult, status_code=201)
async def import_run_into_pipeline(
    pipeline_id: int, file: UploadFile, db: Session = Depends(get_db)
) -> ImportResult:
    """Attach a new run (a new BenchmarkSet) to an *existing* pipeline,
    reusing/extending its Stage rows rather than creating a parallel
    Pipeline — see reprompt_api.ingest.persist_trace_file's docstring for
    the exact reuse/drift rule. Same validation path as POST /import.
    """
    pipeline = db.get(models.Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")

    trace_file = await _parse_upload_to_trace_file(file)

    try:
        pipeline = persist_trace_file(db, trace_file, pipeline=pipeline)
    except CycleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StageDriftError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ImportResult(
        pipeline_id=pipeline.id,
        name=pipeline.name,
        stage_count=len(trace_file.pipeline.stages),
        trace_count=len(trace_file.traces),
    )


@router.get("/{pipeline_id}/runs", response_model=list[RunOut])
def list_runs(pipeline_id: int, db: Session = Depends(get_db)) -> list[RunOut]:
    """Every run (BenchmarkSet) imported against this pipeline, oldest
    first — powers the "Import new run" flow's audit trail. 404s the same
    way every other /{pipeline_id}/... route here does if the pipeline
    itself doesn't exist, rather than silently returning an empty list.
    """
    pipeline = db.get(models.Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")

    rows = db.execute(
        select(
            models.BenchmarkSet.id,
            models.BenchmarkSet.name,
            models.BenchmarkSet.created_at,
            func.count(models.Trace.id),
        )
        .outerjoin(models.Trace, models.Trace.benchmark_set_id == models.BenchmarkSet.id)
        .where(models.BenchmarkSet.pipeline_id == pipeline_id)
        .group_by(models.BenchmarkSet.id)
        .order_by(models.BenchmarkSet.created_at)
    ).all()

    return [
        RunOut(id=row[0], name=row[1], created_at=row[2], trace_count=row[3])
        for row in rows
    ]


@router.get("", response_model=list[PipelineSummary])
def list_pipelines(db: Session = Depends(get_db)) -> list[PipelineSummary]:
    pipelines = db.scalars(
        select(models.Pipeline).options(
            selectinload(models.Pipeline.stages),
            selectinload(models.Pipeline.benchmark_sets).selectinload(
                models.BenchmarkSet.traces
            ),
        )
    ).all()

    summaries: list[PipelineSummary] = []
    for pipeline in pipelines:
        query_count = sum(
            len(bs.traces) for bs in pipeline.benchmark_sets
        )
        summaries.append(
            PipelineSummary(
                id=pipeline.id,
                name=pipeline.name,
                stage_count=len(pipeline.stages),
                models_used=sorted({s.model for s in pipeline.stages}),
                benchmark_query_count=query_count,
            )
        )
    return summaries


@router.patch("/{pipeline_id}", response_model=PipelineSummary)
def update_pipeline(
    pipeline_id: int, update: PipelineUpdate, db: Session = Depends(get_db)
) -> PipelineSummary:
    """Rename a pipeline — used by the unified workspace header's
    click-to-edit-inline name field (apps/web's pipeline-workspace.tsx).
    Same PATCH-whole-resource pattern as settings.py's update_workspace_settings.
    """
    pipeline = db.get(
        models.Pipeline,
        pipeline_id,
        options=[
            selectinload(models.Pipeline.stages),
            selectinload(models.Pipeline.benchmark_sets).selectinload(
                models.BenchmarkSet.traces
            ),
        ],
    )
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")

    pipeline.name = update.name
    db.commit()
    db.refresh(pipeline)

    query_count = sum(len(bs.traces) for bs in pipeline.benchmark_sets)
    return PipelineSummary(
        id=pipeline.id,
        name=pipeline.name,
        stage_count=len(pipeline.stages),
        models_used=sorted({s.model for s in pipeline.stages}),
        benchmark_query_count=query_count,
    )


@router.delete("/{pipeline_id}", status_code=204)
def delete_pipeline(pipeline_id: int, db: Session = Depends(get_db)) -> None:
    """Hard delete a pipeline and every child row underneath it (stages,
    rubrics, benchmark sets/traces/stage records, migrations/candidates).
    Safe as a single `db.delete()` — every Pipeline-rooted relationship in
    models.py is declared `cascade="all, delete-orphan"`, and each of
    those children cascades further down the same way (Stage -> rubric/
    stage_records/candidates, BenchmarkSet -> traces -> stage_records,
    Migration -> candidates), so nothing is left orphaned. Same
    404-if-missing / 204-on-success shape as settings.py's delete_api_key.
    The frontend is expected to confirm with the user before calling this
    — it is not idempotent-safe to retry blindly (a second call 404s).
    """
    pipeline = db.get(models.Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")

    db.delete(pipeline)
    db.commit()


@router.get("/{pipeline_id}/dag", response_model=DagResponse)
def get_pipeline_dag(pipeline_id: int, db: Session = Depends(get_db)) -> DagResponse:
    pipeline = db.get(
        models.Pipeline,
        pipeline_id,
        options=[selectinload(models.Pipeline.stages).selectinload(models.Stage.depends_on)],
    )
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")

    # Reconstruct a minimal packages/core Pipeline purely to reuse build_dag's
    # single, tested implementation of toposort + cycle detection, rather
    # than re-deriving layering logic here.
    from reprompt_core import Pipeline as CorePipeline
    from reprompt_core import Stage as CoreStage

    id_by_db_id = {stage.id: str(stage.id) for stage in pipeline.stages}
    core_stages = [
        CoreStage(
            id=id_by_db_id[stage.id],
            name=stage.name,
            depends_on=[id_by_db_id[dep.id] for dep in stage.depends_on],
            model=stage.model,
            prompt_template=stage.prompt_template,
        )
        for stage in pipeline.stages
    ]
    core_pipeline = CorePipeline(
        id=str(pipeline.id), name=pipeline.name, stages=core_stages
    )

    try:
        dag = build_dag(core_pipeline)
    except CycleError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    layers = [
        DagLayer(stage_ids=[int(stage_id) for stage_id in layer])
        for layer in dag.layers
    ]

    stage_ids = [stage.id for stage in pipeline.stages]
    avg_rows = db.execute(
        select(
            models.StageRecord.stage_id,
            func.avg(models.StageRecord.tokens_in),
            func.avg(models.StageRecord.tokens_out),
            func.avg(models.StageRecord.latency_ms),
        )
        .where(models.StageRecord.stage_id.in_(stage_ids))
        .group_by(models.StageRecord.stage_id)
    ).all()
    averages = {
        row[0]: (row[1] or 0.0, row[2] or 0.0, row[3] or 0.0) for row in avg_rows
    }

    stage_info = {
        stage.id: StageInfo(
            id=stage.id,
            name=stage.name,
            model=stage.model,
            avg_tokens_in=averages.get(stage.id, (0.0, 0.0, 0.0))[0],
            avg_tokens_out=averages.get(stage.id, (0.0, 0.0, 0.0))[1],
            avg_latency_ms=averages.get(stage.id, (0.0, 0.0, 0.0))[2],
        )
        for stage in pipeline.stages
    }

    edges = [
        DagEdge(from_stage_id=dep.id, to_stage_id=stage.id)
        for stage in pipeline.stages
        for dep in stage.depends_on
    ]

    return DagResponse(
        pipeline_id=pipeline.id, layers=layers, stages=stage_info, edges=edges
    )


# ---------------------------------------------------------------------------
# Test-prompt (M5, BYOK proof-of-concept)
# ---------------------------------------------------------------------------
#
# Proves the workspace-BYOK-key -> live complete() wiring works end to end
# (reprompt_api.llm_context). Deliberately a small smoke-test tool, not a
# polished feature: no prompt-template variable rendering (the raw
# prompt_template text goes straight to the model as one user message), no
# retry/streaming, no persistence of the result anywhere. Sits behind
# get_current_user, unlike every other endpoint in this router, because it
# is the one thing here that touches a workspace-owned secret.


class TestPromptIn(BaseModel):
    model: str = Field(
        min_length=1, max_length=255, description="A LiteLLM model string, e.g. 'gpt-4o'."
    )


class TestPromptOut(BaseModel):
    content: str
    model: str
    provider: str | None
    usage: TokenUsage
    cost_usd: float | None
    latency_ms: float
    finish_reason: str | None


def _get_workspace_or_500(db: Session, user: models.User) -> models.Workspace:
    """Every authenticated User has exactly one Workspace (see auth.py /
    models.py) - a missing one is a data-integrity bug, not a client
    error. Small local copy of reprompt_api.settings._get_workspace_or_500
    (that one is module-private) rather than a cross-module import, since
    this is the only place in pipelines.py that needs a workspace at all.
    """
    workspace = db.scalar(
        select(models.Workspace).where(models.Workspace.owner_user_id == user.id)
    )
    if workspace is None:
        raise HTTPException(
            status_code=500,
            detail="No workspace found for this account. This shouldn't happen.",
        )
    return workspace


@router.post("/{pipeline_id}/stages/{stage_id}/test-prompt", response_model=TestPromptOut)
def test_prompt(
    pipeline_id: int,
    stage_id: int,
    body: TestPromptIn,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TestPromptOut:
    """Send `stage_id`'s existing prompt_template, unmodified, as a single
    user message to `body.model`, using the current user's workspace's
    saved BYOK key for that model's provider — see reprompt_api.llm_context
    for how the encrypted key is decrypted and scoped to exactly this one
    call. Returns a clear 422 naming the missing provider (pointing at
    /settings) if the workspace hasn't configured a key for it yet, rather
    than the env-var-flavored MissingAPIKeyError reprompt_core.llm.client
    would otherwise raise.
    """
    stage = db.scalar(
        select(models.Stage).where(
            models.Stage.id == stage_id, models.Stage.pipeline_id == pipeline_id
        )
    )
    if stage is None:
        raise HTTPException(
            status_code=404,
            detail=f"Stage {stage_id} not found in pipeline {pipeline_id}",
        )

    workspace = _get_workspace_or_500(db, current_user)

    try:
        result = complete_with_workspace_credentials(
            db,
            workspace,
            body.model,
            [{"role": "user", "content": stage.prompt_template}],
        )
    except ProviderKeyNotConfigured as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No API key configured for provider '{exc.provider}' in this "
                "workspace. Add one at /settings before testing this model."
            ),
        ) from exc
    except EncryptionNotConfigured as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except TransientLLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (PermanentLLMError, RepromptLLMError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return TestPromptOut(
        content=result.content,
        model=result.model,
        provider=result.provider,
        usage=result.usage,
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
        finish_reason=result.finish_reason,
    )
