"""Round-trip tests for the core SQLAlchemy data model (M1.3).

Uses an in-memory SQLite engine + Base.metadata.create_all() rather than
running the Alembic migration — it's the faster, more isolated option for a
unit test and doesn't depend on filesystem state. `alembic upgrade head`
against a real (throwaway) SQLite file is exercised manually/in CI as a
separate migration-sanity check.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from refract_api.models import (
    Base,
    BenchmarkSet,
    Pipeline,
    Rubric,
    Stage,
    StageRecord,
    Trace,
)


@pytest.fixture()
def session_factory() -> sessionmaker:
    # StaticPool + a single shared connection keeps the in-memory DB alive
    # across multiple Session() instances within a test (default SQLite
    # in-memory behavior tears the DB down when the connection closes).
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _build_object_graph(db: Session) -> int:
    """Persists one Pipeline w/ 2 Stages, a BenchmarkSet w/ one Trace w/ 2
    StageRecords, and a Rubric on the first stage. Returns the pipeline id.
    """
    pipeline = Pipeline(name="Valuation Pipeline")

    stage_extract = Stage(
        source_id="extract_financials",
        name="extract_financials",
        model="claude-sonnet-4-5",
        prompt_template="Extract financial line items from: {input}",
        params={"temperature": 0.2, "top_p": 1.0, "max_tokens": 2048, "format_mode": "json"},
    )
    stage_summarize = Stage(
        source_id="summarize_valuation",
        name="summarize_valuation",
        model="claude-sonnet-4-5",
        prompt_template="Summarize the valuation given: {input}",
        params={"temperature": 0.3, "top_p": 1.0, "max_tokens": 1024, "format_mode": "markdown"},
    )
    # stage_summarize depends on stage_extract's output.
    stage_summarize.depends_on = [stage_extract]

    pipeline.stages = [stage_extract, stage_summarize]

    benchmark_set = BenchmarkSet(name="optimize-set-v1", pipeline=pipeline)
    trace = Trace(
        source_trace_id="trace-0",
        query={"raw_text": "Q3 revenue was $4.2M"},
        query_index=0,
        is_holdout=False,
        benchmark_set=benchmark_set,
    )

    record_extract = StageRecord(
        stage=stage_extract,
        trace=trace,
        input={"raw_text": "Q3 revenue was $4.2M"},
        rendered_prompt="Extract financial line items from: Q3 revenue was $4.2M",
        output={"revenue": 4_200_000, "currency": "USD"},
        tokens_in=42,
        tokens_out=18,
        tokens_thinking=0,
        latency_ms=812.5,
    )
    record_summarize = StageRecord(
        stage=stage_summarize,
        trace=trace,
        input={"revenue": 4_200_000, "currency": "USD"},
        rendered_prompt="Summarize the valuation given: {revenue: 4200000}",
        output={"summary": "Revenue grew to $4.2M in Q3."},
        tokens_in=30,
        tokens_out=22,
        tokens_thinking=5,
        latency_ms=640.0,
    )

    rubric = Rubric(
        stage=stage_extract,
        deterministic_checks={"required_keys": ["revenue", "currency"]},
        judge_criteria={"criteria": [{"name": "accurate_revenue", "weight": 1.0}]},
        downstream_contract={"consumed_fields": ["revenue", "currency"]},
    )

    db.add_all(
        [
            pipeline,
            stage_extract,
            stage_summarize,
            benchmark_set,
            trace,
            record_extract,
            record_summarize,
            rubric,
        ]
    )
    db.commit()
    return pipeline.id


def test_object_graph_round_trips(session_factory: sessionmaker) -> None:
    with session_factory() as db:
        pipeline_id = _build_object_graph(db)

    # Fresh session to force a real reload from the DB, not the identity map.
    with session_factory() as db:
        pipeline = db.get(Pipeline, pipeline_id)
        assert pipeline is not None
        assert pipeline.name == "Valuation Pipeline"
        assert pipeline.created_at is not None
        assert pipeline.updated_at is not None

        # Pipeline.stages relationship.
        stages = {s.name: s for s in pipeline.stages}
        assert set(stages) == {"extract_financials", "summarize_valuation"}

        stage_extract = stages["extract_financials"]
        stage_summarize = stages["summarize_valuation"]

        # depends_on / dependents self-referential relationship.
        assert [s.id for s in stage_summarize.depends_on] == [stage_extract.id]
        assert [s.id for s in stage_extract.dependents] == [stage_summarize.id]
        assert stage_extract.depends_on == []
        assert stage_summarize.dependents == []

        # params JSON round-trips as a dict with correct types.
        assert stage_extract.params["temperature"] == 0.2
        assert stage_extract.params["format_mode"] == "json"

        # BenchmarkSet -> Trace -> StageRecord chain.
        assert len(pipeline.benchmark_sets) == 1
        benchmark_set = pipeline.benchmark_sets[0]
        assert benchmark_set.name == "optimize-set-v1"
        assert len(benchmark_set.traces) == 1

        trace = benchmark_set.traces[0]
        assert trace.query_index == 0
        assert trace.is_holdout is False

        # Trace.stage_records relationship, queryable and correctly linked.
        assert len(trace.stage_records) == 2
        records_by_stage = {r.stage.name: r for r in trace.stage_records}
        assert set(records_by_stage) == {"extract_financials", "summarize_valuation"}

        rec_extract = records_by_stage["extract_financials"]
        assert rec_extract.input == {"raw_text": "Q3 revenue was $4.2M"}
        assert rec_extract.output == {"revenue": 4_200_000, "currency": "USD"}
        assert rec_extract.tokens_in == 42
        assert rec_extract.tokens_out == 18
        assert rec_extract.tokens_thinking == 0
        assert rec_extract.latency_ms == pytest.approx(812.5)

        rec_summarize = records_by_stage["summarize_valuation"]
        assert rec_summarize.tokens_thinking == 5
        assert rec_summarize.latency_ms == pytest.approx(640.0)

        # StageRecord -> Stage back-reference (querying via the stage side too).
        assert {r.id for r in stage_extract.stage_records} == {rec_extract.id}
        assert {r.id for r in stage_summarize.stage_records} == {rec_summarize.id}

        # Rubric one-to-one relationship, both directions.
        assert stage_extract.rubric is not None
        assert stage_extract.rubric.deterministic_checks == {
            "required_keys": ["revenue", "currency"]
        }
        assert stage_extract.rubric.downstream_contract == {
            "consumed_fields": ["revenue", "currency"]
        }
        assert stage_summarize.rubric is None
