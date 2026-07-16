"""Tests for POST /pipelines/{pipeline_id}/import (attach a run to an
existing pipeline) and GET /pipelines/{pipeline_id}/runs — Phase 2's
project/multi-run ingestion. Uses the same reprompt_core-Pydantic-model
payload-building pattern as test_pipelines.py so these can't drift from the
actual trace-format schema.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from reprompt_core import (
    Pipeline as CorePipeline,
    Stage as CoreStage,
    StageRecord as CoreStageRecord,
    TokenUsage,
    Trace as CoreTrace,
    TraceFile,
)

from reprompt_api import models
from reprompt_api.db import get_db
from reprompt_api.main import app
from reprompt_api.models import Base


@pytest.fixture()
def session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def client(session_factory: sessionmaker) -> Iterator[TestClient]:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _record(stage_id: str) -> CoreStageRecord:
    return CoreStageRecord(
        stage_id=stage_id,
        input={"q": "hello"},
        rendered_prompt=f"prompt for {stage_id}",
        output=f"output for {stage_id}",
        tokens=TokenUsage(**{"in": 10, "out": 5}),
        latency_ms=100.0,
    )


def _diamond_trace_file(trace_id: str = "t0") -> TraceFile:
    """root -> {a, b in parallel} -> join, with one trace covering all 4 stages."""
    stages = [
        CoreStage(id="root", name="Root", model="gpt-4o", prompt_template="{{q}}"),
        CoreStage(id="a", name="Branch A", depends_on=["root"], model="gpt-4o", prompt_template="{{root}}"),
        CoreStage(id="b", name="Branch B", depends_on=["root"], model="claude-sonnet-4-5", prompt_template="{{root}}"),
        CoreStage(id="join", name="Join", depends_on=["a", "b"], model="gpt-4o", prompt_template="{{a}} {{b}}"),
    ]
    pipeline = CorePipeline(id="diamond", name="Diamond Test Pipeline", stages=stages)
    traces = [
        CoreTrace(
            trace_id=trace_id,
            query={"q": "hello"},
            records=[_record("root"), _record("a"), _record("b"), _record("join")],
        )
    ]
    return TraceFile(pipeline=pipeline, traces=traces)


def _upload(client: TestClient, trace_file: TraceFile, url: str, filename: str = "trace.json"):
    payload = trace_file.model_dump(by_alias=True)
    return client.post(
        url,
        files={"file": (filename, json.dumps(payload), "application/json")},
    )


def test_import_into_existing_pipeline_reuses_matching_stage_rows(
    client: TestClient, session_factory: sessionmaker
) -> None:
    first = _upload(client, _diamond_trace_file("t0"), "/pipelines/import")
    assert first.status_code == 201, first.text
    pipeline_id = first.json()["pipeline_id"]

    with session_factory() as db:
        original_stage_ids = sorted(
            s.id for s in db.query(models.Stage).filter_by(pipeline_id=pipeline_id).all()
        )

    second = _upload(
        client, _diamond_trace_file("t1"), f"/pipelines/{pipeline_id}/import"
    )
    assert second.status_code == 201, second.text
    body = second.json()
    assert body["pipeline_id"] == pipeline_id
    assert body["stage_count"] == 4

    with session_factory() as db:
        stages = db.query(models.Stage).filter_by(pipeline_id=pipeline_id).all()
        # Still exactly 4 stages - the second run's identical stages reused
        # the existing rows rather than creating a parallel set.
        assert sorted(s.id for s in stages) == original_stage_ids

        pipelines = db.query(models.Pipeline).all()
        assert len(pipelines) == 1  # no second Pipeline created

        benchmark_sets = db.query(models.BenchmarkSet).filter_by(pipeline_id=pipeline_id).all()
        assert len(benchmark_sets) == 2  # one BenchmarkSet per run


def test_import_into_existing_pipeline_adds_a_genuinely_new_stage(
    client: TestClient, session_factory: sessionmaker
) -> None:
    first = _upload(client, _diamond_trace_file("t0"), "/pipelines/import")
    pipeline_id = first.json()["pipeline_id"]

    stages = [
        CoreStage(id="root", name="Root", model="gpt-4o", prompt_template="{{q}}"),
        CoreStage(id="a", name="Branch A", depends_on=["root"], model="gpt-4o", prompt_template="{{root}}"),
        CoreStage(id="b", name="Branch B", depends_on=["root"], model="claude-sonnet-4-5", prompt_template="{{root}}"),
        CoreStage(id="join", name="Join", depends_on=["a", "b"], model="gpt-4o", prompt_template="{{a}} {{b}}"),
        CoreStage(id="extra", name="Extra", depends_on=["join"], model="gpt-4o", prompt_template="{{join}}"),
    ]
    pipeline = CorePipeline(id="diamond", name="Diamond Test Pipeline", stages=stages)
    trace = CoreTrace(
        trace_id="t1",
        query={"q": "hello"},
        records=[_record("root"), _record("a"), _record("b"), _record("join"), _record("extra")],
    )
    trace_file = TraceFile(pipeline=pipeline, traces=[trace])

    response = _upload(client, trace_file, f"/pipelines/{pipeline_id}/import")
    assert response.status_code == 201, response.text
    assert response.json()["stage_count"] == 5

    with session_factory() as db:
        db_stages = db.query(models.Stage).filter_by(pipeline_id=pipeline_id).all()
        assert len(db_stages) == 5
        extra = next(s for s in db_stages if s.source_id == "extra")
        join = next(s for s in db_stages if s.source_id == "join")
        assert [d.id for d in extra.depends_on] == [join.id]


def test_import_into_existing_pipeline_rejects_drifted_stage(
    client: TestClient, session_factory: sessionmaker
) -> None:
    first = _upload(client, _diamond_trace_file("t0"), "/pipelines/import")
    pipeline_id = first.json()["pipeline_id"]

    drifted_stages = [
        CoreStage(id="root", name="Root", model="gpt-4o", prompt_template="{{q}} CHANGED"),
        CoreStage(id="a", name="Branch A", depends_on=["root"], model="gpt-4o", prompt_template="{{root}}"),
        CoreStage(id="b", name="Branch B", depends_on=["root"], model="claude-sonnet-4-5", prompt_template="{{root}}"),
        CoreStage(id="join", name="Join", depends_on=["a", "b"], model="gpt-4o", prompt_template="{{a}} {{b}}"),
    ]
    pipeline = CorePipeline(id="diamond", name="Diamond Test Pipeline", stages=drifted_stages)
    trace = CoreTrace(
        trace_id="t1",
        query={"q": "hello"},
        records=[_record("root"), _record("a"), _record("b"), _record("join")],
    )
    trace_file = TraceFile(pipeline=pipeline, traces=[trace])

    response = _upload(client, trace_file, f"/pipelines/{pipeline_id}/import")
    assert response.status_code == 422
    assert "root" in response.json()["detail"]

    with session_factory() as db:
        # Nothing from the rejected run was persisted.
        benchmark_sets = db.query(models.BenchmarkSet).filter_by(pipeline_id=pipeline_id).all()
        assert len(benchmark_sets) == 1
        stages = db.query(models.Stage).filter_by(pipeline_id=pipeline_id).all()
        assert len(stages) == 4
        root = next(s for s in stages if s.source_id == "root")
        assert root.prompt_template == "{{q}}"  # unchanged


def test_import_into_existing_pipeline_404_for_unknown_pipeline(client: TestClient) -> None:
    response = _upload(client, _diamond_trace_file(), "/pipelines/999999/import")
    assert response.status_code == 404


def test_list_runs_returns_id_name_created_at_trace_count(
    client: TestClient, session_factory: sessionmaker
) -> None:
    first = _upload(client, _diamond_trace_file("t0"), "/pipelines/import")
    pipeline_id = first.json()["pipeline_id"]

    trace_file_2 = _diamond_trace_file("t1")
    trace_file_2.traces.append(
        CoreTrace(
            trace_id="t2",
            query={"q": "second query"},
            records=[_record("root"), _record("a"), _record("b"), _record("join")],
        )
    )
    second = _upload(client, trace_file_2, f"/pipelines/{pipeline_id}/import")
    assert second.status_code == 201, second.text

    response = client.get(f"/pipelines/{pipeline_id}/runs")
    assert response.status_code == 200
    runs = response.json()
    assert len(runs) == 2

    for run in runs:
        assert set(run.keys()) == {"id", "name", "created_at", "trace_count"}
        assert isinstance(run["id"], int)
        assert isinstance(run["name"], str) and run["name"]
        assert isinstance(run["created_at"], str)

    assert runs[0]["trace_count"] == 1
    assert runs[1]["trace_count"] == 2


def test_list_runs_404_for_unknown_pipeline(client: TestClient) -> None:
    response = client.get("/pipelines/999999/runs")
    assert response.status_code == 404
