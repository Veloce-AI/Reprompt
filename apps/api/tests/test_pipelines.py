"""Tests for POST /pipelines/import, GET /pipelines, GET /pipelines/{id}/dag.

Builds trace-file payloads via reprompt_core's own Pydantic models (rather
than hand-writing raw JSON dicts) so these tests can't drift from the actual
schema packages/core enforces.
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


def _diamond_trace_file() -> TraceFile:
    """root -> {a, b in parallel} -> join, with one trace covering all 4 stages."""
    stages = [
        CoreStage(id="root", name="Root", model="gpt-4o", prompt_template="{{q}}"),
        CoreStage(id="a", name="Branch A", depends_on=["root"], model="gpt-4o", prompt_template="{{root}}"),
        CoreStage(id="b", name="Branch B", depends_on=["root"], model="claude-sonnet-4-5", prompt_template="{{root}}"),
        CoreStage(id="join", name="Join", depends_on=["a", "b"], model="gpt-4o", prompt_template="{{a}} {{b}}"),
    ]
    pipeline = CorePipeline(id="diamond", name="Diamond Test Pipeline", stages=stages)

    def record(stage_id: str) -> CoreStageRecord:
        return CoreStageRecord(
            stage_id=stage_id,
            input={"q": "hello"},
            rendered_prompt=f"prompt for {stage_id}",
            output=f"output for {stage_id}",
            tokens=TokenUsage(**{"in": 10, "out": 5}),
            latency_ms=100.0,
        )

    traces = [
        CoreTrace(
            trace_id="t0",
            query={"q": "hello"},
            records=[record("root"), record("a"), record("b"), record("join")],
        )
    ]
    return TraceFile(pipeline=pipeline, traces=traces)


def _upload(client: TestClient, trace_file: TraceFile, filename: str = "trace.json"):
    payload = trace_file.model_dump(by_alias=True)
    return client.post(
        "/pipelines/import",
        files={"file": (filename, json.dumps(payload), "application/json")},
    )


def test_import_valid_trace_file_persists_and_returns_summary(client: TestClient) -> None:
    trace_file = _diamond_trace_file()
    response = _upload(client, trace_file)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Diamond Test Pipeline"
    assert body["stage_count"] == 4
    assert body["trace_count"] == 1
    assert isinstance(body["pipeline_id"], int)


def test_import_malformed_json_returns_422_not_500(client: TestClient) -> None:
    response = client.post(
        "/pipelines/import",
        files={"file": ("trace.json", b"{not valid json", "application/json")},
    )
    assert response.status_code == 422
    assert "not valid JSON" in response.json()["detail"]


def test_import_schema_violation_returns_field_level_422(client: TestClient) -> None:
    trace_file = _diamond_trace_file()
    payload = trace_file.model_dump(by_alias=True)
    del payload["pipeline"]["stages"][0]["prompt_template"]

    response = client.post(
        "/pipelines/import",
        files={"file": ("trace.json", json.dumps(payload), "application/json")},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "prompt_template" in detail


def test_import_cycle_is_rejected_and_nothing_is_persisted(client: TestClient) -> None:
    stages = [
        CoreStage(id="a", name="A", depends_on=["b"], model="gpt-4o", prompt_template="{{q}}"),
        CoreStage(id="b", name="B", depends_on=["a"], model="gpt-4o", prompt_template="{{q}}"),
    ]
    pipeline = CorePipeline(id="cyclic", name="Cyclic Pipeline", stages=stages)
    trace = CoreTrace(
        trace_id="t0",
        query={"q": "x"},
        records=[
            CoreStageRecord(
                stage_id="a",
                rendered_prompt="p",
                output="o",
                tokens=TokenUsage(**{"in": 1, "out": 1}),
                latency_ms=1.0,
            ),
            CoreStageRecord(
                stage_id="b",
                rendered_prompt="p",
                output="o",
                tokens=TokenUsage(**{"in": 1, "out": 1}),
                latency_ms=1.0,
            ),
        ],
    )
    trace_file = TraceFile(pipeline=pipeline, traces=[trace])

    response = _upload(client, trace_file)
    assert response.status_code == 422
    assert "cycle" in response.json()["detail"]

    assert client.get("/pipelines").json() == []


def test_list_pipelines_reflects_imported_data(client: TestClient) -> None:
    _upload(client, _diamond_trace_file())

    response = client.get("/pipelines")
    assert response.status_code == 200
    pipelines = response.json()
    assert len(pipelines) == 1
    summary = pipelines[0]
    assert summary["name"] == "Diamond Test Pipeline"
    assert summary["stage_count"] == 4
    assert summary["models_used"] == ["claude-sonnet-4-5", "gpt-4o"]
    assert summary["benchmark_query_count"] == 1


def test_get_dag_returns_correctly_layered_diamond(client: TestClient) -> None:
    upload_response = _upload(client, _diamond_trace_file())
    pipeline_id = upload_response.json()["pipeline_id"]

    response = client.get(f"/pipelines/{pipeline_id}/dag")
    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_id"] == pipeline_id
    assert len(body["layers"]) == 3  # root | {a, b} | join
    assert len(body["layers"][1]["stage_ids"]) == 2
    stage_names = {info["name"] for info in body["stages"].values()}
    assert stage_names == {"Root", "Branch A", "Branch B", "Join"}


def test_get_dag_for_unknown_pipeline_returns_404(client: TestClient) -> None:
    response = client.get("/pipelines/999999/dag")
    assert response.status_code == 404


def test_patch_pipeline_renames_and_returns_updated_summary(client: TestClient) -> None:
    upload_response = _upload(client, _diamond_trace_file())
    pipeline_id = upload_response.json()["pipeline_id"]

    response = client.patch(f"/pipelines/{pipeline_id}", json={"name": "Renamed Pipeline"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == pipeline_id
    assert body["name"] == "Renamed Pipeline"
    assert body["stage_count"] == 4

    # Persisted, not just echoed back.
    listed = client.get("/pipelines").json()
    assert listed[0]["name"] == "Renamed Pipeline"


def test_patch_pipeline_rejects_empty_name(client: TestClient) -> None:
    upload_response = _upload(client, _diamond_trace_file())
    pipeline_id = upload_response.json()["pipeline_id"]

    response = client.patch(f"/pipelines/{pipeline_id}", json={"name": ""})
    assert response.status_code == 422


def test_patch_pipeline_for_unknown_pipeline_returns_404(client: TestClient) -> None:
    response = client.patch("/pipelines/999999", json={"name": "Doesn't matter"})
    assert response.status_code == 404


def test_import_minimal_stage_record_persists_null_tokens_and_latency(
    client: TestClient, session_factory: sessionmaker
) -> None:
    """Regression coverage for the ingest path added alongside schema_version
    1.1 (docs/trace-format.md): a StageRecord with no tokens/latency/cost/
    documents must import without crashing, and persist tokens_in/out/
    thinking and latency_ms as NULL - not coerced to 0 - since those columns
    are now nullable (apps/api/src/reprompt_api/models.py).
    """
    stages = [
        CoreStage(id="only", name="Only Stage", model="gpt-4o", prompt_template="{{q}}")
    ]
    pipeline = CorePipeline(id="minimal", name="Minimal Pipeline", stages=stages)
    trace = CoreTrace(
        trace_id="t0",
        query={"q": "hello"},
        records=[
            CoreStageRecord(stage_id="only", rendered_prompt="prompt", output="output")
        ],
    )
    trace_file = TraceFile(pipeline=pipeline, traces=[trace])

    response = _upload(client, trace_file)
    assert response.status_code == 201, response.text

    with session_factory() as db:
        records = db.query(models.StageRecord).all()
        assert len(records) == 1
        record = records[0]
        assert record.tokens_in is None
        assert record.tokens_out is None
        assert record.tokens_thinking is None
        assert record.latency_ms is None
        assert record.cost is None
        assert record.documents == []
        assert record.meta == {}


def test_import_preserves_source_ids_query_and_cost(
    client: TestClient, session_factory: sessionmaker
) -> None:
    """Regression test for a real data-loss bug: ingest previously dropped
    Trace.query, Trace.trace_id, and each Stage's source (user-facing) id
    entirely - found by an independent review, confirmed against real
    production trace data which needs exactly these fields preserved.
    """
    trace_file = _diamond_trace_file()
    upload_response = _upload(client, trace_file)
    assert upload_response.status_code == 201

    with session_factory() as db:
        stages = db.query(models.Stage).order_by(models.Stage.id).all()
        source_ids = {s.source_id for s in stages}
        assert source_ids == {"root", "a", "b", "join"}

        traces = db.query(models.Trace).all()
        assert len(traces) == 1
        assert traces[0].source_trace_id == "t0"
        assert traces[0].query == {"q": "hello"}

        records = db.query(models.StageRecord).all()
        assert len(records) == 4
        # _diamond_trace_file's records don't set cost - should persist as
        # None (unknown), not silently coerced to 0.
        assert all(r.cost is None for r in records)
