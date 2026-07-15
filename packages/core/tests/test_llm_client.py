"""Tests for the BYOK completion wrapper (reprompt_core.llm.client).

No real network calls to a paid provider
------------------------------------------
There is no API key configured in this environment (by design — this is
infrastructure for BYOK keys the user hasn't supplied yet, per the task
this module was built for). Every test that exercises the "happy path"
mocks ``litellm.completion`` directly via ``monkeypatch`` and asserts on
(a) what request our wrapper built and handed to LiteLLM, and (b) how it
parsed LiteLLM's response back into an :class:`LLMResponse` — this is real
coverage of our own logic, not of LiteLLM's or a provider's behavior.

The "missing API key" tests are deliberately *not* mocked at the
``missing_credential_env_vars`` layer — they run the real LiteLLM
``validate_environment`` check against a real cloud model string with no
key in the environment (this environment has none set for any cloud
provider), which is exactly the real-world path a BYOK user hits before
they've configured anything.

See ``test_llm_ollama_live.py`` for the local/live-model story: this
environment has no Ollama server running, so those tests are skipped, not
faked.
"""

from __future__ import annotations

import os

import pytest
from litellm import exceptions as litellm_exceptions
from litellm.types.utils import Choices, CompletionTokensDetailsWrapper, Message as LiteLLMMessage, ModelResponse, Usage

from reprompt_core.llm.client import (
    AuthenticationLLMError,
    LLMResponse,
    MissingAPIKeyError,
    PermanentLLMError,
    TransientLLMError,
    UnknownLLMError,
    UnsupportedFeatureError,
    complete,
)
from reprompt_core.trace import TokenUsage


def _fake_response(
    *,
    model: str = "gpt-4o-2024-08-06",
    content: str = "hello from the model",
    prompt_tokens: int = 20,
    completion_tokens: int = 7,
    reasoning_tokens: int | None = None,
    finish_reason: str = "stop",
) -> ModelResponse:
    """Build a real litellm ModelResponse (not a Mock) so parsing logic in
    `complete()` is exercised against the actual shape LiteLLM returns."""
    details = None
    if reasoning_tokens is not None:
        details = CompletionTokensDetailsWrapper(reasoning_tokens=reasoning_tokens)
    return ModelResponse(
        id="chatcmpl-test",
        created=0,
        model=model,
        object="chat.completion",
        choices=[
            Choices(
                finish_reason=finish_reason,
                index=0,
                message=LiteLLMMessage(content=content, role="assistant"),
            )
        ],
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            completion_tokens_details=details,
        ),
    )


@pytest.fixture(autouse=True)
def _no_real_cloud_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Belt-and-braces: strip any cloud provider key from the environment
    for the duration of every test in this module, so these tests can never
    accidentally make (and be charged for) a real network call regardless
    of what's in the developer's shell."""
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Request building (mocked litellm.completion)
# ---------------------------------------------------------------------------


def test_builds_request_with_required_fields_only(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _fake_response()

    monkeypatch.setattr("reprompt_core.llm.client.litellm.completion", fake_completion)
    monkeypatch.setattr("reprompt_core.llm.client.missing_credential_env_vars", lambda model: [])

    complete("gpt-4o", [{"role": "user", "content": "hi"}])

    assert captured["model"] == "gpt-4o"
    assert captured["messages"] == [{"role": "user", "content": "hi"}]
    # Optional params that weren't passed must not appear at all (so the
    # provider default applies, rather than us sending an explicit None).
    assert "temperature" not in captured
    assert "max_tokens" not in captured
    assert "response_format" not in captured
    assert "timeout" not in captured


def test_builds_request_with_all_optional_params(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _fake_response()

    monkeypatch.setattr("reprompt_core.llm.client.litellm.completion", fake_completion)
    monkeypatch.setattr("reprompt_core.llm.client.missing_credential_env_vars", lambda model: [])
    monkeypatch.setattr("reprompt_core.llm.client.supports_json_mode", lambda model: True)

    complete(
        "gpt-4o",
        [{"role": "user", "content": "hi"}],
        temperature=0.2,
        max_tokens=512,
        response_format={"type": "json_object"},
        timeout=30.0,
        top_p=0.9,
        seed=7,
    )

    assert captured["temperature"] == 0.2
    assert captured["max_tokens"] == 512
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["timeout"] == 30.0
    # Arbitrary extra LiteLLM params pass through untouched.
    assert captured["top_p"] == 0.9
    assert captured["seed"] == 7


def test_never_accepts_api_key_as_a_function_argument() -> None:
    """`complete()` has no `api_key` parameter at all — passing one is a
    TypeError, not a silently-accepted footgun. This is a deliberate API
    shape per the "never hardcode/pass keys as plain args" working rule."""
    import inspect

    signature = inspect.signature(complete)
    assert "api_key" not in signature.parameters


# ---------------------------------------------------------------------------
# Response parsing (mocked litellm.completion)
# ---------------------------------------------------------------------------


def test_parses_content_model_and_finish_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "reprompt_core.llm.client.litellm.completion",
        lambda **kwargs: _fake_response(model="gpt-4o-2024-08-06", content="the answer is 42", finish_reason="stop"),
    )
    monkeypatch.setattr("reprompt_core.llm.client.missing_credential_env_vars", lambda model: [])

    result = complete("gpt-4o", [{"role": "user", "content": "what is the answer?"}])

    assert isinstance(result, LLMResponse)
    assert result.content == "the answer is 42"
    assert result.model == "gpt-4o-2024-08-06"  # the model LiteLLM actually reports, not the alias requested
    assert result.finish_reason == "stop"
    assert result.provider == "openai"


def test_parses_token_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "reprompt_core.llm.client.litellm.completion",
        lambda **kwargs: _fake_response(prompt_tokens=123, completion_tokens=45),
    )
    monkeypatch.setattr("reprompt_core.llm.client.missing_credential_env_vars", lambda model: [])

    result = complete("gpt-4o", [{"role": "user", "content": "hi"}])

    assert result.usage == TokenUsage(input=123, output=45, thinking=None)


def test_parses_reasoning_tokens_as_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "reprompt_core.llm.client.litellm.completion",
        lambda **kwargs: _fake_response(prompt_tokens=50, completion_tokens=200, reasoning_tokens=150),
    )
    monkeypatch.setattr("reprompt_core.llm.client.missing_credential_env_vars", lambda model: [])

    result = complete("gpt-4o", [{"role": "user", "content": "hi"}])

    assert result.usage.thinking == 150


def test_computes_cost_via_litellm_completion_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "reprompt_core.llm.client.litellm.completion",
        lambda **kwargs: _fake_response(model="gpt-4o-2024-08-06", prompt_tokens=1000, completion_tokens=1000),
    )
    monkeypatch.setattr("reprompt_core.llm.client.missing_credential_env_vars", lambda model: [])

    result = complete("gpt-4o", [{"role": "user", "content": "hi"}])

    # Real litellm.completion_cost() against real gpt-4o pricing data —
    # this is the one place we let a real (non-network) litellm computation
    # run, since it's exactly the cost-tracking story the product needs.
    assert result.cost_usd is not None
    assert result.cost_usd > 0.0


def test_cost_none_when_completion_cost_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "reprompt_core.llm.client.litellm.completion",
        lambda **kwargs: _fake_response(),
    )
    monkeypatch.setattr("reprompt_core.llm.client.missing_credential_env_vars", lambda model: [])

    def raising_cost(**kwargs):
        raise RuntimeError("pricing data unavailable")

    monkeypatch.setattr("reprompt_core.llm.client.litellm.completion_cost", raising_cost)

    result = complete("gpt-4o", [{"role": "user", "content": "hi"}])

    assert result.cost_usd is None


def test_latency_is_measured(monkeypatch: pytest.MonkeyPatch) -> None:
    import time as time_module

    def slow_completion(**kwargs):
        time_module.sleep(0.05)
        return _fake_response()

    monkeypatch.setattr("reprompt_core.llm.client.litellm.completion", slow_completion)
    monkeypatch.setattr("reprompt_core.llm.client.missing_credential_env_vars", lambda model: [])

    result = complete("gpt-4o", [{"role": "user", "content": "hi"}])

    # A generous lower bound rather than ~50.0 exactly: Windows' default
    # timer resolution can make time.sleep() return a few ms early.
    assert result.latency_ms >= 30.0


def test_empty_content_becomes_empty_string_not_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "reprompt_core.llm.client.litellm.completion",
        lambda **kwargs: _fake_response(content=""),
    )
    monkeypatch.setattr("reprompt_core.llm.client.missing_credential_env_vars", lambda model: [])

    result = complete("gpt-4o", [{"role": "user", "content": "hi"}])

    assert result.content == ""
    assert isinstance(result.content, str)


# ---------------------------------------------------------------------------
# Missing API key — the most likely real-world BYOK failure mode
# ---------------------------------------------------------------------------


def test_missing_api_key_raises_before_any_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def should_not_be_called(**kwargs):
        nonlocal called
        called = True
        return _fake_response()

    monkeypatch.setattr("reprompt_core.llm.client.litellm.completion", should_not_be_called)

    # No OPENAI_API_KEY is set anywhere in this process (see the autouse
    # fixture above) — this is the real reprompt_core.llm.registry check,
    # not a mock.
    with pytest.raises(MissingAPIKeyError) as exc_info:
        complete("gpt-4o", [{"role": "user", "content": "hi"}])

    assert called is False, "complete() must not reach litellm.completion when a key is missing"
    assert "OPENAI_API_KEY" in str(exc_info.value)
    assert "openai" in str(exc_info.value)
    assert exc_info.value.provider == "openai"
    assert "OPENAI_API_KEY" in exc_info.value.env_vars


def test_missing_api_key_message_matches_expected_shape() -> None:
    """Matches the exact actionable shape the task calls for: "No API key
    found for provider 'anthropic'. Set ANTHROPIC_API_KEY."."""
    with pytest.raises(MissingAPIKeyError, match=r"No API key found for provider 'anthropic'\. Set ANTHROPIC_API_KEY\."):
        complete("claude-sonnet-4-5", [{"role": "user", "content": "hi"}])


def test_local_model_never_raises_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """ollama/vllm-style local models must not require a key to be present,
    even though this environment genuinely has zero provider keys set."""
    monkeypatch.setattr(
        "reprompt_core.llm.client.litellm.completion",
        lambda **kwargs: _fake_response(model="ollama/llama3"),
    )

    # Must not raise MissingAPIKeyError.
    result = complete("ollama/llama3", [{"role": "user", "content": "hi"}])
    assert result.content


# ---------------------------------------------------------------------------
# Unsupported response_format — proactive, pre-network-call degradation
# ---------------------------------------------------------------------------


def test_unsupported_response_format_raises_before_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def should_not_be_called(**kwargs):
        nonlocal called
        called = True
        return _fake_response()

    monkeypatch.setattr("reprompt_core.llm.client.litellm.completion", should_not_be_called)
    monkeypatch.setattr("reprompt_core.llm.client.missing_credential_env_vars", lambda model: [])
    monkeypatch.setattr("reprompt_core.llm.client.supports_json_mode", lambda model: False)

    with pytest.raises(UnsupportedFeatureError, match="does not appear to support"):
        complete(
            "some-model-without-json-mode",
            [{"role": "user", "content": "hi"}],
            response_format={"type": "json_object"},
        )

    assert called is False


def test_response_format_omitted_never_checks_json_support(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the caller doesn't ask for response_format, JSON-mode support is
    irrelevant and must never be consulted (and never block the call)."""
    monkeypatch.setattr(
        "reprompt_core.llm.client.litellm.completion",
        lambda **kwargs: _fake_response(),
    )
    monkeypatch.setattr("reprompt_core.llm.client.missing_credential_env_vars", lambda model: [])

    def should_not_be_called(model):
        raise AssertionError("supports_json_mode should not be called when response_format is None")

    monkeypatch.setattr("reprompt_core.llm.client.supports_json_mode", should_not_be_called)

    complete("gpt-4o", [{"role": "user", "content": "hi"}])  # must not raise


# ---------------------------------------------------------------------------
# Error category mapping — retryable vs. not
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "litellm_exc_factory",
    [
        lambda: litellm_exceptions.RateLimitError(message="rate limited", llm_provider="openai", model="gpt-4o"),
        lambda: litellm_exceptions.Timeout(message="timed out", model="gpt-4o", llm_provider="openai"),
        lambda: litellm_exceptions.APIConnectionError(message="connection reset", llm_provider="openai", model="gpt-4o"),
        lambda: litellm_exceptions.ServiceUnavailableError(
            message="unavailable", llm_provider="openai", model="gpt-4o", response=None
        ),
        lambda: litellm_exceptions.InternalServerError(
            message="server error", llm_provider="openai", model="gpt-4o", response=None
        ),
    ],
    ids=["rate_limit", "timeout", "connection", "service_unavailable", "internal_server_error"],
)
def test_transient_provider_errors_map_to_transient_llm_error(monkeypatch, litellm_exc_factory) -> None:
    def raising_completion(**kwargs):
        raise litellm_exc_factory()

    monkeypatch.setattr("reprompt_core.llm.client.litellm.completion", raising_completion)
    monkeypatch.setattr("reprompt_core.llm.client.missing_credential_env_vars", lambda model: [])

    with pytest.raises(TransientLLMError) as exc_info:
        complete("gpt-4o", [{"role": "user", "content": "hi"}])

    assert exc_info.value.__cause__ is not None  # original litellm exception preserved via `raise ... from exc`


def test_auth_rejected_after_key_present_maps_to_authentication_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Distinct from MissingAPIKeyError: a key WAS present (per our
    pre-flight check) but the provider itself rejected it."""

    def raising_completion(**kwargs):
        raise litellm_exceptions.AuthenticationError(
            message="invalid api key", llm_provider="openai", model="gpt-4o"
        )

    monkeypatch.setattr("reprompt_core.llm.client.litellm.completion", raising_completion)
    monkeypatch.setattr("reprompt_core.llm.client.missing_credential_env_vars", lambda model: [])

    with pytest.raises(AuthenticationLLMError):
        complete("gpt-4o", [{"role": "user", "content": "hi"}])


@pytest.mark.parametrize(
    "litellm_exc_factory",
    [
        lambda: litellm_exceptions.BadRequestError(message="bad request", llm_provider="openai", model="gpt-4o"),
        lambda: litellm_exceptions.NotFoundError(message="model not found", llm_provider="openai", model="not-a-real-model"),
        lambda: litellm_exceptions.ContextWindowExceededError(message="too many tokens", llm_provider="openai", model="gpt-4o"),
        lambda: litellm_exceptions.ContentPolicyViolationError(message="blocked", llm_provider="openai", model="gpt-4o"),
    ],
    ids=["bad_request", "not_found", "context_window_exceeded", "content_policy"],
)
def test_permanent_provider_errors_map_to_permanent_llm_error(monkeypatch, litellm_exc_factory) -> None:
    def raising_completion(**kwargs):
        raise litellm_exc_factory()

    monkeypatch.setattr("reprompt_core.llm.client.litellm.completion", raising_completion)
    monkeypatch.setattr("reprompt_core.llm.client.missing_credential_env_vars", lambda model: [])

    with pytest.raises(PermanentLLMError):
        complete("gpt-4o", [{"role": "user", "content": "hi"}])


def test_unrecognized_error_maps_to_unknown_llm_error_not_silently_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def raising_completion(**kwargs):
        raise ValueError("something litellm-internal and unmapped")

    monkeypatch.setattr("reprompt_core.llm.client.litellm.completion", raising_completion)
    monkeypatch.setattr("reprompt_core.llm.client.missing_credential_env_vars", lambda model: [])

    with pytest.raises(UnknownLLMError) as exc_info:
        complete("gpt-4o", [{"role": "user", "content": "hi"}])

    assert isinstance(exc_info.value.__cause__, ValueError)


def test_transient_and_permanent_errors_are_distinguishable_by_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """The core promise callers rely on: a caller can `except TransientLLMError`
    to decide to retry, and that will never accidentally also catch a
    PermanentLLMError (bad model name) or vice versa."""
    assert not issubclass(TransientLLMError, PermanentLLMError)
    assert not issubclass(PermanentLLMError, TransientLLMError)
    assert issubclass(MissingAPIKeyError, PermanentLLMError)
    assert issubclass(AuthenticationLLMError, PermanentLLMError)
    assert issubclass(UnsupportedFeatureError, PermanentLLMError)
