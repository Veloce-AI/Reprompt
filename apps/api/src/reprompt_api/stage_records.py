"""Stage-record browser: GET /pipelines/{pipeline_id}/stage-records.

Backs the pipeline workspace's read-only "Data" tab (apps/web's
data-table.tsx) — a spreadsheet-style, cursor-paginated view over every
`StageRecord` (input, rendered prompt, output, token/cost/latency) captured
for a pipeline's benchmark traces. New file, not folded into the already-large
pipelines.py, per this phase's own scope note (a second agent is editing
pipelines.py in a parallel worktree at the same time).

Cursor pagination is deliberately the simplest possible form — a strict
`StageRecord.id > cursor ORDER BY id LIMIT limit` — since `id` is an
autoincrementing surrogate key with no updates/deletes on this table in the
product today, so it's stable across pages. No offset/page-number pagination
(doesn't scale) and no fetch-all-then-filter in Python (all filtering is
pushed into the SQL WHERE clause via the join below).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from reprompt_api import models
from reprompt_api.db import get_db

router = APIRouter(prefix="/pipelines", tags=["stage-records"])


class StageRecordOut(BaseModel):
    id: int
    stage_id: int
    stage_name: str
    trace_id: int
    input: dict
    rendered_prompt: str
    output: str
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: float | None
    cost: float | None


class StageRecordsPage(BaseModel):
    records: list[StageRecordOut]
    next_cursor: int | None


@router.get("/{pipeline_id}/stage-records", response_model=StageRecordsPage)
def list_stage_records(
    pipeline_id: int,
    stage_id: int | None = None,
    trace_id: int | None = None,
    cursor: int = Query(0, ge=0, description="Return records with id > cursor"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> StageRecordsPage:
    """Server-side filtered + paginated. Always scoped to `pipeline_id` via
    the StageRecord -> Trace -> BenchmarkSet join (a StageRecord has no
    direct pipeline_id column); `stage_id`/`trace_id` are additional optional
    equality filters, applied in the same query. Fetches `limit + 1` rows to
    cheaply know whether a next page exists without a second COUNT query.
    """
    query = (
        select(models.StageRecord, models.Stage.name)
        .join(models.Stage, models.StageRecord.stage_id == models.Stage.id)
        .join(models.Trace, models.StageRecord.trace_id == models.Trace.id)
        .join(
            models.BenchmarkSet,
            models.Trace.benchmark_set_id == models.BenchmarkSet.id,
        )
        .where(models.BenchmarkSet.pipeline_id == pipeline_id)
        .where(models.StageRecord.id > cursor)
    )
    if stage_id is not None:
        query = query.where(models.StageRecord.stage_id == stage_id)
    if trace_id is not None:
        query = query.where(models.StageRecord.trace_id == trace_id)

    query = query.order_by(models.StageRecord.id).limit(limit + 1)

    rows = db.execute(query).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    records = [
        StageRecordOut(
            id=rec.id,
            stage_id=rec.stage_id,
            stage_name=stage_name,
            trace_id=rec.trace_id,
            input=rec.input,
            rendered_prompt=rec.rendered_prompt,
            output=rec.output,
            tokens_in=rec.tokens_in,
            tokens_out=rec.tokens_out,
            latency_ms=rec.latency_ms,
            cost=rec.cost,
        )
        for rec, stage_name in rows
    ]

    next_cursor = records[-1].id if has_more and records else None
    return StageRecordsPage(records=records, next_cursor=next_cursor)
