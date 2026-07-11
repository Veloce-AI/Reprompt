"""Tests for POST /pipelines/{pipeline_id}/stages/{stage_id}/test-prompt —
the M5 BYOK proof-of-concept endpoint that exercises
refract_api.llm_context end to end through the real HTTP surface.

Same TestClient + in-memory SQLite pattern as test_pipelines.py/
test_settings.py. Users/sessions come from the real magic-link flow (as
in test_settings.py) since this endpoint is workspace-scoped. No real
network call: `refract_core.llm.client.complete` is mocked at the
`litellm.completion` layer, same technique as
packages/core/tests/test_llm_client.py and test_llm_context.py.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from litellm.types.utils import Choices, Message as LiteLLMMessage, ModelResponse, Usage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from refract_core import (
    Pipeline as CorePipeline,
    Stage as CoreStage,
    StageRecord as CoreStageRecord,
    TokenUsage as CoreTokenUsage,
    Trace as CoreTrace,
    TraceFile,
)

from refract_api import crypto, models
from refract_api.db import get_db
from refract_api.main import app
from refract_api.models import Base


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(crypto.ENV_VAR, Fernet.generate_key().decode())
    crypto.reset_cache_for_tests()
    yield
    crypto.reset_cache_for_tests()


@pytest.fixture()
def session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
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


def _import_single_stage_pipeline(
    client: TestClient, *, model: str = "gpt-4o", prompt: str = "Say hi"
) -> tuple[int, int]:
    """Uploads a minimal one-stage pipeline via the real /pipelines/import
    endpoint and returns (pipeline_id, stage_id)."""
    stage = CoreStage(id="only", name="Only Stage", model=model, prompt_template=prompt)
    pipeline = CorePipeline(id="p", name="Test Prompt Pipeline", stages=[stage])
    trace = CoreTrace(
        trace_id="t0",
        query={"q": "hello"},
        records=[
            CoreStageRecord(
                stage_id="only",
                rendered_prompt=prompt,
                output="some output",
                tokens=CoreTokenUsage(**{"in": 5, "out": 3}),
                latency_ms=10.0,
            )
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

    dag = client.get(f"/pipelines/{pipeline_id}/dag")
    assert dag.status_code == 200, dag.text
    (stage_id_str,) = dag.json()["stages"].keys()
    return pipeline_id, int(stage_id_str)


def _fake_response(*, model: str = "gpt-4o-2024-08-06", content: str = "hello!") -> ModelResponse:
    return ModelResponse(
        id="chatcmpl-test",
        created=0,
        model=model,
        object="chat.completion",
        choices=[
            Choices(
                finish_reason="stop",
                index=0,
                message=LiteLLMMessage(content=content, role="assistant"),
            )
        ],
        usage=Usage(prompt_tokens=12, completion_tokens=4, total_tokens=16),
    )


# ---------------------------------------------------------------------------
# Auth / not-found
# ---------------------------------------------------------------------------


def test_requires_authentication(client: TestClient) -> None:
    pipeline_id, stage_id = _import_single_stage_pipeline(client)
    response = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/test-prompt", json={"model": "gpt-4o"}
    )
    assert response.status_code == 401


def test_unknown_stage_returns_404(client: TestClient) -> None:
    token, _ = _sign_in(client, "notfound@example.com")
    pipeline_id, _stage_id = _import_single_stage_pipeline(client)

    response = client.post(
        f"/pipelines/{pipeline_id}/stages/999999/test-prompt",
        json={"model": "gpt-4o"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Missing provider key
# ---------------------------------------------------------------------------


def test_missing_provider_key_returns_422_naming_the_provider(client: TestClient) -> None:
    token, _ = _sign_in(client, "nokey@example.com")
    pipeline_id, stage_id = _import_single_stage_pipeline(client, model="gpt-4o")

    response = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/test-prompt",
        json={"model": "gpt-4o"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert "openai" in detail
    assert "/settings" in detail


def test_missing_provider_key_is_specific_to_the_required_provider(client: TestClient) -> None:
    """A key saved for a *different* provider than the requested model
    needs must not satisfy the check."""
    token, _ = _sign_in(client, "wrongprovider@example.com")
    client.post(
        "/settings/api-keys",
        json={"provider": "anthropic", "api_key": "sk-anthropickey1111"},
        headers=_auth_headers(token),
    )
    pipeline_id, stage_id = _import_single_stage_pipeline(client, model="gpt-4o")

    response = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/test-prompt",
        json={"model": "gpt-4o"},
        headers=_auth_headers(token),
    )
    assert response.status_code == 422
    assert "openai" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Success path (complete() mocked)
# ---------------------------------------------------------------------------


def test_success_path_returns_llm_response_and_uses_the_saved_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, _ = _sign_in(client, "success@example.com")
    client.post(
        "/settings/api-keys",
        json={"provider": "openai", "api_key": "sk-workspacekey12345"},
        headers=_auth_headers(token),
    )
    pipeline_id, stage_id = _import_single_stage_pipeline(
        client, model="gpt-4o", prompt="Summarize this in one sentence."
    )

    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _fake_response(content="a one-sentence summary")

    monkeypatch.setattr("refract_core.llm.client.litellm.completion", fake_completion)

    response = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/test-prompt",
        json={"model": "gpt-4o"},
        headers=_auth_headers(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content"] == "a one-sentence summary"
    assert body["provider"] == "openai"
    assert body["finish_reason"] == "stop"
    assert body["usage"]["in"] == 12
    assert body["usage"]["out"] == 4
    assert body["latency_ms"] >= 0.0

    # The stage's existing prompt_template was sent, unmodified, as the
    # single user message.
    assert captured["messages"] == [
        {"role": "user", "content": "Summarize this in one sentence."}
    ]
    # And the workspace's *decrypted* key reached LiteLLM directly - never
    # via an environment variable (see refract_api.llm_context).
    assert captured["api_key"] == "sk-workspacekey12345"
    import os

    assert "OPENAI_API_KEY" not in os.environ


def test_second_workspace_never_sees_first_workspaces_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_a, _ = _sign_in(client, "isolation-a@example.com")
    token_b, _ = _sign_in(client, "isolation-b@example.com")

    client.post(
        "/settings/api-keys",
        json={"provider": "openai", "api_key": "sk-workspaceAkey1111"},
        headers=_auth_headers(token_a),
    )
    # Workspace B deliberately has no key configured at all.

    pipeline_id, stage_id = _import_single_stage_pipeline(client, model="gpt-4o")

    monkeypatch.setattr(
        "refract_core.llm.client.litellm.completion", lambda **kwargs: _fake_response()
    )

    ok = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/test-prompt",
        json={"model": "gpt-4o"},
        headers=_auth_headers(token_a),
    )
    assert ok.status_code == 200, ok.text

    # Workspace B still gets the "not configured" error - A's key never
    # became usable for B just because A's request ran moments earlier.
    denied = client.post(
        f"/pipelines/{pipeline_id}/stages/{stage_id}/test-prompt",
        json={"model": "gpt-4o"},
        headers=_auth_headers(token_b),
    )
    assert denied.status_code == 422
    assert "openai" in denied.json()["detail"]


def test_two_workspaces_back_to_back_requests_never_cross_streams(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end version of the property test_llm_context.py proves with
    genuinely-overlapping threads at the mechanism layer (see
    ``test_two_workspaces_scoped_calls_never_see_each_others_key`` there,
    which forces real concurrent execution via a ``threading.Barrier``
    around direct calls to ``complete_with_workspace_credentials``).

    Driving two *real, overlapping* HTTP requests through
    ``TestClient``/Starlette's test portal turned out to be its own source
    of flakiness unrelated to the credential-scoping code under test
    (portal/thread-pool timing, not a correctness issue here) — so this
    HTTP-layer test instead does two back-to-back calls for two different
    workspaces and asserts each is served with only its own workspace's
    key, which is exactly the "sequential-but-verifying-isolation" style
    this project's other concurrency-adjacent tests use. Combined with the
    mechanism-layer test's genuine multi-thread proof, this covers both
    "the real HTTP path resolves the right key" and "the mechanism itself
    is safe under true concurrency."
    """
    token_a, _ = _sign_in(client, "concurrent-a@example.com")
    token_b, _ = _sign_in(client, "concurrent-b@example.com")
    client.post(
        "/settings/api-keys",
        json={"provider": "openai", "api_key": "sk-concurrentAkey111"},
        headers=_auth_headers(token_a),
    )
    client.post(
        "/settings/api-keys",
        json={"provider": "openai", "api_key": "sk-concurrentBkey222"},
        headers=_auth_headers(token_b),
    )
    pipeline_a, stage_a = _import_single_stage_pipeline(
        client, model="gpt-4o", prompt="prompt-from-workspace-a"
    )
    pipeline_b, stage_b = _import_single_stage_pipeline(
        client, model="gpt-4o", prompt="prompt-from-workspace-b"
    )

    seen: list[tuple[str, str]] = []

    def fake_completion(**kwargs):
        seen.append((kwargs["messages"][0]["content"], kwargs["api_key"]))
        return _fake_response()

    monkeypatch.setattr("refract_core.llm.client.litellm.completion", fake_completion)

    response_a = client.post(
        f"/pipelines/{pipeline_a}/stages/{stage_a}/test-prompt",
        json={"model": "gpt-4o"},
        headers=_auth_headers(token_a),
    )
    response_b = client.post(
        f"/pipelines/{pipeline_b}/stages/{stage_b}/test-prompt",
        json={"model": "gpt-4o"},
        headers=_auth_headers(token_b),
    )

    assert response_a.status_code == 200, response_a.text
    assert response_b.status_code == 200, response_b.text
    seen_by_prompt = dict(seen)
    assert seen_by_prompt["prompt-from-workspace-a"] == "sk-concurrentAkey111"
    assert seen_by_prompt["prompt-from-workspace-b"] == "sk-concurrentBkey222"
