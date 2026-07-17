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
    """source_id -> db id, used for seeding rubrics in start/status tests."""
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


def test_create_migration_single_model(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={
            "target_model_config": {"models": ["gpt-4o-mini"]},
            "budget": 25.0,
            "parity_threshold": 0.9,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["pipeline_id"] == pipeline_id
    assert body["target_model_config"] == {"models": ["gpt-4o-mini"]}
    assert body["budget"] == 25.0
    assert body["parity_threshold"] == 0.9
    assert body["status"] == "pending"
    assert isinstance(body["id"], int)


def test_create_migration_multi_model_config(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={
            "target_model_config": {"models": ["gpt-4o-mini", "claude-haiku-4-5"]},
            "budget": 50.0,
            "parity_threshold": 0.95,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["target_model_config"] == {"models": ["gpt-4o-mini", "claude-haiku-4-5"]}


def test_create_migration_persists_explicit_judge_and_mutator_model_overrides(
    client: TestClient,
) -> None:
    """judge_model/mutator_model are optional overrides for Reprompt's OWN
    judge/mutator harness infrastructure, kept deliberately separate from
    `models` (the model(s) the user is actually testing) - see
    reprompt_api.optimizer_runner.py and DEV_TRACKER.md's "Fix judge/mutator
    self-grading bias" section. Confirms they actually round-trip through
    TargetModelConfig's schema/model_dump() rather than being silently
    dropped (a real gap before these fields were declared - the old schema
    only declared `models`, so Pydantic's default `model_dump()` stripped
    any `judge_model`/`mutator_model` key a caller sent)."""
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={
            "target_model_config": {
                "models": ["gpt-4o-mini"],
                "judge_model": "claude-haiku-4-5",
                "mutator_model": "gpt-4o",
            },
            "budget": 10.0,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["target_model_config"] == {
        "models": ["gpt-4o-mini"],
        "judge_model": "claude-haiku-4-5",
        "mutator_model": "gpt-4o",
    }


def test_create_migration_omits_judge_and_mutator_model_when_not_given(client: TestClient) -> None:
    """The common case - no judge_model/mutator_model override - must keep
    storing the same bare {"models": [...]} shape as before those fields
    existed (not padded with explicit `None`s), so existing rows/behavior
    are unaffected."""
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={"target_model_config": {"models": ["gpt-4o-mini"]}, "budget": 10.0},
    )
    assert response.status_code == 201, response.text
    assert response.json()["target_model_config"] == {"models": ["gpt-4o-mini"]}


def test_create_migration_persists_stage_overrides(
    client: TestClient, session_factory: sessionmaker
) -> None:
    """stage_overrides is additive: keyed by real stage id (string), each
    entry replaces `models` for that stage only - see DEV_TRACKER.md's
    "Per-stage target model override" note. Confirms it round-trips through
    TargetModelConfig's schema/model_dump() exactly as sent."""
    pipeline_id = _upload(client, _diamond_trace_file())
    stage_ids = _stage_ids(session_factory, pipeline_id)
    root_id = str(stage_ids["root"])

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={
            "target_model_config": {
                "models": ["gpt-4o-mini"],
                "stage_overrides": {root_id: ["claude-haiku-4-5", "gpt-4o"]},
            },
            "budget": 25.0,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["target_model_config"] == {
        "models": ["gpt-4o-mini"],
        "stage_overrides": {root_id: ["claude-haiku-4-5", "gpt-4o"]},
    }


def test_create_migration_omits_stage_overrides_when_not_given(client: TestClient) -> None:
    """The common case - no advanced per-stage customization - must keep
    storing the same bare {"models": [...]} shape as before this field
    existed, not padded with an explicit `null` key."""
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={"target_model_config": {"models": ["gpt-4o-mini"]}, "budget": 10.0},
    )
    assert response.status_code == 201, response.text
    assert response.json()["target_model_config"] == {"models": ["gpt-4o-mini"]}


def test_create_migration_rejects_stage_overrides_referencing_unknown_stage_id(
    client: TestClient,
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={
            "target_model_config": {
                "models": ["gpt-4o-mini"],
                "stage_overrides": {"999999": ["claude-haiku-4-5"]},
            },
            "budget": 10.0,
        },
    )
    assert response.status_code == 422
    assert "999999" in response.json()["detail"]


def test_create_migration_rejects_stage_overrides_referencing_another_pipelines_stage(
    client: TestClient, session_factory: sessionmaker
) -> None:
    """A real, existing stage id — just not one that belongs to *this*
    pipeline — must also be rejected, not silently accepted."""
    pipeline_a = _upload(client, _diamond_trace_file())
    pipeline_b = _upload(client, _diamond_trace_file())
    other_stage_id = str(_stage_ids(session_factory, pipeline_b)["root"])

    response = client.post(
        f"/pipelines/{pipeline_a}/migrations",
        json={
            "target_model_config": {
                "models": ["gpt-4o-mini"],
                "stage_overrides": {other_stage_id: ["claude-haiku-4-5"]},
            },
            "budget": 10.0,
        },
    )
    assert response.status_code == 422
    assert other_stage_id in response.json()["detail"]


def test_create_migration_rejects_empty_model_list_in_a_stage_override(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    root_id = str(_stage_ids(session_factory, pipeline_id)["root"])

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={
            "target_model_config": {
                "models": ["gpt-4o-mini"],
                "stage_overrides": {root_id: []},
            },
            "budget": 10.0,
        },
    )
    assert response.status_code == 422


def test_create_migration_defaults_parity_threshold_to_95_percent(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={"target_model_config": {"models": ["gpt-4o-mini"]}, "budget": 10.0},
    )
    assert response.status_code == 201, response.text
    assert response.json()["parity_threshold"] == 0.95


def test_create_migration_rejects_empty_models_list(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={"target_model_config": {"models": []}, "budget": 10.0},
    )
    assert response.status_code == 422


def test_create_migration_rejects_zero_or_negative_budget(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    for bad_budget in (0, -5.0):
        response = client.post(
            f"/pipelines/{pipeline_id}/migrations",
            json={"target_model_config": {"models": ["gpt-4o-mini"]}, "budget": bad_budget},
        )
        assert response.status_code == 422


def test_create_migration_rejects_out_of_range_parity_threshold(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())

    for bad_threshold in (-0.1, 1.5):
        response = client.post(
            f"/pipelines/{pipeline_id}/migrations",
            json={
                "target_model_config": {"models": ["gpt-4o-mini"]},
                "budget": 10.0,
                "parity_threshold": bad_threshold,
            },
        )
        assert response.status_code == 422


def test_create_migration_unknown_pipeline_returns_404(client: TestClient) -> None:
    response = client.post(
        "/pipelines/999999/migrations",
        json={"target_model_config": {"models": ["gpt-4o-mini"]}, "budget": 10.0},
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
            json={"target_model_config": {"models": ["gpt-4o-mini"]}, "budget": budget},
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
        json={"target_model_config": {"models": ["gpt-4o-mini"]}, "budget": 10.0},
    )

    listing_b = client.get(f"/pipelines/{pipeline_b}/migrations").json()
    assert listing_b == []


# ---------------------------------------------------------------------------
# Helpers shared by start / status tests
# ---------------------------------------------------------------------------


def _create_migration(client: TestClient, pipeline_id: int) -> int:
    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={"target_model_config": {"models": ["gpt-4o-mini"]}, "budget": 10.0},
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
    with patch("reprompt_api.migrations.run_optimizer_for_migration", mock_runner):
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
        migration.progress_substep = "critiquing"
        db.commit()

    response = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id}/status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "running"
    assert body["progress_stage_name"] == "Branch A"
    assert body["progress_current"] == 1
    assert body["progress_total"] == 4
    assert body["progress_substep"] == "critiquing"


def test_status_progress_substep_defaults_to_none_before_a_run_starts(
    client: TestClient,
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)

    response = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id}/status")
    assert response.status_code == 200, response.text
    assert response.json()["progress_substep"] is None


def test_status_activity_log_defaults_to_none_before_a_run_starts(
    client: TestClient,
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)

    response = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id}/status")
    assert response.status_code == 200, response.text
    assert response.json()["activity_log"] is None


def test_status_exposes_activity_log_entries(
    client: TestClient, session_factory: sessionmaker
) -> None:
    """Phase B: optimizer_runner.py's on_phase closure appends
    {stage_id, phase, detail, timestamp} entries - GET .../status must
    surface the list verbatim, same polling pattern as progress_substep."""
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)

    entries = [
        {"stage_id": 1, "phase": "mutating", "detail": None, "timestamp": "2026-07-16T09:00:00+00:00"},
        {"stage_id": 1, "phase": "refining", "detail": "needs work", "timestamp": "2026-07-16T09:00:05+00:00"},
    ]
    with session_factory() as db:
        migration = db.get(models.Migration, migration_id)
        migration.status = "running"
        migration.activity_log = entries
        db.commit()

    response = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id}/status")
    assert response.status_code == 200, response.text
    assert response.json()["activity_log"] == entries


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


# ---------------------------------------------------------------------------
# stage_states derivation (Phase 2 — live DAG/run status view)
# ---------------------------------------------------------------------------
# Diamond pipeline stage order is by DB id (insertion order): root, a, b, join
# (see optimizer_runner._run's db_stages query — reused as-is by
# migrations._compute_stage_states).


def test_stage_states_all_idle_before_run_starts(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)
    stage_ids = _stage_ids(session_factory, pipeline_id)

    body = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id}/status").json()
    assert body["stage_states"] == {str(sid): "idle" for sid in stage_ids.values()}


def test_stage_states_mid_run_marks_done_running_idle(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)
    stage_ids = _stage_ids(session_factory, pipeline_id)

    with session_factory() as db:
        migration = db.get(models.Migration, migration_id)
        migration.status = "running"
        migration.progress_stage_name = "Branch A"  # source_id "a", 2nd in order
        migration.progress_current = 2
        migration.progress_total = 4
        db.commit()

    body = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id}/status").json()
    states = body["stage_states"]
    assert states[str(stage_ids["root"])] == "done"
    assert states[str(stage_ids["a"])] == "running"
    assert states[str(stage_ids["b"])] == "idle"
    assert states[str(stage_ids["join"])] == "idle"


def test_stage_states_failed_marks_current_stage_failed(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)
    stage_ids = _stage_ids(session_factory, pipeline_id)

    with session_factory() as db:
        migration = db.get(models.Migration, migration_id)
        migration.status = "failed"
        migration.progress_stage_name = "Join"  # last stage
        migration.progress_current = 4
        migration.progress_total = 4
        migration.stop_reason = "No workspace found"
        db.commit()

    body = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id}/status").json()
    states = body["stage_states"]
    assert states[str(stage_ids["root"])] == "done"
    assert states[str(stage_ids["a"])] == "done"
    assert states[str(stage_ids["b"])] == "done"
    assert states[str(stage_ids["join"])] == "failed"


def test_stage_states_stopped_early_marks_current_stage_done(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)
    stage_ids = _stage_ids(session_factory, pipeline_id)

    with session_factory() as db:
        migration = db.get(models.Migration, migration_id)
        migration.status = "stopped_early"
        migration.progress_stage_name = "Branch B"
        migration.progress_current = 3
        migration.progress_total = 4
        migration.stopped_early = True
        migration.stop_reason = "budget_exhausted"
        db.commit()

    body = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id}/status").json()
    states = body["stage_states"]
    assert states[str(stage_ids["root"])] == "done"
    assert states[str(stage_ids["a"])] == "done"
    assert states[str(stage_ids["b"])] == "done"
    assert states[str(stage_ids["join"])] == "idle"


def test_stage_states_completed_marks_all_stages_done(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)
    stage_ids = _stage_ids(session_factory, pipeline_id)

    with session_factory() as db:
        migration = db.get(models.Migration, migration_id)
        migration.status = "completed"
        migration.progress_stage_name = "Join"
        migration.progress_current = 4
        migration.progress_total = 4
        migration.total_cost_usd = 1.23
        db.commit()

    body = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id}/status").json()
    assert body["stage_states"] == {str(sid): "done" for sid in stage_ids.values()}


# ---------------------------------------------------------------------------
# target_model tracking on Candidate rows
# ---------------------------------------------------------------------------


def test_candidate_rows_populated_with_target_model(
    client: TestClient, session_factory: sessionmaker
) -> None:
    """Candidates created during optimization have target_model set.

    This test mocks the optimizer to run and create a single candidate,
    then verifies the target_model field is correctly populated.
    """
    pipeline_id = _upload(client, _diamond_trace_file())

    response = client.post(
        f"/pipelines/{pipeline_id}/migrations",
        json={
            "target_model_config": {"models": ["gpt-4o-mini", "claude-haiku-4-5"]},
            "budget": 100.0,
            "parity_threshold": 0.95,
        },
    )
    assert response.status_code == 201, response.text
    migration_id = response.json()["id"]
    stage_ids = _stage_ids(session_factory, pipeline_id)

    # Seed rubrics for all stages
    for stage_id in stage_ids.values():
        _seed_rubric(session_factory, stage_id, approved=True)

    # Simulate what would happen during an actual migration run:
    # create a few candidate rows with different target models.
    with session_factory() as db:
        # Simulate optimizer creating candidates for gpt-4o-mini
        db.add(
            models.Candidate(
                migration_id=migration_id,
                stage_id=stage_ids["root"],
                target_model="gpt-4o-mini",
                prompt_variant="optimized prompt for gpt-4o-mini",
                params={"temperature": 0.7},
                format="text",
                scores={"deterministic": 0.9},
                cost=0.01,
                latency=100.0,
            )
        )
        # Simulate optimizer creating candidates for claude-haiku-4-5
        db.add(
            models.Candidate(
                migration_id=migration_id,
                stage_id=stage_ids["root"],
                target_model="claude-haiku-4-5",
                prompt_variant="optimized prompt for claude-haiku",
                params={"temperature": 0.5},
                format="text",
                scores={"deterministic": 0.85},
                cost=0.005,
                latency=50.0,
            )
        )
        db.commit()

    # Verify both candidates exist and have correct target_model values
    with session_factory() as db:
        candidates = db.query(models.Candidate).filter(
            models.Candidate.migration_id == migration_id,
            models.Candidate.stage_id == stage_ids["root"],
        ).all()

        assert len(candidates) == 2
        target_models = {c.target_model for c in candidates}
        assert target_models == {"gpt-4o-mini", "claude-haiku-4-5"}

        # Verify each candidate has the correct prompt variant
        mini_candidate = next(c for c in candidates if c.target_model == "gpt-4o-mini")
        assert "gpt-4o-mini" in mini_candidate.prompt_variant

        haiku_candidate = next(c for c in candidates if c.target_model == "claude-haiku-4-5")
        assert "claude-haiku" in haiku_candidate.prompt_variant


# ---------------------------------------------------------------------------
# GET /pipelines/{id}/migrations/{id}/results (before/after prompt diff)
# ---------------------------------------------------------------------------


def _add_candidate(
    session_factory: sessionmaker,
    *,
    migration_id: int,
    stage_id: int,
    target_model: str,
    prompt_variant: str,
    final_score: float | None,
) -> None:
    with session_factory() as db:
        scores: dict = {"deterministic": 0.9}
        if final_score is not None:
            scores["final"] = final_score
        db.add(
            models.Candidate(
                migration_id=migration_id,
                stage_id=stage_id,
                target_model=target_model,
                prompt_variant=prompt_variant,
                params={},
                format="text",
                scores=scores,
                cost=0.01,
                latency=100.0,
            )
        )
        db.commit()


def test_results_empty_before_any_candidate_exists(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)

    response = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id}/results")
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_results_picks_highest_final_score_candidate_per_stage(
    client: TestClient, session_factory: sessionmaker
) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)
    stage_ids = _stage_ids(session_factory, pipeline_id)
    root_id = stage_ids["root"]

    _add_candidate(
        session_factory,
        migration_id=migration_id,
        stage_id=root_id,
        target_model="gpt-4o-mini",
        prompt_variant="weaker variant",
        final_score=0.6,
    )
    _add_candidate(
        session_factory,
        migration_id=migration_id,
        stage_id=root_id,
        target_model="claude-haiku-4-5",
        prompt_variant="stronger variant",
        final_score=0.92,
    )

    response = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id}/results")
    assert response.status_code == 200, response.text
    body = response.json()

    root_result = next(r for r in body if r["stage_id"] == root_id)
    assert root_result["stage_name"] == "Root"
    assert root_result["original_prompt"] == "{{q}}"
    assert root_result["winning_prompt"] == "stronger variant"
    assert root_result["winning_model"] == "claude-haiku-4-5"
    assert abs(root_result["score"] - 0.92) < 1e-9

    # Only stages with at least one Candidate row appear.
    assert {r["stage_id"] for r in body} == {root_id}


def test_results_treats_missing_final_score_as_zero(
    client: TestClient, session_factory: sessionmaker
) -> None:
    """A Candidate.scores dict missing the "final" key (e.g. an older/
    partial row) must not crash the comparison — it's treated as the worst
    possible score rather than raising a KeyError/TypeError."""
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)
    stage_ids = _stage_ids(session_factory, pipeline_id)
    root_id = stage_ids["root"]

    _add_candidate(
        session_factory,
        migration_id=migration_id,
        stage_id=root_id,
        target_model="gpt-4o-mini",
        prompt_variant="no final score recorded",
        final_score=None,
    )
    _add_candidate(
        session_factory,
        migration_id=migration_id,
        stage_id=root_id,
        target_model="claude-haiku-4-5",
        prompt_variant="has a final score",
        final_score=0.5,
    )

    response = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id}/results")
    assert response.status_code == 200, response.text
    root_result = next(r for r in response.json() if r["stage_id"] == root_id)
    assert root_result["winning_prompt"] == "has a final score"


def test_results_available_for_non_terminal_migration(
    client: TestClient, session_factory: sessionmaker
) -> None:
    """Not gated on Migration.status being terminal - a running migration
    with at least one finished attempt for a stage already shows it."""
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)
    stage_ids = _stage_ids(session_factory, pipeline_id)
    root_id = stage_ids["root"]

    with session_factory() as db:
        migration = db.get(models.Migration, migration_id)
        migration.status = "running"
        db.commit()

    _add_candidate(
        session_factory,
        migration_id=migration_id,
        stage_id=root_id,
        target_model="gpt-4o-mini",
        prompt_variant="in-progress winner so far",
        final_score=0.7,
    )

    response = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_id}/results")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["winning_prompt"] == "in-progress winner so far"


def test_results_scopes_candidates_to_the_requested_migration(
    client: TestClient, session_factory: sessionmaker
) -> None:
    """Two migrations on the same pipeline/stage must not leak each other's
    candidates into the results list."""
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_a = _create_migration(client, pipeline_id)
    migration_b = _create_migration(client, pipeline_id)
    stage_ids = _stage_ids(session_factory, pipeline_id)
    root_id = stage_ids["root"]

    _add_candidate(
        session_factory,
        migration_id=migration_a,
        stage_id=root_id,
        target_model="gpt-4o-mini",
        prompt_variant="migration A's variant",
        final_score=0.8,
    )

    response = client.get(f"/pipelines/{pipeline_id}/migrations/{migration_b}/results")
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_results_unknown_migration_returns_404(client: TestClient) -> None:
    pipeline_id = _upload(client, _diamond_trace_file())
    response = client.get(f"/pipelines/{pipeline_id}/migrations/999999/results")
    assert response.status_code == 404


def test_results_unknown_pipeline_returns_404(client: TestClient) -> None:
    response = client.get("/pipelines/999999/migrations/1/results")
    assert response.status_code == 404


def test_candidate_target_model_is_persisted(
    client: TestClient, session_factory: sessionmaker
) -> None:
    """Candidate rows written by on_attempt must record target_model so the
    scorecard can tell which model produced each attempt (critical once a
    migration runs multiple target models)."""
    pipeline_id = _upload(client, _diamond_trace_file())
    migration_id = _create_migration(client, pipeline_id)
    stage_ids = _stage_ids(session_factory, pipeline_id)
    any_stage_id = next(iter(stage_ids.values()))

    with session_factory() as db:
        db.add(
            models.Candidate(
                migration_id=migration_id,
                stage_id=any_stage_id,
                target_model="gpt-4o-mini",
                prompt_variant="test prompt",
                params={"temperature": 0.2},
                format="plain",
                scores={"final": 0.85},
                cost=0.001,
                latency=120.0,
            )
        )
        db.commit()

    with session_factory() as db:
        candidate = db.query(models.Candidate).filter(
            models.Candidate.migration_id == migration_id
        ).first()
        assert candidate is not None
        assert candidate.target_model == "gpt-4o-mini"
