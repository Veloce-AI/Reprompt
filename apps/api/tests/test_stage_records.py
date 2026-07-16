"""Tests for GET /pipelines/{pipeline_id}/stage-records.

Same fixture/upload-via-API pattern as test_pipelines.py (builds trace-file
payloads via reprompt_core's own Pydantic models rather than hand-writing
raw JSON, so these tests can't drift from the actual schema).
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


def _two_stage_trace_file(num_traces: int) -> TraceFile:
    """A -> B pipeline, `num_traces` traces each producing 2 stage records
    (one per stage) — so total stage record count is 2 * num_traces.
    """
    stages = [
        CoreStage(id="extract", name="Extract", model="gpt-4o", prompt_template="{{q}}"),
        CoreStage(
            id="summarize",
            name="Summarize",
            depends_on=["extract"],
            model="gpt-4o",
            prompt_template="{{extract}}",
        ),
    ]
    pipeline = CorePipeline(id="two-stage", name="Two Stage Pipeline", stages=stages)

    def record(stage_id: str, i: int) -> CoreStageRecord:
        return CoreStageRecord(
            stage_id=stage_id,
            input={"q": f"query {i}"},
            rendered_prompt=f"prompt {stage_id} {i}",
            output=f"output {stage_id} {i}",
            tokens=TokenUsage(**{"in": 10 + i, "out": 5 + i}),
            latency_ms=100.0 + i,
        )

    traces = [
        CoreTrace(
            trace_id=f"t{i}",
            query={"q": f"query {i}"},
            records=[record("extract", i), record("summarize", i)],
        )
        for i in range(num_traces)
    ]
    return TraceFile(pipeline=pipeline, traces=traces)


def _upload(client: TestClient, trace_file: TraceFile) -> int:
    payload = trace_file.model_dump(by_alias=True)
    response = client.post(
        "/pipelines/import",
        files={"file": ("trace.json", json.dumps(payload), "application/json")},
    )
    assert response.status_code == 201, response.text
    return response.json()["pipeline_id"]


def test_list_stage_records_returns_all_fields(client: TestClient) -> None:
    pipeline_id = _upload(client, _two_stage_trace_file(1))

    response = client.get(f"/pipelines/{pipeline_id}/stage-records")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["records"]) == 2
    assert body["next_cursor"] is None

    rec = next(r for r in body["records"] if r["stage_name"] == "Extract")
    assert rec["rendered_prompt"] == "prompt extract 0"
    assert rec["output"] == "output extract 0"
    assert rec["input"] == {"q": "query 0"}
    assert rec["tokens_in"] == 10
    assert rec["tokens_out"] == 5
    assert rec["latency_ms"] == 100.0
    assert isinstance(rec["trace_id"], int)
    assert isinstance(rec["stage_id"], int)


def test_cursor_pagination_walks_all_pages_without_overlap_or_gaps(
    client: TestClient,
) -> None:
    pipeline_id = _upload(client, _two_stage_trace_file(5))  # 10 stage records total

    seen_ids: list[int] = []
    cursor = 0
    pages = 0
    while True:
        response = client.get(
            f"/pipelines/{pipeline_id}/stage-records",
            params={"cursor": cursor, "limit": 4},
        )
        assert response.status_code == 200
        body = response.json()
        seen_ids.extend(r["id"] for r in body["records"])
        pages += 1
        if body["next_cursor"] is None:
            break
        cursor = body["next_cursor"]
        assert pages < 20  # safety valve against an infinite loop on a bug

    assert pages == 3  # 4 + 4 + 2
    assert len(seen_ids) == 10
    assert len(set(seen_ids)) == 10  # no duplicates across pages
    assert seen_ids == sorted(seen_ids)  # strictly increasing order


def test_stage_id_filter_returns_only_that_stage(client: TestClient) -> None:
    pipeline_id = _upload(client, _two_stage_trace_file(3))

    dag = client.get(f"/pipelines/{pipeline_id}/dag").json()
    extract_stage_id = next(
        int(sid) for sid, info in dag["stages"].items() if info["name"] == "Extract"
    )

    response = client.get(
        f"/pipelines/{pipeline_id}/stage-records", params={"stage_id": extract_stage_id}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["records"]) == 3
    assert all(r["stage_id"] == extract_stage_id for r in body["records"])
    assert all(r["stage_name"] == "Extract" for r in body["records"])


def test_trace_id_filter_returns_only_that_traces_records(client: TestClient) -> None:
    pipeline_id = _upload(client, _two_stage_trace_file(3))

    all_records = client.get(f"/pipelines/{pipeline_id}/stage-records").json()["records"]
    one_trace_id = all_records[0]["trace_id"]

    response = client.get(
        f"/pipelines/{pipeline_id}/stage-records", params={"trace_id": one_trace_id}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["records"]) == 2  # extract + summarize for that one trace
    assert all(r["trace_id"] == one_trace_id for r in body["records"])


def test_stage_records_scoped_to_pipeline_no_cross_pipeline_leakage(
    client: TestClient,
) -> None:
    pipeline_a_id = _upload(client, _two_stage_trace_file(2))
    pipeline_b_id = _upload(client, _two_stage_trace_file(3))
    assert pipeline_a_id != pipeline_b_id

    response_a = client.get(f"/pipelines/{pipeline_a_id}/stage-records")
    response_b = client.get(f"/pipelines/{pipeline_b_id}/stage-records")

    assert len(response_a.json()["records"]) == 4  # 2 traces * 2 stages
    assert len(response_b.json()["records"]) == 6  # 3 traces * 2 stages

    ids_a = {r["id"] for r in response_a.json()["records"]}
    ids_b = {r["id"] for r in response_b.json()["records"]}
    assert ids_a.isdisjoint(ids_b)


def test_unknown_pipeline_returns_empty_list_not_error(client: TestClient) -> None:
    response = client.get("/pipelines/999999/stage-records")
    assert response.status_code == 200
    assert response.json() == {"records": [], "next_cursor": None}
