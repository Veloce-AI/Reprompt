"""Tests for GET /pipelines/{id}/rubrics, PATCH /rubrics/{id},
POST /rubrics/{id}/approve, POST /pipelines/{id}/rubrics/approve-all.

Same TestClient + in-memory SQLite pattern as test_pipelines.py. Rubric rows
are created via reprompt_api.seed_rubrics (the dev/test seed helper, since
there's no rubric generator yet) rather than hand-rolled here, so these
tests exercise the exact same seed data path used to build the UI against.
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
from reprompt_api.seed_rubrics import seed_rubrics_for_pipeline


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
    """root -> {a, b in parallel} -> join, with one trace covering all 4 stages.

    Duplicated from test_pipelines.py deliberately (small, self-contained
    per test module - same convention as that file).
    """
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


def _upload(client: TestClient, trace_file: TraceFile) -> int:
    payload = trace_file.model_dump(by_alias=True)
    response = client.post(
        "/pipelines/import",
        files={"file": ("trace.json", json.dumps(payload), "application/json")},
    )
    assert response.status_code == 201, response.text
    return response.json()["pipeline_id"]


def _seed(session_factory: sessionmaker, pipeline_id: int, *, stage_ids: list[int] | None = None) -> list[int]:
    """Seed rubrics via the real helper, in its own session (mirrors how a
    standalone `uv run python -m reprompt_api.seed_rubrics` invocation or a
    pytest fixture would do it - a separate connection from the TestClient's
    request-scoped sessions, same DB file/engine underneath).
    """
    with session_factory() as db:
        pipeline = db.get(models.Pipeline, pipeline_id)
        rubrics = seed_rubrics_for_pipeline(db, pipeline, stage_ids=stage_ids)
        return [r.id for r in rubrics]


def test_list_rubrics_returns_empty_before_any_seed(client: TestClient, session_factory: sessionmaker) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.get(f"/pipelines/{pipeline_id}/rubrics")
    assert response.status_code == 200
    assert response.json() == []


def test_list_rubrics_unknown_pipeline_returns_404(client: TestClient) -> None:
    response = client.get("/pipelines/999999/rubrics")
    assert response.status_code == 404


def test_list_rubrics_groups_by_stage_with_real_check_shapes(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    _seed(session_factory, pipeline_id)  # seeds all 4 stages

    response = client.get(f"/pipelines/{pipeline_id}/rubrics")
    assert response.status_code == 200
    rubrics = response.json()
    assert len(rubrics) == 4

    stage_names = {r["stage_name"] for r in rubrics}
    assert stage_names == {"Root", "Branch A", "Branch B", "Join"}

    first = rubrics[0]
    assert first["approved"] is False
    check_types = {c["type"] for c in first["deterministic_checks"]}
    assert check_types == {"required_keys", "length_bounds"}
    required_keys_check = next(c for c in first["deterministic_checks"] if c["type"] == "required_keys")
    assert required_keys_check["keys"] == ["currency", "revenue"]

    criteria_names = {c["name"] for c in first["judge_criteria"]}
    assert "Covers all key entities" in criteria_names
    assert first["downstream_contract"] == ["currency", "revenue"]


def test_patch_rubric_replaces_deterministic_checks(client: TestClient, session_factory: sessionmaker) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    rubric_ids = _seed(session_factory, pipeline_id)
    rubric_id = rubric_ids[0]

    new_checks = [
        {"type": "required_keys", "id": "req-1", "keys": ["order_id"]},
    ]
    response = client.patch(f"/rubrics/{rubric_id}", json={"deterministic_checks": new_checks})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["deterministic_checks"]) == 1
    assert body["deterministic_checks"][0]["keys"] == ["order_id"]
    # Untouched fields are left alone by a partial update.
    assert len(body["judge_criteria"]) == 2
    assert body["downstream_contract"] == ["currency", "revenue"]


def test_patch_rubric_rejects_invalid_deterministic_check_shape(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    rubric_ids = _seed(session_factory, pipeline_id)
    rubric_id = rubric_ids[0]

    bad_checks = [{"type": "required_keys"}]  # missing required `keys`
    response = client.patch(f"/rubrics/{rubric_id}", json={"deterministic_checks": bad_checks})
    assert response.status_code == 422

    # Nothing was persisted - a follow-up GET still shows the original data.
    get_response = client.get(f"/pipelines/{pipeline_id}/rubrics")
    matching = next(r for r in get_response.json() if r["id"] == rubric_id)
    assert len(matching["deterministic_checks"]) == 2


def test_patch_rubric_rejects_unknown_check_type(client: TestClient, session_factory: sessionmaker) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    rubric_ids = _seed(session_factory, pipeline_id)

    response = client.patch(
        f"/rubrics/{rubric_ids[0]}",
        json={"deterministic_checks": [{"type": "not_a_real_check_type"}]},
    )
    assert response.status_code == 422


def test_patch_rubric_updates_judge_criteria_and_downstream_contract(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    rubric_ids = _seed(session_factory, pipeline_id)

    response = client.patch(
        f"/rubrics/{rubric_ids[0]}",
        json={
            "judge_criteria": [{"name": "No hedging language", "weight": 1.0, "description": "..."}],
            "downstream_contract": ["order_id", "status"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["judge_criteria"] == [
        {"name": "No hedging language", "weight": 1.0, "description": "..."}
    ]
    assert body["downstream_contract"] == ["order_id", "status"]


def test_patch_rubric_rejects_blank_downstream_contract_field(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    rubric_ids = _seed(session_factory, pipeline_id)

    response = client.patch(
        f"/rubrics/{rubric_ids[0]}",
        json={"downstream_contract": ["order_id", "  "]},
    )
    assert response.status_code == 422


def test_patch_unknown_rubric_returns_404(client: TestClient) -> None:
    response = client.patch("/rubrics/999999", json={"downstream_contract": ["x"]})
    assert response.status_code == 404


def test_approve_rubric_sets_flag(client: TestClient, session_factory: sessionmaker) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    rubric_ids = _seed(session_factory, pipeline_id)

    response = client.post(f"/rubrics/{rubric_ids[0]}/approve")
    assert response.status_code == 200
    assert response.json()["approved"] is True

    # Other rubrics for the same pipeline are untouched.
    listing = client.get(f"/pipelines/{pipeline_id}/rubrics").json()
    approved_flags = {r["id"]: r["approved"] for r in listing}
    assert approved_flags[rubric_ids[0]] is True
    assert all(approved_flags[rid] is False for rid in rubric_ids[1:])


def test_approve_unknown_rubric_returns_404(client: TestClient) -> None:
    response = client.post("/rubrics/999999/approve")
    assert response.status_code == 404


def test_approve_all_marks_every_rubric_for_pipeline(client: TestClient, session_factory: sessionmaker) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    rubric_ids = _seed(session_factory, pipeline_id)

    response = client.post(f"/pipelines/{pipeline_id}/rubrics/approve-all")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == len(rubric_ids)
    assert all(r["approved"] is True for r in body)

    listing = client.get(f"/pipelines/{pipeline_id}/rubrics").json()
    assert all(r["approved"] is True for r in listing)


def test_approve_all_unknown_pipeline_returns_404(client: TestClient) -> None:
    response = client.post("/pipelines/999999/rubrics/approve-all")
    assert response.status_code == 404


def test_approve_all_does_not_touch_other_pipelines(client: TestClient, session_factory: sessionmaker) -> None:
    pipeline_a = _upload(client, _diamond_trace_file())
    pipeline_b = _upload(client, _diamond_trace_file())
    _seed(session_factory, pipeline_a)
    _seed(session_factory, pipeline_b)

    client.post(f"/pipelines/{pipeline_a}/rubrics/approve-all")

    b_listing = client.get(f"/pipelines/{pipeline_b}/rubrics").json()
    assert all(r["approved"] is False for r in b_listing)
