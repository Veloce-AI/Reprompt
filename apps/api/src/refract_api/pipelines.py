"""Pipeline import, listing, and DAG endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from refract_core import CycleError, TraceFileError, build_dag, parse_trace_file

from refract_api import models
from refract_api.db import get_db
from refract_api.ingest import persist_trace_file

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


class ImportResult(BaseModel):
    pipeline_id: int
    name: str
    stage_count: int
    trace_count: int


class PipelineSummary(BaseModel):
    id: int
    name: str
    stage_count: int
    models_used: list[str]
    benchmark_query_count: int


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


@router.post("/import", response_model=ImportResult, status_code=201)
async def import_pipeline(
    file: UploadFile, db: Session = Depends(get_db)
) -> ImportResult:
    """Upload a trace-format JSON file. Validates against the canonical
    schema (packages/core) before persisting anything. On any validation
    failure, returns 422 with a field-level error message — never a raw
    stack trace or a generic 500.
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
        trace_file = parse_trace_file(data)
    except TraceFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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
    from refract_core import Pipeline as CorePipeline
    from refract_core import Stage as CoreStage

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
