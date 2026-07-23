"""Tests for POST /pipelines/{pipeline_id}/stages/{stage_id}/generate-rubric
— the M2 rubric-engine endpoint that wires reprompt_core.rubric_generator to
a workspace's real BYOK credential and persists the result.

Same TestClient + in-memory SQLite + magic-link sign-in pattern as
test_pipelines_test_prompt.py. No real network call in this suite: the live
proof of reprompt_core.rubric_generator actually working against a real
model lives in packages/core's test_rubric_generator_live.py (per the task
brief). Here, `reprompt_api.rubrics.complete_with_workspace_credentials` is
monkeypatched directly — the exact call site the endpoint uses — to a fake
that returns a canned LLMResponse, so the auth/404/missing-key paths and
the real generation -> translation -> persistence pipeline are all
exercised fast and deterministically.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from reprompt_core import (
    Pipeline as CorePipeline,
    Stage as CoreStage,
    StageRecord as CoreStageRecord,
    TokenUsage as CoreTokenUsage,
    Trace as CoreTrace,
    TraceFile,
)
from reprompt_core.llm.client import LLMResponse
from reprompt_core.trace import TokenUsage as CoreTokenUsageModel

from reprompt_api import crypto, models
from reprompt_api.db import get_db
from reprompt_api.main import app
from reprompt_api.models import Base

VALID_RUBRIC_CONTENT = json.dumps(
    {
        "deterministic_checks": [
            {"type": "required_keys", "keys": ["currency", "revenue"]},
        ],
        "judge_criteria": [
            {"name": "Correct currency", "weight": 1.0, "description": "Matches the input currency."},
        ],
        "downstream_contract": ["currency", "revenue"],
    }
)


def _fake_llm_response(content: str, *, model: str = "claude-sonnet-4-5") -> LLMResponse:
    return LLMResponse(
        content=content,
        model=model,
        provider="anthropic",
        usage=CoreTokenUsageModel(input=100, output=50, thinking=None),
        cost_usd=0.001,
        latency_ms=123.0,
        finish_reason="stop",
    )


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(crypto.ENV_VAR, Fernet.generate_key().decode())
    crypto.reset_cache_for_tests()
    yield
    crypto.reset_cache_for_tests()


@pytest.fixture()
def session_factory() -> sessionmaker:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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


def _sign_in(client: TestClient, email: str) -> tuple[str, int]:
    response = client.post("/auth/request-link", json={"email": email})
    assert response.status_code == 200, response.text
    query = parse_qs(urlparse(response.json()["dev_magic_link"]).query)
    raw_token = query["token"][0]

    verify = client.post("/auth/verify", json={"token": raw_token})
    assert verify.status_code == 200, verify.text
    body = verify.json()
    return body["session_token"], body["workspace"]["id"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _import_pipeline_with_traces(
    client: TestClient, *, model: str = "gpt-4o", prompt: str = "Extract {{document}}", outputs: list[str]
) -> tuple[int, int]:
    """Uploads a one-stage pipeline with one trace (and one StageRecord) per
    entry in `outputs`. Returns (pipeline_id, stage_id)."""
    stage = CoreStage(id="only", name="Only Stage", model=model, prompt_template=prompt)
    pipeline = CorePipeline(id="p", name="Generate Rubric Test Pipeline", stages=[stage])
    traces = [
        CoreTrace(
            trace_id=f"t{i}",
            query={"document": f"doc {i}"},
            records=[
                CoreStageRecord(
                    stage_id="only",
                    input={"document": f"doc {i}"},
                    rendered_prompt=f"prompt for doc {i}",
                    output=output,
                    tokens=CoreTokenUsage(**{"in": 5, "out": 3}),
                    latency_ms=10.0,
                )
            ],
        )
        for i, output in enumerate(outputs)
    ]
    trace_file = TraceFile(pipeline=pipeline, traces=traces)
    payload = trace_file.model_dump(by_alias=True)
    response = client.post(
        "/pipelines/import",
        files={"file": ("trace.json", json.dumps(payload), "application/json")},
    )
    assert response.status_code == 201, response.text
    pipeline_id = response.json()["pipeline_id"]

    dag = client.get(f"/pipelines/{pipeline_id}/dag")
    assert dag.status_code == 200, dag.text
    (stage_id_str,) = dag.json()["stages"].keys()
    return pipeline_id, int(stage_id_str)


# ---------------------------------------------------------------------------
# Auth / not-found / no traces
# ---------------------------------------------------------------------------


def test_requires_authentication(client: TestClient) -> None:
    pipeline_id, stage_id = _import_pipeline_with_traces(client, outputs=["out1"])
    response = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/generate-rubric", json={"model": "claude-sonnet-4-5"}
    )
    assert response.status_code == 401


def test_unknown_stage_returns_404(client: TestClient) -> None:
    token, _ = _sign_in(client, "notfound@example.com")
    pipeline_id, _stage_id = _import_pipeline_with_traces(client, outputs=["out1"])

    response = client.post(
        f"/pipelines/{pipeline_id}/stages/999999/generate-rubric",
        json={"model": "claude-sonnet-4-5"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 404


def test_unknown_pipeline_returns_404(client: TestClient) -> None:
    token, _ = _sign_in(client, "nopipeline@example.com")
    _pipeline_id, stage_id = _import_pipeline_with_traces(client, outputs=["out1"])

    response = client.post(
        f"/pipelines/999999/stages/{stage_id}/generate-rubric",
        json={"model": "claude-sonnet-4-5"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Missing provider key
# ---------------------------------------------------------------------------


def test_missing_provider_key_returns_422_naming_the_provider(client: TestClient) -> None:
    token, _ = _sign_in(client, "nokey@example.com")
    pipeline_id, stage_id = _import_pipeline_with_traces(client, outputs=["out1"])

    response = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/generate-rubric",
        json={"model": "claude-sonnet-4-5"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert "anthropic" in detail
    assert "/settings" in detail


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_success_path_generates_and_persists_a_real_rubric_row(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, _ = _sign_in(client, "success@example.com")
    client.post(
        "/settings/api-keys",
        json={"provider": "anthropic", "api_key": "sk-workspacekey12345"},
        headers=_auth_headers(token),
    )
    pipeline_id, stage_id = _import_pipeline_with_traces(
        client, outputs=['{"currency": "USD", "revenue": 100}', '{"currency": "EUR", "revenue": 200}']
    )

    captured: dict = {}

    def fake_complete_with_workspace_credentials(db, workspace, model, messages, **kwargs):
        captured["model"] = model
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return _fake_llm_response(VALID_RUBRIC_CONTENT)

    monkeypatch.setattr(
        "reprompt_api.rubrics.complete_with_workspace_credentials", fake_complete_with_workspace_credentials
    )

    response = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/generate-rubric",
        json={"model": "claude-sonnet-4-5"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stage_name"] == "Only Stage"
    assert body["approved"] is False
    assert body["deterministic_checks"] == [{"type": "required_keys", "keys": ["currency", "revenue"]}]
    assert body["judge_criteria"] == [
        {"name": "Correct currency", "weight": 1.0, "description": "Matches the input currency."}
    ]
    assert body["downstream_contract"] == ["currency", "revenue"]
    assert body["generated_with_model"] == "claude-sonnet-4-5"

    # Both traces' outputs reached the prompt — "analyzing that stage's
    # outputs across all traces", not just the first one.
    user_content = captured["messages"][1]["content"]
    assert '{"currency": "USD", "revenue": 100}' in user_content
    assert '{"currency": "EUR", "revenue": 200}' in user_content
    assert captured["model"] == "claude-sonnet-4-5"

    # It was actually persisted, not just returned - a follow-up GET sees it.
    listing = client.get(f"/pipelines/{pipeline_id}/rubrics").json()
    assert len(listing) == 1
    assert listing[0]["id"] == body["id"]
    # generated_with_model is a transient generate-call detail, not stored
    # on the Rubric row - a plain list fetch never carries it.
    assert listing[0]["generated_with_model"] is None


def test_no_trace_records_for_stage_returns_422(client: TestClient) -> None:
    """A stage with zero StageRecords (shouldn't normally happen post-import,
    but is a real possible state) can't be analyzed - fails clearly rather
    than calling the model with no examples at all."""
    token, _ = _sign_in(client, "notraces@example.com")
    client.post(
        "/settings/api-keys",
        json={"provider": "anthropic", "api_key": "sk-workspacekey12345"},
        headers=_auth_headers(token),
    )
    # Two-stage pipeline where the trace only covers "first" - "second" gets
    # zero StageRecords even though the stage itself exists.
    stages = [
        CoreStage(id="first", name="First", model="gpt-4o", prompt_template="{{q}}"),
        CoreStage(id="second", name="Second", depends_on=["first"], model="gpt-4o", prompt_template="{{first}}"),
    ]
    pipeline = CorePipeline(id="p2", name="Sparse Pipeline", stages=stages)
    trace = CoreTrace(
        trace_id="t0",
        query={"q": "hi"},
        # Only "first" gets a StageRecord. TraceFile validation only checks
        # that every record references a *known* stage id, not that every
        # declared stage has a record in every trace - so "second" ends up
        # with zero StageRecords after import, which is exactly the state
        # this test needs.
        records=[
            CoreStageRecord(
                stage_id="first",
                rendered_prompt="p",
                output="o",
                tokens=CoreTokenUsage(**{"in": 1, "out": 1}),
                latency_ms=1.0,
            ),
        ],
    )
    trace_file = TraceFile(pipeline=pipeline, traces=[trace])
    payload = trace_file.model_dump(by_alias=True)
    response = client.post(
        "/pipelines/import",
        files={"file": ("trace.json", json.dumps(payload), "application/json")},
    )
    assert response.status_code == 201, response.text
    pipeline_id = response.json()["pipeline_id"]
    dag = client.get(f"/pipelines/{pipeline_id}/dag").json()
    second_stage_id = next(int(sid) for sid, info in dag["stages"].items() if info["name"] == "Second")

    gen_response = client.post(
        f"/pipelines/{pipeline_id}/stages/{second_stage_id}/generate-rubric",
        json={"model": "claude-sonnet-4-5"},
        headers=_auth_headers(token),
    )
    assert gen_response.status_code == 422
    assert "no benchmark trace records" in gen_response.json()["detail"]


# ---------------------------------------------------------------------------
# Auto-select when no model is given (model_select.select_model)
# ---------------------------------------------------------------------------


def test_omitting_model_auto_selects_from_configured_models(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No `model` in the request body at all - the endpoint must pick one
    itself via reprompt_core.llm.model_select.select_model rather than
    rejecting the request. With only an anthropic key configured, the only
    tier-1 candidate available is claude-sonnet-4-5 (gpt-4o/gemini are
    filtered out - their providers have no configured key), so that's what
    should be called and reported back."""
    token, _ = _sign_in(client, "autoselect@example.com")
    client.post(
        "/settings/api-keys",
        json={"provider": "anthropic", "api_key": "sk-workspacekey12345"},
        headers=_auth_headers(token),
    )
    pipeline_id, stage_id = _import_pipeline_with_traces(client, outputs=["out1"])

    captured: dict = {}

    def fake_complete_with_workspace_credentials(db, workspace, model, messages, **kwargs):
        captured["model"] = model
        return _fake_llm_response(VALID_RUBRIC_CONTENT, model=model)

    monkeypatch.setattr(
        "reprompt_api.rubrics.complete_with_workspace_credentials", fake_complete_with_workspace_credentials
    )

    response = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/generate-rubric",
        json={},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200, response.text
    assert captured["model"] == "claude-sonnet-4-5"
    assert response.json()["generated_with_model"] == "claude-sonnet-4-5"


def test_null_model_also_auto_selects(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same as omitting the key entirely - an explicit JSON null must be
    treated the same as "not provided", not as a validation error."""
    token, _ = _sign_in(client, "nullmodel@example.com")
    client.post(
        "/settings/api-keys",
        json={"provider": "openai", "api_key": "sk-workspacekey12345"},
        headers=_auth_headers(token),
    )
    pipeline_id, stage_id = _import_pipeline_with_traces(client, outputs=["out1"])

    captured: dict = {}

    def fake_complete_with_workspace_credentials(db, workspace, model, messages, **kwargs):
        captured["model"] = model
        return _fake_llm_response(VALID_RUBRIC_CONTENT, model=model)

    monkeypatch.setattr(
        "reprompt_api.rubrics.complete_with_workspace_credentials", fake_complete_with_workspace_credentials
    )

    response = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/generate-rubric",
        json={"model": None},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200, response.text
    assert captured["model"] == "gpt-4o"


def test_env_var_override_wins_over_auto_select_when_model_omitted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REPROMPT_RUBRIC_MODEL, when set by the operator, must be used instead
    of auto-select - even though the workspace's own configured key would
    otherwise make a different model the tier-1 auto-select pick."""
    monkeypatch.setenv("REPROMPT_RUBRIC_MODEL", "nvidia_nim/deepseek-ai/deepseek-v4-flash")
    token, _ = _sign_in(client, "envoverride@example.com")
    client.post(
        "/settings/api-keys",
        json={"provider": "anthropic", "api_key": "sk-workspacekey12345"},
        headers=_auth_headers(token),
    )
    pipeline_id, stage_id = _import_pipeline_with_traces(client, outputs=["out1"])

    captured: dict = {}

    def fake_complete_with_workspace_credentials(db, workspace, model, messages, **kwargs):
        captured["model"] = model
        return _fake_llm_response(VALID_RUBRIC_CONTENT, model=model)

    monkeypatch.setattr(
        "reprompt_api.rubrics.complete_with_workspace_credentials", fake_complete_with_workspace_credentials
    )

    response = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/generate-rubric",
        json={},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200, response.text
    assert captured["model"] == "nvidia_nim/deepseek-ai/deepseek-v4-flash"


def test_explicit_body_model_still_wins_over_env_var_override(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller-supplied `model` in the request body outranks the operator's
    env var override, same as it outranks plain auto-select."""
    monkeypatch.setenv("REPROMPT_RUBRIC_MODEL", "nvidia_nim/deepseek-ai/deepseek-v4-flash")
    token, _ = _sign_in(client, "envoverride-explicit@example.com")
    client.post(
        "/settings/api-keys",
        json={"provider": "openai", "api_key": "sk-workspacekey12345"},
        headers=_auth_headers(token),
    )
    pipeline_id, stage_id = _import_pipeline_with_traces(client, outputs=["out1"])

    captured: dict = {}

    def fake_complete_with_workspace_credentials(db, workspace, model, messages, **kwargs):
        captured["model"] = model
        return _fake_llm_response(VALID_RUBRIC_CONTENT, model=model)

    monkeypatch.setattr(
        "reprompt_api.rubrics.complete_with_workspace_credentials", fake_complete_with_workspace_credentials
    )

    response = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/generate-rubric",
        json={"model": "gpt-4o-mini"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200, response.text
    assert captured["model"] == "gpt-4o-mini"


def test_explicit_model_is_never_second_guessed_by_auto_select(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicitly-given model is used exactly as given, even though it
    is NOT the workspace's configured provider's tier-1 pick (openai key
    configured, but the caller explicitly asked for gpt-4o-mini, a tier-2
    model) - the explicit choice must never be overridden."""
    token, _ = _sign_in(client, "explicitwins@example.com")
    client.post(
        "/settings/api-keys",
        json={"provider": "openai", "api_key": "sk-workspacekey12345"},
        headers=_auth_headers(token),
    )
    pipeline_id, stage_id = _import_pipeline_with_traces(client, outputs=["out1"])

    captured: dict = {}

    def fake_complete_with_workspace_credentials(db, workspace, model, messages, **kwargs):
        captured["model"] = model
        return _fake_llm_response(VALID_RUBRIC_CONTENT, model=model)

    monkeypatch.setattr(
        "reprompt_api.rubrics.complete_with_workspace_credentials", fake_complete_with_workspace_credentials
    )

    response = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/generate-rubric",
        json={"model": "gpt-4o-mini"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200, response.text
    assert captured["model"] == "gpt-4o-mini"


def test_auto_select_falls_back_to_no_key_models_before_any_byok_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No BYOK key configured at all - the workspace still has the no-key
    local models available (per get_available_models/GET /settings/models
    behavior), so auto-select must succeed rather than 422ing, picking one
    of those."""
    token, _ = _sign_in(client, "nokeyautoselect@example.com")
    pipeline_id, stage_id = _import_pipeline_with_traces(client, outputs=["out1"])

    captured: dict = {}

    def fake_complete_with_workspace_credentials(db, workspace, model, messages, **kwargs):
        captured["model"] = model
        return _fake_llm_response(VALID_RUBRIC_CONTENT, model=model)

    monkeypatch.setattr(
        "reprompt_api.rubrics.complete_with_workspace_credentials", fake_complete_with_workspace_credentials
    )

    response = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/generate-rubric",
        json={},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200, response.text
    assert captured["model"] in {"ollama/llama3.1", "ollama/qwen2.5:14b"}


# ---------------------------------------------------------------------------
# Upsert / re-approval-reset behavior
# ---------------------------------------------------------------------------


def test_regenerating_an_approved_rubric_overwrites_content_and_resets_approval(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, _ = _sign_in(client, "reapprove@example.com")
    client.post(
        "/settings/api-keys",
        json={"provider": "anthropic", "api_key": "sk-workspacekey12345"},
        headers=_auth_headers(token),
    )
    pipeline_id, stage_id = _import_pipeline_with_traces(client, outputs=['{"currency": "USD", "revenue": 100}'])

    monkeypatch.setattr(
        "reprompt_api.rubrics.complete_with_workspace_credentials",
        lambda db, workspace, model, messages, **kw: _fake_llm_response(VALID_RUBRIC_CONTENT),
    )

    first = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/generate-rubric",
        json={"model": "claude-sonnet-4-5"},
        headers=_auth_headers(token),
    )
    assert first.status_code == 200, first.text
    rubric_id = first.json()["id"]

    approve = client.post(f"/rubrics/{rubric_id}/approve")
    assert approve.status_code == 200
    assert approve.json()["approved"] is True

    new_content = json.dumps(
        {
            "deterministic_checks": [{"type": "required_keys", "keys": ["order_id"]}],
            "judge_criteria": [{"name": "New criterion", "weight": 1.0, "description": "..."}],
            "downstream_contract": ["order_id"],
        }
    )
    monkeypatch.setattr(
        "reprompt_api.rubrics.complete_with_workspace_credentials",
        lambda db, workspace, model, messages, **kw: _fake_llm_response(new_content),
    )

    second = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/generate-rubric",
        json={"model": "claude-sonnet-4-5"},
        headers=_auth_headers(token),
    )
    assert second.status_code == 200, second.text
    body = second.json()

    # Same row, not a new one - the unique constraint on stage_id enforces
    # this, but assert the id explicitly too.
    assert body["id"] == rubric_id
    assert body["deterministic_checks"] == [{"type": "required_keys", "keys": ["order_id"]}]
    assert body["downstream_contract"] == ["order_id"]
    # Re-review is required after content changes underneath an approval.
    assert body["approved"] is False

    listing = client.get(f"/pipelines/{pipeline_id}/rubrics").json()
    assert len(listing) == 1
    assert listing[0]["id"] == rubric_id
    assert listing[0]["approved"] is False


# ---------------------------------------------------------------------------
# Generator-error mapping
# ---------------------------------------------------------------------------


def test_unusable_model_output_returns_422(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two consecutive unparseable responses (the generator's one retry also
    fails) surfaces as a 422, not a 500 - see reprompt_core.rubric_generator's
    RubricGenerationError handling."""
    token, _ = _sign_in(client, "badoutput@example.com")
    client.post(
        "/settings/api-keys",
        json={"provider": "anthropic", "api_key": "sk-workspacekey12345"},
        headers=_auth_headers(token),
    )
    pipeline_id, stage_id = _import_pipeline_with_traces(client, outputs=["out1"])

    monkeypatch.setattr(
        "reprompt_api.rubrics.complete_with_workspace_credentials",
        lambda db, workspace, model, messages, **kw: _fake_llm_response("not json at all"),
    )

    response = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/generate-rubric",
        json={"model": "claude-sonnet-4-5"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 422, response.text
    assert "corrective retry" in response.json()["detail"]
