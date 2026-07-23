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

from reprompt_core.optimizer.loop import (
    OptimizationResult,
    StageAttempt,
    StagePhaseEvent,
    StageResult,
)

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


def _make_migration_with_one_stage(
    db: Session, *, target_model_config: dict | None = None
) -> tuple[int, int]:
    """Minimal pipeline: one stage with one benchmark record - just enough
    for _build_stage_inputs to produce a non-empty stage list (a stage with
    no benchmark records is silently skipped, never reaching run_optimizer
    at all - see optimizer_runner._build_stage_inputs).

    ``target_model_config`` defaults to the original single-target shape
    every pre-existing test in this file relies on; pass an explicit dict
    (e.g. with a ``judge_model``/``mutator_model`` override, or a
    deliberately "weak" target model) for the judge/mutator selection
    tests below."""
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
        target_model_config=target_model_config or {"models": ["gpt-4o-mini"]},
        budget=10.0,
        parity_threshold=0.95,
        status="running",
    )
    db.add(migration)
    db.commit()
    db.refresh(migration)
    return pipeline.id, migration.id


def _make_two_stage_pipeline(db: Session) -> tuple[int, dict[str, int]]:
    """Two independent stages (no DAG edges needed for this), each with one
    benchmark record - enough for _build_stage_inputs to produce a
    non-empty stage list for both. Split from a migration-creation helper
    (unlike _make_migration_with_one_stage) because the per-stage-override
    tests below need real stage ids *before* they can build
    target_model_config. Returns (pipeline_id, {source_id: stage.id})."""
    pipeline = models.Pipeline(name="Test Pipeline")
    db.add(pipeline)
    db.flush()

    stage_ids: dict[str, int] = {}
    for source_id, name in (("root", "Root"), ("second", "Second")):
        stage = models.Stage(
            pipeline_id=pipeline.id,
            source_id=source_id,
            name=name,
            model="gpt-4o",
            prompt_template="{{q}}",
            params={},
        )
        db.add(stage)
        db.flush()
        stage_ids[source_id] = stage.id

    benchmark_set = models.BenchmarkSet(pipeline_id=pipeline.id, name="benchmark")
    db.add(benchmark_set)
    db.flush()

    trace = models.Trace(
        benchmark_set_id=benchmark_set.id, source_trace_id="t1", query={"q": "hi"}, query_index=0
    )
    db.add(trace)
    db.flush()

    for source_id in ("root", "second"):
        db.add(
            models.StageRecord(
                stage_id=stage_ids[source_id],
                trace_id=trace.id,
                input={"q": "hi"},
                rendered_prompt="prompt",
                output="out",
            )
        )
    db.commit()
    return pipeline.id, stage_ids


def _make_migration(db: Session, pipeline_id: int, target_model_config: dict) -> int:
    migration = models.Migration(
        pipeline_id=pipeline_id,
        target_model_config=target_model_config,
        budget=10.0,
        parity_threshold=0.95,
        status="running",
    )
    db.add(migration)
    db.commit()
    db.refresh(migration)
    return migration.id


def _recording_fake_run_optimizer(calls: list[dict]):
    """Returns a fake matching run_optimizer's signature that records each
    invocation's target_model (every stage passed in one call shares it -
    the same invariant optimizer_runner.py's own batching relies on) and
    which stage ids were included, then fires one on_attempt per stage so
    Candidate.target_model can be checked end-to-end too - proving the
    on_attempt closure recorded whichever model was *actually* running at
    call time (via _state["current_target_model"]), not a stale value left
    over from a previous loop iteration."""

    def fake(
        stages,
        *,
        call,
        budget,
        judge_model,
        strategy,
        parity_threshold,
        mutator_model=None,
        on_attempt=None,
        on_phase=None,
        **_kw,
    ):
        calls.append(
            {
                "target_model": stages[0].target_model,
                "stage_ids": [s.stage_id for s in stages],
            }
        )
        if on_attempt is not None:
            for s in stages:
                on_attempt(
                    StageAttempt(
                        stage_id=s.stage_id,
                        target_model=s.target_model,
                        prompt_variant=f"variant for stage {s.stage_id}",
                        params={},
                        format_mode="text",
                        scores={"final": 0.5},
                        cost_usd=0.001,
                        latency_ms=10.0,
                    )
                )
        return OptimizationResult(
            stage_results=[
                StageResult(
                    stage_id=s.stage_id,
                    best=None,
                    attempts_tried=1,
                    met_threshold=False,
                    selection_reason="test",
                )
                for s in stages
            ],
            total_cost_usd=0.001 * len(stages),
            stopped_early=False,
            stop_reason=None,
        )

    return fake


def _add_api_key(db: Session, workspace: models.Workspace, provider: str) -> None:
    """Minimal WorkspaceApiKey row - get_available_models only reads
    ``.provider`` off these rows (never decrypts ``encrypted_key``), so a
    placeholder ciphertext is fine for these DB-level tests."""
    db.add(
        models.WorkspaceApiKey(
            workspace_id=workspace.id,
            provider=provider,
            encrypted_key="unused-in-this-test",
            last_four="1234",
        )
    )
    db.commit()


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


def _capturing_fake_run_optimizer(captured: dict):
    """Returns a fake matching run_optimizer's signature that records the
    judge_model/mutator_model it was actually called with, then reports one
    no-op StageResult - used by the judge/mutator selection tests below,
    which care about *which model was selected*, not the phase-event
    plumbing _fake_run_optimizer above exercises."""

    def fake(
        stages,
        *,
        call,
        budget,
        judge_model,
        strategy,
        parity_threshold,
        mutator_model=None,
        on_attempt=None,
        on_phase=None,
        **_kw,
    ):
        captured["judge_model"] = judge_model
        captured["mutator_model"] = mutator_model
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


# ---------------------------------------------------------------------------
# Judge/mutator model selection - decoupled from target_model_config.models
# (see DEV_TRACKER.md's "Fix judge/mutator self-grading bias" section: the
# target model(s) are the user's own choice of what's being tested; judge/
# mutator are Reprompt's own harness infrastructure and must never silently
# fall back to whatever the user picked to test).
# ---------------------------------------------------------------------------


def test_judge_and_mutator_auto_select_from_workspace_not_target_model(
    client: None, session_factory: sessionmaker
) -> None:
    """No explicit judge_model/mutator_model override - both must be
    auto-selected from the WORKSPACE's available models (get_available_models
    + select_model(), the same pattern already used for rubric generation),
    never falling back to target_model_config.models[0]. The migration's
    target model is deliberately a weak, always-available local model
    (ollama/llama3.1, tier 3) while an Anthropic BYOK key makes a stronger
    tier-1 model (claude-sonnet-4-5) available - proving the selection is
    actually decoupled from what's being tested, not just coincidentally
    different."""
    with session_factory() as db:
        workspace = _make_workspace(db)
        _add_api_key(db, workspace, "anthropic")
        pipeline_id, migration_id = _make_migration_with_one_stage(
            db, target_model_config={"models": ["ollama/llama3.1"]}
        )

    captured: dict = {}
    with patch(
        "reprompt_api.optimizer_runner.run_optimizer", _capturing_fake_run_optimizer(captured)
    ):
        run_optimizer_for_migration(migration_id)

    assert captured["judge_model"] == "claude-sonnet-4-5"
    assert captured["mutator_model"] == "claude-sonnet-4-5"
    # The whole point: neither matches the target model actually under test.
    assert captured["judge_model"] != "ollama/llama3.1"
    assert captured["mutator_model"] != "ollama/llama3.1"


def test_env_var_override_wins_over_auto_select_for_judge_and_mutator(
    client: None, session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REPROMPT_JUDGE_MODEL/REPROMPT_MUTATOR_MODEL, when set by the operator,
    must be used instead of auto-select - even though a BYOK key would
    otherwise make a different model the tier-1 auto-select pick. Neither
    migration sets its own judge_model/mutator_model override, so this
    exercises the middle tier of the 3-tier priority chain."""
    monkeypatch.setenv("REPROMPT_JUDGE_MODEL", "nvidia_nim/deepseek-ai/deepseek-v4-flash")
    monkeypatch.setenv("REPROMPT_MUTATOR_MODEL", "nvidia_nim/deepseek-ai/deepseek-v4-flash")
    with session_factory() as db:
        workspace = _make_workspace(db)
        _add_api_key(db, workspace, "anthropic")
        pipeline_id, migration_id = _make_migration_with_one_stage(
            db, target_model_config={"models": ["ollama/llama3.1"]}
        )

    captured: dict = {}
    with patch(
        "reprompt_api.optimizer_runner.run_optimizer", _capturing_fake_run_optimizer(captured)
    ):
        run_optimizer_for_migration(migration_id)

    assert captured["judge_model"] == "nvidia_nim/deepseek-ai/deepseek-v4-flash"
    assert captured["mutator_model"] == "nvidia_nim/deepseek-ai/deepseek-v4-flash"


def test_migration_level_override_still_wins_over_env_var(
    client: None, session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A per-migration judge_model/mutator_model override (top of the
    3-tier priority chain) must still beat the operator's env var."""
    monkeypatch.setenv("REPROMPT_JUDGE_MODEL", "nvidia_nim/deepseek-ai/deepseek-v4-flash")
    with session_factory() as db:
        _make_workspace(db)
        pipeline_id, migration_id = _make_migration_with_one_stage(
            db,
            target_model_config={
                "models": ["gpt-4o-mini"],
                "judge_model": "claude-haiku-4-5",
            },
        )

    captured: dict = {}
    with patch(
        "reprompt_api.optimizer_runner.run_optimizer", _capturing_fake_run_optimizer(captured)
    ):
        run_optimizer_for_migration(migration_id)

    assert captured["judge_model"] == "claude-haiku-4-5"


def test_explicit_judge_model_override_wins_over_auto_select(
    client: None, session_factory: sessionmaker
) -> None:
    with session_factory() as db:
        _make_workspace(db)
        pipeline_id, migration_id = _make_migration_with_one_stage(
            db,
            target_model_config={
                "models": ["gpt-4o-mini"],
                "judge_model": "claude-haiku-4-5",
            },
        )

    captured: dict = {}
    with patch(
        "reprompt_api.optimizer_runner.run_optimizer", _capturing_fake_run_optimizer(captured)
    ):
        run_optimizer_for_migration(migration_id)

    # Explicit override wins outright - never second-guessed against the
    # workspace's available models (no BYOK key configured for anthropic
    # here at all, yet the override is still honored exactly as given).
    assert captured["judge_model"] == "claude-haiku-4-5"


def test_explicit_mutator_model_override_wins_over_auto_select(
    client: None, session_factory: sessionmaker
) -> None:
    with session_factory() as db:
        _make_workspace(db)
        pipeline_id, migration_id = _make_migration_with_one_stage(
            db,
    target_model_config={
                "models": ["gpt-4o-mini"],
                "mutator_model": "gpt-4o",
            },
        )

    captured: dict = {}
    with patch(
        "reprompt_api.optimizer_runner.run_optimizer", _capturing_fake_run_optimizer(captured)
    ):
        run_optimizer_for_migration(migration_id)

    assert captured["mutator_model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# Per-stage target model override (target_model_config.stage_overrides) -
# re-added on top of the flat `models` list shape, see DEV_TRACKER.md's
# "Per-stage target model override" note. `models` stays the default/simple
# path (try every model against every stage); `stage_overrides` is additive:
# a stage keyed there tries only its own list, replacing `models` for that
# stage only - stages absent from it are unaffected.
# ---------------------------------------------------------------------------


def test_stage_overrides_uses_override_models_for_that_stage_only(
    client: None, session_factory: sessionmaker
) -> None:
    with session_factory() as db:
        _make_workspace(db)
        pipeline_id, stage_ids = _make_two_stage_pipeline(db)
        migration_id = _make_migration(
            db,
            pipeline_id,
            target_model_config={
                "models": ["gpt-4o-mini"],
                "stage_overrides": {str(stage_ids["second"]): ["claude-haiku-4-5"]},
            },
        )

    calls: list[dict] = []
    with patch("reprompt_api.optimizer_runner.run_optimizer", _recording_fake_run_optimizer(calls)):
        run_optimizer_for_migration(migration_id)

    # The stage with no override ("root") ran once, against the global list.
    root_calls = [c for c in calls if stage_ids["root"] in c["stage_ids"]]
    assert len(root_calls) == 1
    assert root_calls[0]["target_model"] == "gpt-4o-mini"
    assert root_calls[0]["stage_ids"] == [stage_ids["root"]]

    # The overridden stage ("second") ran once, against ITS model only -
    # never the global gpt-4o-mini, and isolated from "root" (its own
    # run_optimizer call, not batched with the default-path stages).
    second_calls = [c for c in calls if stage_ids["second"] in c["stage_ids"]]
    assert len(second_calls) == 1
    assert second_calls[0]["target_model"] == "claude-haiku-4-5"
    assert second_calls[0]["stage_ids"] == [stage_ids["second"]]

    # Candidate rows persisted with the correct target_model per stage -
    # confirms on_attempt's _state["current_target_model"] threading is
    # right across both the global-model loop and the override loop, not
    # just that run_optimizer itself was called with the right model.
    with session_factory() as db:
        candidates = db.query(models.Candidate).filter(
            models.Candidate.migration_id == migration_id
        ).all()
        by_stage = {c.stage_id: c.target_model for c in candidates}
    assert by_stage[stage_ids["root"]] == "gpt-4o-mini"
    assert by_stage[stage_ids["second"]] == "claude-haiku-4-5"


def test_stage_without_override_falls_back_to_global_models_list(
    client: None, session_factory: sessionmaker
) -> None:
    """A migration with no stage_overrides at all behaves exactly as before
    this field existed - every stage batched together, once per global
    model."""
    with session_factory() as db:
        _make_workspace(db)
        pipeline_id, stage_ids = _make_two_stage_pipeline(db)
        migration_id = _make_migration(
            db, pipeline_id, target_model_config={"models": ["gpt-4o-mini", "claude-haiku-4-5"]}
        )

    calls: list[dict] = []
    with patch("reprompt_api.optimizer_runner.run_optimizer", _recording_fake_run_optimizer(calls)):
        run_optimizer_for_migration(migration_id)

    assert len(calls) == 2
    assert {c["target_model"] for c in calls} == {"gpt-4o-mini", "claude-haiku-4-5"}
    for c in calls:
        assert set(c["stage_ids"]) == {stage_ids["root"], stage_ids["second"]}


def test_stage_overrides_with_multiple_models_tries_each_for_that_stage(
    client: None, session_factory: sessionmaker
) -> None:
    """An override list with more than one model produces one run_optimizer
    call per override model for that stage - the same "try each, keep the
    best" semantics the global `models` list already has, just scoped to
    one stage."""
    with session_factory() as db:
        _make_workspace(db)
        pipeline_id, stage_ids = _make_two_stage_pipeline(db)
        migration_id = _make_migration(
            db,
            pipeline_id,
            target_model_config={
                "models": ["gpt-4o-mini"],
                "stage_overrides": {
                    str(stage_ids["second"]): ["claude-haiku-4-5", "gemini/gemini-2.0-flash"]
                },
            },
        )

    calls: list[dict] = []
    with patch("reprompt_api.optimizer_runner.run_optimizer", _recording_fake_run_optimizer(calls)):
        run_optimizer_for_migration(migration_id)

    second_calls = [c for c in calls if stage_ids["second"] in c["stage_ids"]]
    assert {c["target_model"] for c in second_calls} == {
        "claude-haiku-4-5",
        "gemini/gemini-2.0-flash",
    }
    assert len(second_calls) == 2


def test_stage_overrides_covering_every_stage_skips_the_global_model_loop_entirely(
    client: None, session_factory: sessionmaker
) -> None:
    """When every stage has its own override, the global `models` list is
    never tried against anything - no wasted/empty run_optimizer calls."""
    with session_factory() as db:
        _make_workspace(db)
        pipeline_id, stage_ids = _make_two_stage_pipeline(db)
        migration_id = _make_migration(
            db,
            pipeline_id,
            target_model_config={
                "models": ["gpt-4o-mini"],
                "stage_overrides": {
                    str(stage_ids["root"]): ["claude-haiku-4-5"],
                    str(stage_ids["second"]): ["gemini/gemini-2.0-flash"],
                },
            },
        )

    calls: list[dict] = []
    with patch("reprompt_api.optimizer_runner.run_optimizer", _recording_fake_run_optimizer(calls)):
        run_optimizer_for_migration(migration_id)

    assert len(calls) == 2
    used = {c["target_model"] for c in calls}
    assert used == {"claude-haiku-4-5", "gemini/gemini-2.0-flash"}
    assert "gpt-4o-mini" not in used
