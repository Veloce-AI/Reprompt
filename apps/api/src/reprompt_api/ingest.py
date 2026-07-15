"""Persist a validated reprompt_core.TraceFile into the SQLAlchemy models.

The heavy lifting (schema validation, referential integrity, DAG
correctness) already happened in packages/core (TraceFile / build_dag).
This module's only job is the mechanical translation from those in-memory
Pydantic objects into rows — Pipeline -> Stage[] (+ dependency edges) ->
BenchmarkSet -> Trace[] -> StageRecord[].
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from reprompt_core import TraceFile, build_dag

from reprompt_api import models


def persist_trace_file(db: Session, trace_file: TraceFile) -> models.Pipeline:
    """Create a Pipeline (+ stages, one BenchmarkSet, its traces/records) from
    a validated TraceFile, and commit it. Raises on DB error; caller's
    responsibility to catch and roll back if used outside a fresh session.

    Also runs build_dag() as a final sanity check — a TraceFile can pass
    packages/core's own schema validation (referential integrity) while
    still containing a multi-stage cycle, which schema validation alone
    can't see. We don't want to persist a pipeline whose DAG can't be built.
    """
    # Raises CycleError if the stage graph can't be topologically sorted.
    build_dag(trace_file.pipeline)

    pipeline = models.Pipeline(name=trace_file.pipeline.name)
    db.add(pipeline)
    db.flush()  # assign pipeline.id without committing yet

    stage_by_source_id: dict[str, models.Stage] = {}
    for stage in trace_file.pipeline.stages:
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
            db_stage.depends_on.append(stage_by_source_id[dep_id])

    benchmark_set = models.BenchmarkSet(
        pipeline_id=pipeline.id, name=f"{trace_file.pipeline.name} benchmark"
    )
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
