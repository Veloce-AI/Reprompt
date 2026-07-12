"""Tests for GET /pipelines/{id}/models, POST /pipelines/{id}/migrations,
GET /pipelines/{id}/migrations.

Same TestClient + in-memory SQLite pattern as test_pipelines.py/test_rubrics.py.
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

from refract_api import models
from refract_api.db import get_db
from refract_api.main import app
from refract_api.models import Base


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


def _stage_ids(session_factory: sessionmaker, pipeline_id: int) -> dict[str, int]:
    """source_id -> db id, for building per-stage overrides in tests."""
    with session_factory() as db:
        stages = db.query(models.Stage).filter(models.Stage.pipeline_id == pipeline_id).all()
        return {s.source_id: s.id for s in stages}


# ---------------------------------------------------------------------------
# GET /pipelines/{id}/models
# ---------------------------------------------------------------------------


def test_list_model_options_returns_curated_list_with_registry_facts(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.get(f"/pipelines/{pipeline_id}/models")
    assert response.status_code == 200
    options = response.json()
    assert len(options) > 0

    model_names = {o["model"] for o in options}
    assert "gpt-4o" in model_names
    assert "gpt-4o-mini" in model_names

    gpt4o = next(o for o in options if o["model"] == "gpt-4o")
    assert gpt4o["input_cost_per_1m"] is not None
    assert gpt4o["input_cost_per_1m"] > 0
    assert gpt4o["max_input_tokens"] is not None
    assert gpt4o["requires_api_key"] is True

    # Local/open options never require a credential.
    ollama = next((o for o in options if o["model"].startswith("ollama/")), None)
    assert ollama is not None
    assert ollama["requires_api_key"] is False


def test_list_model_options_unknown_pipeline_returns_404(client: TestClient) -> None:
    response = client.get("/pipelines/999999/models")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /pipelines/{id}/migrations
# ---------------------------------------------------------------------------


def test_create_migration_bulk_only_config(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={
            "target_model_config": {"default": "gpt-4o-mini"},
            "budget": 25.0,
            "parity_threshold": 0.9,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["pipeline_id"] == pipeline_id
    assert body["target_model_config"] == {"default": "gpt-4o-mini", "stages": {}}
    assert body["budget"] == 25.0
    assert body["parity_threshold"] == 0.9
    assert body["status"] == "pending"
    assert isinstance(body["id"], int)


def test_create_migration_defaults_parity_threshold_to_95_percent(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={"target_model_config": {"default": "gpt-4o-mini"}, "budget": 10.0},
    )
    assert response.status_code == 201, response.text
    assert response.json()["parity_threshold"] == 0.95


def test_create_migration_with_per_stage_overrides(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    stage_ids = _stage_ids(session_factory, pipeline_id)

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={
            "target_model_config": {
                "default": "gpt-4o-mini",
                "stages": {str(stage_ids["b"]): "claude-haiku-4-5"},
            },
            "budget": 50.0,
            "parity_threshold": 0.95,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["target_model_config"] == {
        "default": "gpt-4o-mini",
        "stages": {str(stage_ids["b"]): "claude-haiku-4-5"},
    }


def test_create_migration_rejects_stage_override_from_different_pipeline(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_a = _upload(client, _diamond_trace_file())
    pipeline_b = _upload(client, _diamond_trace_file())
    stage_ids_b = _stage_ids(session_factory, pipeline_b)

    response = client.post(
        f"/pipelines/{pipeline_a}/migrations",
        json={
            "target_model_config": {
                "default": "gpt-4o-mini",
                "stages": {str(stage_ids_b["root"]): "claude-haiku-4-5"},
            },
            "budget": 50.0,
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert str(stage_ids_b["root"]) in detail
    assert f"pipeline {pipeline_a}" in detail

    # Nothing was persisted.
    listing = client.get(f"/pipelines/{pipeline_a}/migrations").json()
    assert listing == []


def test_create_migration_rejects_unknown_stage_id(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={
            "target_model_config": {"default": "gpt-4o-mini", "stages": {"999999": "gpt-4o"}},
            "budget": 10.0,
        },
    )
    assert response.status_code == 422
    assert "999999" in response.json()["detail"]


def test_create_migration_rejects_zero_or_negative_budget(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    for bad_budget in (0, -5.0):
        response = client.post(
            f"/pipelines/{pipeline_id}/migrations",
            json={"target_model_config": {"default": "gpt-4o-mini"}, "budget": bad_budget},
        )
        assert response.status_code == 422


def test_create_migration_rejects_out_of_range_parity_threshold(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    for bad_threshold in (-0.1, 1.5):
        response = client.post(
            f"/pipelines/{pipeline_id}/migrations",
            json={
                "target_model_config": {"default": "gpt-4o-mini"},
                "budget": 10.0,
                "parity_threshold": bad_threshold,
            },
        )
        assert response.status_code == 422


def test_create_migration_rejects_blank_default_model(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={"target_model_config": {"default": ""}, "budget": 10.0},
    )
    assert response.status_code == 422


def test_create_migration_unknown_pipeline_returns_404(client: TestClient) -> None:
    response = client.post(
        "/pipelines/999999/migrations",
        json={"target_model_config": {"default": "gpt-4o-mini"}, "budget": 10.0},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /pipelines/{id}/migrations
# ---------------------------------------------------------------------------


def test_list_migrations_returns_empty_before_any_created(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.get(f"/pipelines/{pipeline_id}/migrations")
    assert response.status_code == 200
    assert response.json() == []


def test_list_migrations_returns_created_migrations_in_order(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    for budget in (10.0, 20.0):
        client.post(
            f"/pipelines/{pipeline_id}/migrations",
            json={"target_model_config": {"default": "gpt-4o-mini"}, "budget": budget},
        )

    response = client.get(f"/pipelines/{pipeline_id}/migrations")
    assert response.status_code == 200
    budgets = [m["budget"] for m in response.json()]
    assert budgets == [10.0, 20.0]


def test_list_migrations_unknown_pipeline_returns_404(client: TestClient) -> None:
    response = client.get("/pipelines/999999/migrations")
    assert response.status_code == 404


def test_list_migrations_does_not_include_other_pipelines(client: TestClient) -> None:
    pipeline_a = _upload(client, _diamond_trace_file())
    pipeline_b = _upload(client, _diamond_trace_file())

    client.post(
        f"/pipelines/{pipeline_a}/migrations",
        json={"target_model_config": {"default": "gpt-4o-mini"}, "budget": 10.0},
    )

    listing_b = client.get(f"/pipelines/{pipeline_b}/migrations").json()
    assert listing_b == []


# ---------------------------------------------------------------------------
# Helpers shared by start / status tests
# ---------------------------------------------------------------------------


def _create_migration(client: TestClient, pipeline_id: int) -> int:
    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={"target_model_config": {"default": "gpt-4o-mini"}, "budget": 10.0},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _seed_rubric(
    session_factory: sessionmaker,
    stage_id: int,
    *,
    approved: bool = True,
) -> None:
    """Insert a Rubric row directly — generate-rubric requires a real BYOK
    key, so tests seed rubrics via the DB layer instead."""
    with session_factory() as db:
        rubric = models.Rubric(
            stage_id=stage_id,
            deterministic_checks=[],
            judge_criteria=[],
            downstream_contract=[],
            approved=approved,
        )
        db.add(rubric)
        db.commit()


# ---------------------------------------------------------------------------
# POST /pipelines/{id}/migrations/{id}/start
# ---------------------------------------------------------------------------


def test_start_blocked_when_rubric_not_approved(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)
    stage_ids = _stage_ids(session_factory, pipeline_id)

    # Approve three stages but deliberately leave "root" unapproved.
    _seed_rubric(session_factory, stage_ids["root"], approved=False)
    for src in ("a", "b", "join"):
        _seed_rubric(session_factory, stage_ids[src], approved=True)

    response = client.post(f"/pipelines/{pipeline_id}/migrations/{migration_id}/start")
    assert response.status_code == 422
    # Error must name the stage by name (human-readable), not just its DB id.
    assert "Root" in response.json()["detail"]


def test_start_blocked_when_rubric_missing_entirely(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)
    # No rubrics seeded — all 4 stages must appear in the 422.

    response = client.post(f"/pipelines/{pipeline_id}/migrations/{migration_id}/start")
    assert response.status_code == 422
    detail = response.json()["detail"]
    for name in ("Root", "Branch A", "Branch B", "Join"):
        assert name in detail, f"Expected stage name '{name}' in error detail: {detail}"


def test_start_happy_path_sets_running_and_schedules_task(
    client: TestClient, session_factory: sessionmaker
) -> None:
    from unittest.mock import MagicMock, patch

    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)
    stage_ids = _stage_ids(session_factory, pipeline_id)

    for stage_id in stage_ids.values():
        _seed_rubric(session_factory, stage_id, approved=True)

    mock_runner = MagicMock()
    with patch("refract_api.migrations.run_optimizer_for_migration", mock_runner):
        response = client.post(f"/pipelines/{pipeline_id}/migrations/{migration_id}/start")

    assert response.status_code == 200, response.text
    body = response.json()
    # Status must be "running" in the response — set before add_task so a
    # poll immediately after /start never sees a stale "pending".
    assert body["status"] == "running"
    assert body["id"] == migration_id
    # TestClient runs BackgroundTasks synchronously before returning, so the
    # mock is already called by the time we check it here.
    mock_runner.assert_called_once_with(migration_id)


def test_start_unknown_migration_returns_404(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    response = client.post(f"/pipelines/{pipeline_id}/migrations/999999/start")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /pipelines/{id}/migrations/{id}/status
# ---------------------------------------------------------------------------


def test_status_reflects_progress_fields(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)

    # Simulate what the background task writes mid-run.
    with session_factory() as db:
        migration = db.get(models.Migration, migration_id)
        migration.status = "running"
        migration.progress_stage_name = "Branch A"
        migration.progress_current = 1
        migration.progress_total = 4
        db.commit()

    response = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id}/status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "running"
    assert body["progress_stage_name"] == "Branch A"
    assert body["progress_current"] == 1
    assert body["progress_total"] == 4


def test_status_reflects_terminal_states(
    client: TestClient, session_factory: sessionmaker
) -> None:
    import datetime

    pipeline_id = _upload(client, _diamond_trace_file())
    completed_at = datetime.datetime(2026, 7, 12, 10, 0, 0, tzinfo=datetime.timezone.utc)

    # --- completed ---
    migration_id = _create_migration(client, pipeline_id)
    with session_factory() as db:
        m = db.get(models.Migration, migration_id)
        m.status = "completed"
        m.total_cost_usd = 1.23
        m.stopped_early = False
        m.completed_at = completed_at
        db.commit()

    body = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id}/status").json()
    assert body["status"] == "completed"
    assert abs(body["total_cost_usd"] - 1.23) < 1e-6
    assert body["stopped_early"] is False
    assert body["completed_at"] is not None

    # --- failed ---
    migration_id_2 = _create_migration(client, pipeline_id)
    with session_factory() as db:
        m = db.get(models.Migration, migration_id_2)
        m.status = "failed"
        m.stop_reason = "No workspace found"
        m.completed_at = completed_at
        db.commit()

    body = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id_2}/status").json()
    assert body["status"] == "failed"
    assert body["stop_reason"] == "No workspace found"
    assert body["completed_at"] is not None


def test_status_unknown_migration_returns_404(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    response = client.get(f"/pipelines/{pipeline_id}/migrations/999999/status")
    assert response.status_code == 404
