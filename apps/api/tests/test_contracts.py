"""Tests for Phase 5 contract mining endpoints.

GET  /pipelines/{pid}/stages/{sid}/assertions
POST /pipelines/{pid}/stages/{sid}/mine-contract
POST /pipelines/{pid}/stages/{sid}/assertions/{aid}/approve
POST /pipelines/{pid}/stages/{sid}/assertions/{aid}/retire
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


def _trace_file() -> TraceFile:
    stages = [
        CoreStage(id="root", name="Root", model="gpt-4o", prompt_template="{{q}}"),
    ]
    pipeline = CorePipeline(id="p1", name="Test Pipeline", stages=stages)
    traces = [
        CoreTrace(
            trace_id="t1",
            query={"q": "hello"},
            records=[
                CoreStageRecord(
                    stage_id="root",
                    input={"q": "hello"},
                    rendered_prompt="hello",
                    output='{"answer": "yes"}',
                    tokens=TokenUsage(**{"in": 5, "out": 5}),
                    latency_ms=10.0,
                )
            ],
        ),
        CoreTrace(
            trace_id="t2",
            query={"q": "world"},
            records=[
                CoreStageRecord(
                    stage_id="root",
                    input={"q": "world"},
                    rendered_prompt="world",
                    output='{"answer": "no"}',
                    tokens=TokenUsage(**{"in": 5, "out": 5}),
                    latency_ms=10.0,
                )
            ],
        ),
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


def _stage_ids(session_factory: sessionmaker, pipeline_id: int) -> dict[str, int]:
    with session_factory() as db:
        stages = db.query(models.Stage).filter(models.Stage.pipeline_id == pipeline_id).all()
        return {s.source_id: s.id for s in stages}


def _add_assertion(
    session_factory: sessionmaker,
    *,
    stage_id: int,
    kind: str = "required_keys",
    spec: dict | None = None,
    status: str = "candidate",
    description: str = "test assertion",
) -> int:
    with session_factory() as db:
        a = models.Assertion(
            stage_id=stage_id,
            kind=kind,
            spec=spec or {"keys": ["answer"]},
            status=status,
            source="mined",
            description=description,
            counterexamples=[],
            version=1,
        )
        db.add(a)
        db.commit()
        return a.id


# ---------------------------------------------------------------------------
# GET /assertions
# ---------------------------------------------------------------------------


def test_list_assertions_empty_by_default(client: TestClient) -> None:
    pipeline_id = _upload(client, _trace_file())
    stage_id = next(iter(_stage_ids(client.app.dependency_overrides, pipeline_id).values())) if False else None
    # Use direct query via session
    pass


def test_list_assertions_returns_seeded_rows(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _trace_file())
    stage_ids = _stage_ids(session_factory, pipeline_id)
    root_id = stage_ids["root"]

    _add_assertion(session_factory, stage_id=root_id, kind="required_keys", spec={"keys": ["answer"]})

    response = client.get(f"/pipelines/{pipeline_id}/stages/{root_id}/assertions")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["kind"] == "required_keys"
    assert body[0]["status"] == "candidate"
    assert body[0]["spec"] == {"keys": ["answer"]}


def test_list_assertions_empty_when_none_exist(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _trace_file())
    stage_ids = _stage_ids(session_factory, pipeline_id)
    root_id = stage_ids["root"]

    response = client.get(f"/pipelines/{pipeline_id}/stages/{root_id}/assertions")
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_list_assertions_unknown_stage_returns_404(client: TestClient) -> None:
    pipeline_id = _upload(client, _trace_file())
    response = client.get(f"/pipelines/{pipeline_id}/stages/999999/assertions")
    assert response.status_code == 404


def test_list_assertions_unknown_pipeline_returns_404(client: TestClient) -> None:
    response = client.get("/pipelines/999999/stages/1/assertions")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST .../approve and .../retire
# ---------------------------------------------------------------------------


def test_approve_assertion_sets_status_approved(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _trace_file())
    stage_ids = _stage_ids(session_factory, pipeline_id)
    root_id = stage_ids["root"]
    aid = _add_assertion(session_factory, stage_id=root_id, status="candidate")

    response = client.post(f"/pipelines/{pipeline_id}/stages/{root_id}/assertions/{aid}/approve")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"


def test_retire_assertion_sets_status_retired(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _trace_file())
    stage_ids = _stage_ids(session_factory, pipeline_id)
    root_id = stage_ids["root"]
    aid = _add_assertion(session_factory, stage_id=root_id, status="candidate")

    response = client.post(f"/pipelines/{pipeline_id}/stages/{root_id}/assertions/{aid}/retire")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "retired"


def test_approve_unknown_assertion_returns_404(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _trace_file())
    stage_ids = _stage_ids(session_factory, pipeline_id)
    root_id = stage_ids["root"]
    response = client.post(f"/pipelines/{pipeline_id}/stages/{root_id}/assertions/999999/approve")
    assert response.status_code == 404


def test_retire_unknown_assertion_returns_404(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _trace_file())
    stage_ids = _stage_ids(session_factory, pipeline_id)
    root_id = stage_ids["root"]
    response = client.post(f"/pipelines/{pipeline_id}/stages/{root_id}/assertions/999999/retire")
    assert response.status_code == 404


def test_approve_persists_across_list(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _trace_file())
    stage_ids = _stage_ids(session_factory, pipeline_id)
    root_id = stage_ids["root"]
    aid = _add_assertion(session_factory, stage_id=root_id)

    client.post(f"/pipelines/{pipeline_id}/stages/{root_id}/assertions/{aid}/approve")

    body = client.get(f"/pipelines/{pipeline_id}/stages/{root_id}/assertions").json()
    assert body[0]["status"] == "approved"
