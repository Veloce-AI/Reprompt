"""Persist a validated reprompt_core.TraceFile into the SQLAlchemy models.

The heavy lifting (schema validation, referential integrity, DAG
correctness) already happened in packages/core (TraceFile / build_dag).
This module's only job is the mechanical translation from those in-memory
Pydantic objects into rows — Pipeline -> Stage[] (+ dependency edges) ->
BenchmarkSet -> Trace[] -> StageRecord[].

Also supports attaching a second (third, ...) run to an *existing* Pipeline
(see `pipeline=` below) — Stage rows are treated as immutable once created,
matching how Rubric/Candidate already assume a stable stage_id: an in-place
change to a stage's model/prompt/params would silently invalidate an
already-approved rubric with no way to detect it, so a drifted stage is
rejected outright (`StageDriftError`) rather than silently accepted or
versioned.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from reprompt_core import TraceFile, build_dag

from reprompt_api import models


class StageDriftError(Exception):
    """Raised when attaching a new run to an existing pipeline and one or
    more incoming stages' model/prompt_template/system_prompt/params differ
    from the already-persisted Stage row sharing the same source_id.

    Stage rows are immutable once created (Rubric/Candidate both assume a
    stable stage_id) - this exception is how `persist_trace_file` enforces
    that, rather than silently overwriting or versioning the row. Caller
    (pipelines.py) catches this and returns 422 naming the conflicting
    stage(s).
    """

    def __init__(self, conflicting_source_ids: list[str]):
        self.conflicting_source_ids = conflicting_source_ids
        stages = ", ".join(conflicting_source_ids)
        super().__init__(
            f"Stage definition changed for: {stages}. A pipeline's stages "
            "are immutable once created - re-import as a new pipeline if "
            "this is an intentional prompt change."
        )


def persist_trace_file(
    db: Session,
    trace_file: TraceFile,
    *,
    pipeline: models.Pipeline | None = None,
) -> models.Pipeline:
    """Create (or extend) a Pipeline from a validated TraceFile, and commit
    it. Raises on DB error; caller's responsibility to catch and roll back
    if used outside a fresh session.

    Also runs build_dag() as a final sanity check — a TraceFile can pass
    packages/core's own schema validation (referential integrity) while
    still containing a multi-stage cycle, which schema validation alone
    can't see. We don't want to persist a pipeline whose DAG can't be built.

    If `pipeline` is None (the default): behaves exactly as before - creates
    a brand-new Pipeline + Stage[] + one BenchmarkSet for this run.

    If `pipeline` is given: no new Pipeline is created. Each incoming stage
    is matched to an existing Stage by (pipeline_id, source_id): if found and
    identical (model/prompt_template/system_prompt/params all match), the
    existing row is reused as-is; if found but different, raises
    StageDriftError naming every conflicting stage (checked for *all*
    stages before anything is mutated, so a rejected import never leaves
    the session half-modified); if not found, a new Stage row is created
    (a pipeline can grow new stages across runs). A new BenchmarkSet is
    always created for the run.
    """
    # Raises CycleError if the stage graph can't be topologically sorted.
    build_dag(trace_file.pipeline)

    is_new_pipeline = pipeline is None
    if is_new_pipeline:
        pipeline = models.Pipeline(name=trace_file.pipeline.name)
        db.add(pipeline)
        db.flush()  # assign pipeline.id without committing yet
        stage_by_source_id: dict[str, models.Stage] = {}
    else:
        existing_stages = db.scalars(
            select(models.Stage).where(models.Stage.pipeline_id == pipeline.id)
        ).all()
        stage_by_source_id = {stage.source_id: stage for stage in existing_stages}

        # Detect drift across *all* incoming stages before mutating
        # anything, so a rejected import leaves the session untouched.
        conflicts: list[str] = []
        for stage in trace_file.pipeline.stages:
            existing = stage_by_source_id.get(stage.id)
            if existing is None:
                continue
            incoming_params = stage.params.model_dump(exclude_none=True)
            if (
                existing.model != stage.model
                or existing.prompt_template != stage.prompt_template
                or existing.system_prompt != stage.system_prompt
                or existing.params != incoming_params
            ):
                conflicts.append(stage.id)
        if conflicts:
            raise StageDriftError(conflicts)

    for stage in trace_file.pipeline.stages:
        if stage.id in stage_by_source_id:
            continue  # existing, identical stage - reuse the row as-is
        db_stage = models.Stage(
            pipeline_id=pipeline.id,
            source_id=stage.id,
            name=stage.name,
            model=stage.model,
            prompt_template=stage.prompt_template,
            system_prompt=stage.system_prompt,
            params=stage.params.model_dump(exclude_none=True),
            meta=stage.metadata,
        )
        db.add(db_stage)
        stage_by_source_id[stage.id] = db_stage
    db.flush()  # assign stage ids before wiring dependency edges

    for stage in trace_file.pipeline.stages:
        db_stage = stage_by_source_id[stage.id]
        for dep_id in stage.depends_on:
            dep_stage = stage_by_source_id[dep_id]
            if dep_stage not in db_stage.depends_on:
                db_stage.depends_on.append(dep_stage)

    if is_new_pipeline:
        benchmark_set_name = f"{trace_file.pipeline.name} benchmark"
    else:
        # Distinguish repeat runs against the same pipeline - "Run 2", "Run
        # 3", ... (the original import's own BenchmarkSet counts as "Run 1"
        # implicitly, just under its original descriptive name).
        prior_run_count = db.scalar(
            select(func.count())
            .select_from(models.BenchmarkSet)
            .where(models.BenchmarkSet.pipeline_id == pipeline.id)
        )
        benchmark_set_name = f"Run {prior_run_count + 1}"

    benchmark_set = models.BenchmarkSet(pipeline_id=pipeline.id, name=benchmark_set_name)
    db.add(benchmark_set)
    db.flush()

    for query_index, trace in enumerate(trace_file.traces):
        db_trace = models.Trace(
            benchmark_set_id=benchmark_set.id,
            source_trace_id=trace.trace_id,
            query=trace.query,
            query_index=query_index,
            meta=trace.metadata,
        )
        db.add(db_trace)
        db.flush()
        for record in trace.records:
            db_stage = stage_by_source_id[record.stage_id]
            # tokens is optional as of schema_version 1.1 (see
            # docs/trace-format.md) - a trace source that doesn't report
            # per-call token accounting leaves all three columns NULL rather
            # than coercing to 0, same "unknown != zero" reasoning already
            # applied to cost and (now) latency_ms.
            tokens = record.tokens
            db.add(
                models.StageRecord(
                    trace_id=db_trace.id,
                    stage_id=db_stage.id,
                    input=record.input,
                    rendered_prompt=record.rendered_prompt,
                    output=record.output,
                    tokens_in=tokens.input if tokens is not None else None,
                    tokens_out=tokens.output if tokens is not None else None,
                    tokens_thinking=(tokens.thinking if tokens is not None else None),
                    latency_ms=record.latency_ms,
                    cost=record.cost,
                    documents=record.documents,
                    meta=record.metadata,
                )
            )

    db.commit()
    db.refresh(pipeline)
    return pipeline
