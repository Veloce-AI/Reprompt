"""Tests for refract_api.llm_context — the mechanism that scopes a
workspace's decrypted BYOK key into exactly one
`refract_core.llm.client.complete()` call.

See refract_api.llm_context's module docstring for the full design
rationale (direct per-call kwarg to LiteLLM, chosen over env-var + lock).
Because that design never touches `os.environ` at all, "no leakage
across concurrent calls" holds by construction rather than by careful
cleanup — several tests below assert that property directly (no env var
is ever set/left behind), which is the strongest possible evidence for
"the next call in this process never sees a stale credential."

No real network calls: `refract_core.llm.client.complete` is monkeypatched
at the `litellm.completion` layer, same technique as
packages/core/tests/test_llm_client.py.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from litellm.types.utils import Choices, Message as LiteLLMMessage, ModelResponse, Usage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from refract_api import crypto, models
from refract_api.llm_context import (
    ProviderKeyNotConfigured,
    complete_with_workspace_credentials,
    resolve_workspace_credential,
)
from refract_api.models import Base


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(crypto.ENV_VAR, Fernet.generate_key().decode())
    crypto.reset_cache_for_tests()
    yield
    crypto.reset_cache_for_tests()


@pytest.fixture(autouse=True)
def _no_stray_cloud_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Belt-and-braces, same as packages/core/tests/test_llm_client.py:
    this module's entire premise is "the credential never goes through
    the environment" — strip any cloud key from the environment so a test
    could never accidentally pass by reading a real ambient key instead
    of the one this module scoped in.
    """
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _make_workspace(db: Session, name: str = "Test Workspace") -> models.Workspace:
    user = models.User(email=f"{name.lower().replace(' ', '-')}@example.com")
    db.add(user)
    db.flush()
    workspace = models.Workspace(name=name, owner_user_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


def _save_key(db: Session, workspace: models.Workspace, provider: str, raw_key: str) -> None:
    db.add(
        models.WorkspaceApiKey(
            workspace_id=workspace.id,
            provider=provider,
            encrypted_key=crypto.encrypt(raw_key),
            last_four=raw_key[-4:],
        )
    )
    db.commit()


def _fake_response(*, model: str = "gpt-4o-2024-08-06", content: str = "hi") -> ModelResponse:
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
        usage=Usage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
    )


# ---------------------------------------------------------------------------
# resolve_workspace_credential
# ---------------------------------------------------------------------------


def test_resolve_workspace_credential_decrypts_the_stored_key(db: Session) -> None:
    workspace = _make_workspace(db)
    _save_key(db, workspace, "openai", "sk-realsecretvalue1111")

    plaintext = resolve_workspace_credential(db, workspace, "gpt-4o")

    assert plaintext == "sk-realsecretvalue1111"


def test_resolve_workspace_credential_raises_when_no_key_saved(db: Session) -> None:
    workspace = _make_workspace(db)

    with pytest.raises(ProviderKeyNotConfigured) as exc_info:
        resolve_workspace_credential(db, workspace, "gpt-4o")

    assert exc_info.value.provider == "openai"
    assert "openai" in str(exc_info.value)
    assert "/settings" in str(exc_info.value)


def test_resolve_workspace_credential_only_matches_the_right_provider(db: Session) -> None:
    workspace = _make_workspace(db)
    _save_key(db, workspace, "anthropic", "sk-anthropicvalue2222")

    # A gpt-4o request needs an openai key; only an anthropic key is saved.
    with pytest.raises(ProviderKeyNotConfigured) as exc_info:
        resolve_workspace_credential(db, workspace, "gpt-4o")
    assert exc_info.value.provider == "openai"


def test_resolve_workspace_credential_never_sees_another_workspaces_key(db: Session) -> None:
    workspace_a = _make_workspace(db, "Workspace A")
    workspace_b = _make_workspace(db, "Workspace B")
    _save_key(db, workspace_a, "openai", "sk-workspaceAkey1111")
    _save_key(db, workspace_b, "openai", "sk-workspaceBkey2222")

    assert resolve_workspace_credential(db, workspace_a, "gpt-4o") == "sk-workspaceAkey1111"
    assert resolve_workspace_credential(db, workspace_b, "gpt-4o") == "sk-workspaceBkey2222"


# ---------------------------------------------------------------------------
# complete_with_workspace_credentials — scoping into complete()
# ---------------------------------------------------------------------------


def test_scoped_credential_reaches_litellm_as_a_direct_kwarg_not_an_env_var(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _make_workspace(db)
    _save_key(db, workspace, "openai", "sk-scopedplaintext1111")

    captured: dict = {}

    def fake_completion(**kwargs):
        # The critical assertion: at the moment LiteLLM's own completion()
        # is invoked, the workspace's decrypted key is present as the
        # `api_key` kwarg...
        captured.update(kwargs)
        # ...and is NOT sitting in the process environment (proves this
        # mechanism never mutated global/shared state to get the key here).
        assert "OPENAI_API_KEY" not in os.environ
        return _fake_response()

    monkeypatch.setattr("refract_core.llm.client.litellm.completion", fake_completion)

    result = complete_with_workspace_credentials(
        db, workspace, "gpt-4o", [{"role": "user", "content": "hi"}]
    )

    assert captured["api_key"] == "sk-scopedplaintext1111"
    assert result.content == "hi"


def test_scoped_credential_never_leaks_into_the_environment(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before, during (asserted above), and after a scoped call, the
    credential must never appear in os.environ — this is what makes
    "cleanup" a non-issue for this mechanism: there is nothing to clean up.
    """
    workspace = _make_workspace(db)
    _save_key(db, workspace, "openai", "sk-shouldneverleak1111")

    assert "OPENAI_API_KEY" not in os.environ

    monkeypatch.setattr(
        "refract_core.llm.client.litellm.completion", lambda **kwargs: _fake_response()
    )
    complete_with_workspace_credentials(
        db, workspace, "gpt-4o", [{"role": "user", "content": "hi"}]
    )

    assert "OPENAI_API_KEY" not in os.environ


def test_scoped_credential_not_leaked_to_a_subsequent_unrelated_call(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later, completely unrelated `complete()` call in the same process
    (e.g. a different request that never resolved a workspace credential
    at all) must not accidentally pick up a previous call's scoped key —
    it should behave exactly as if no workspace credential mechanism
    exists (i.e. hit the real "missing API key" pre-flight check).
    """
    from refract_core.llm.client import MissingAPIKeyError, complete

    workspace = _make_workspace(db)
    _save_key(db, workspace, "openai", "sk-firstcallkey1111")

    monkeypatch.setattr(
        "refract_core.llm.client.litellm.completion", lambda **kwargs: _fake_response()
    )
    complete_with_workspace_credentials(
        db, workspace, "gpt-4o", [{"role": "user", "content": "hi"}]
    )

    # A plain complete() call with no scoped credential and no env var set
    # must still raise MissingAPIKeyError — proving the first call's key
    # left no trace behind for this second, unrelated call to stumble on.
    with pytest.raises(MissingAPIKeyError):
        complete("gpt-4o", [{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# Concurrency safety: two workspaces' keys must never cross streams
# ---------------------------------------------------------------------------


def test_two_workspaces_scoped_calls_never_see_each_others_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drives two calls for two different workspaces with genuinely
    overlapping `litellm.completion()` invocations (forced via a
    threading.Barrier so both are truly in flight at once, not just
    issued back-to-back) and asserts each call's `api_key` kwarg matches
    only its own workspace's key. Because the credential is a local
    variable threaded through the call stack (never `os.environ`, never
    any object shared between calls — see refract_api.llm_context's
    module docstring), this holds regardless of thread interleaving; this
    test demonstrates that rather than merely asserting it.

    Deliberately does NOT use the module's `db` fixture here: that fixture
    is an in-memory SQLite engine on `StaticPool` — a single shared
    connection object. Two threads issuing genuinely concurrent queries
    against one shared SQLite connection (even via two separate ORM
    Sessions) is a real race at the driver level, not just an ORM
    concern, and was flaky in practice (intermittent IndexError /
    UnknownLLMError from a corrupted cursor state, not a credential
    leak). A file-backed SQLite DB gives each thread's own engine/session
    a genuinely independent connection, so this test's flakiness comes
    only from what it's actually trying to test, not from shared test
    plumbing underneath it.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrency-test.db'}")
    Base.metadata.create_all(engine)
    setup_session = sessionmaker(bind=engine)()
    try:
        workspace_a = _make_workspace(setup_session, "Workspace A")
        workspace_b = _make_workspace(setup_session, "Workspace B")
        _save_key(setup_session, workspace_a, "openai", "sk-workspaceAkey1111")
        _save_key(setup_session, workspace_b, "openai", "sk-workspaceBkey2222")
        workspace_a_id, workspace_b_id = workspace_a.id, workspace_b.id
    finally:
        setup_session.close()

    barrier = threading.Barrier(2, timeout=5)
    lock = threading.Lock()
    seen: list[tuple[str, str]] = []  # (message content, api_key seen by litellm)

    def fake_completion(**kwargs):
        barrier.wait()  # force both in-flight calls to overlap in time
        with lock:
            seen.append((kwargs["messages"][0]["content"], kwargs["api_key"]))
        return _fake_response()

    monkeypatch.setattr("refract_core.llm.client.litellm.completion", fake_completion)

    errors: list[BaseException] = []

    def call(workspace_id: int, tag: str) -> None:
        try:
            # Each thread gets its own engine, not just its own session -
            # a real multi-request server wouldn't share a connection
            # across requests either (see refract_api.db.get_db).
            thread_engine = create_engine(f"sqlite:///{tmp_path / 'concurrency-test.db'}")
            thread_session = sessionmaker(bind=thread_engine)()
            try:
                workspace = thread_session.get(models.Workspace, workspace_id)
                complete_with_workspace_credentials(
                    thread_session,
                    workspace,
                    "gpt-4o",
                    [{"role": "user", "content": tag}],
                )
            finally:
                thread_session.close()
                thread_engine.dispose()
        except BaseException as exc:  # noqa: BLE001 - surfaced via `errors` below
            errors.append(exc)

    thread_a = threading.Thread(
        target=call, args=(workspace_a_id, "prompt-from-workspace-a")
    )
    thread_b = threading.Thread(
        target=call, args=(workspace_b_id, "prompt-from-workspace-b")
    )
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=10)
    thread_b.join(timeout=10)

    assert not errors, f"unexpected error(s) in worker threads: {errors}"
    assert len(seen) == 2
    seen_by_tag = dict(seen)
    assert seen_by_tag["prompt-from-workspace-a"] == "sk-workspaceAkey1111"
    assert seen_by_tag["prompt-from-workspace-b"] == "sk-workspaceBkey2222"
