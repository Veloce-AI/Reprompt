"""Tests for POST /pipelines/import, GET /pipelines, GET /pipelines/{id}/dag.

Builds trace-file payloads via refract_core's own Pydantic models (rather
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

from refract_core import (
    Pipeline as CorePipeline,
    Stage as CoreStage,
    StageRecord as CoreStageRecord,
    TokenUsage,
    Trace as CoreTrace,
    TraceFile,
)

from refract_api.db import get_db
from refract_api.main import app
from refract_api.models import Base


@pytest.fixture()
def client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine)

    def override_get_db():
        db = testing_session()
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
    assert set(body["stages"].values()) == {"Root", "Branch A", "Branch B", "Join"}


def test_get_dag_for_unknown_pipeline_returns_404(client: TestClient) -> None:
    response = client.get("/pipelines/999999/dag")
    assert response.status_code == 404
