"""Tests for reprompt_api.optimizer_runner's on_phase closure — Phase B's
activity_log persistence/capping (see DEV_TRACKER.md's "Phase B — Live
reasoning feed + activity log").

Monkeypatches ``reprompt_api.optimizer_runner.run_optimizer`` (imported into
that module's own namespace, same as every other name it imports from
``reprompt_core``) with a fake that fires a caller-controlled sequence of
``StagePhaseEvent``s through the real ``on_phase``/``on_attempt`` closures —
same "swap the engine call, keep the DB-wiring shell real" split
``test_llm_context.py`` uses for ``complete_with_workspace_credentials``.
No real LLM call, no full sweep/scoring machinery needed to test this
plumbing.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from reprompt_core.optimizer.loop import OptimizationResult, StagePhaseEvent, StageResult

from reprompt_api import models
from reprompt_api.models import Base
from reprompt_api.optimizer_runner import MAX_ACTIVITY_LOG_ENTRIES, run_optimizer_for_migration


@pytest.fixture()
def session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _make_workspace(db: Session) -> models.Workspace:
    user = models.User(email="owner@example.com")
    db.add(user)
    db.flush()
    workspace = models.Workspace(name="Test Workspace", owner_user_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


def _make_migration_with_one_stage(db: Session) -> tuple[int, int]:
    """Minimal pipeline: one stage with one benchmark record - just enough
    for _build_stage_inputs to produce a non-empty stage list (a stage with
    no benchmark records is silently skipped, never reaching run_optimizer
    at all - see optimizer_runner._build_stage_inputs)."""
    pipeline = models.Pipeline(name="Test Pipeline")
    db.add(pipeline)
    db.flush()

    stage = models.Stage(
        pipeline_id=pipeline.id,
        source_id="root",
        name="Root",
        model="gpt-4o",
        prompt_template="{{q}}",
        params={},
    )
    db.add(stage)
    db.flush()

    benchmark_set = models.BenchmarkSet(pipeline_id=pipeline.id, name="benchmark")
    db.add(benchmark_set)
    db.flush()

    trace = models.Trace(
        benchmark_set_id=benchmark_set.id, source_trace_id="t1", query={"q": "hi"}, query_index=0
    )
    db.add(trace)
    db.flush()

    db.add(
        models.StageRecord(
            stage_id=stage.id, trace_id=trace.id, input={"q": "hi"}, rendered_prompt="prompt", output="out",
        )
    )

    migration = models.Migration(
        pipeline_id=pipeline.id,
        target_model_config={"models": ["gpt-4o-mini"]},
        budget=10.0,
        parity_threshold=0.95,
        status="running",
    )
    db.add(migration)
    db.commit()
    db.refresh(migration)
    return pipeline.id, migration.id


def _fake_run_optimizer(events: list[StagePhaseEvent]):
    """Returns a fake matching run_optimizer's signature that fires `events`
    through the real on_phase closure, then reports one no-op StageResult."""

    def fake(stages, *, call, budget, judge_model, strategy, parity_threshold, on_attempt=None, on_phase=None, **_kw):
        for event in events:
            if on_phase is not None:
                on_phase(event)
        return OptimizationResult(
            stage_results=[
                StageResult(
                    stage_id=stages[0].stage_id, best=None, attempts_tried=0,
                    met_threshold=False, selection_reason="test",
                )
            ],
            total_cost_usd=0.0,
            stopped_early=False,
            stop_reason=None,
        )

    return fake


@pytest.fixture()
def client(session_factory: sessionmaker) -> Iterator[None]:
    """No FastAPI TestClient needed here - run_optimizer_for_migration opens
    its own SessionLocal(), so patch db.SessionLocal to reuse this test's
    in-memory engine instead of hitting a real DB file."""
    with patch("reprompt_api.optimizer_runner.SessionLocal", session_factory):
        yield


def test_on_phase_appends_events_to_activity_log(client: None, session_factory: sessionmaker) -> None:
    with session_factory() as db:
        _make_workspace(db)
        pipeline_id, migration_id = _make_migration_with_one_stage(db)

    events = [
        StagePhaseEvent(stage_id=1, phase="mutating"),
        StagePhaseEvent(stage_id=1, phase="critiquing"),
        StagePhaseEvent(stage_id=1, phase="refining", detail="needs work"),
    ]
    with patch("reprompt_api.optimizer_runner.run_optimizer", _fake_run_optimizer(events)):
        run_optimizer_for_migration(migration_id)

    with session_factory() as db:
        migration = db.get(models.Migration, migration_id)
        log = migration.activity_log

    assert log is not None
    assert len(log) == 3
    assert log[0]["phase"] == "mutating"
    assert log[0]["detail"] is None
    assert log[2]["phase"] == "refining"
    assert log[2]["detail"] == "needs work"
    for entry in log:
        assert set(entry.keys()) == {"stage_id", "phase", "detail", "timestamp"}
        assert entry["timestamp"]  # non-empty ISO string


def test_activity_log_is_capped_at_max_entries_keeping_the_most_recent(
    client: None, session_factory: sessionmaker
) -> None:
    with session_factory() as db:
        _make_workspace(db)
        pipeline_id, migration_id = _make_migration_with_one_stage(db)

    total_events = MAX_ACTIVITY_LOG_ENTRIES + 20
    events = [
        StagePhaseEvent(stage_id=1, phase="mutating", detail=f"event {i}")
        for i in range(total_events)
    ]
    with patch("reprompt_api.optimizer_runner.run_optimizer", _fake_run_optimizer(events)):
        run_optimizer_for_migration(migration_id)

    with session_factory() as db:
        migration = db.get(models.Migration, migration_id)
        log = migration.activity_log

    assert log is not None
    assert len(log) == MAX_ACTIVITY_LOG_ENTRIES
    # The oldest 20 events were dropped from the front - the log starts at
    # "event 20" and ends at the very last event fired.
    assert log[0]["detail"] == "event 20"
    assert log[-1]["detail"] == f"event {total_events - 1}"
