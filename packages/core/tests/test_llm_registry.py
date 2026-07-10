"""Tests for the model capability registry (refract_core.llm.registry).

This is a thin layer over LiteLLM's own model metadata (see the module
docstring in ``refract_core/llm/registry.py``), so most of these tests
exercise it against real LiteLLM data (no network calls — LiteLLM's model
metadata is a bundled static table) rather than mocking LiteLLM itself.
The filtering logic (credential vs. non-credential env vars) is tested
directly against a mocked ``litellm.validate_environment`` so it doesn't
depend on any particular provider's current env-var list.
"""

from __future__ import annotations

import pytest

from refract_core.llm.registry import (
    ModelCapabilities,
    get_model_capabilities,
    missing_credential_env_vars,
    supports_json_mode,
)


# ---------------------------------------------------------------------------
# missing_credential_env_vars
# ---------------------------------------------------------------------------


def test_missing_credential_env_vars_for_cloud_model_with_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert missing_credential_env_vars("gpt-4o") == ["OPENAI_API_KEY"]


def test_missing_credential_env_vars_empty_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-for-test-only")
    assert missing_credential_env_vars("gpt-4o") == []


def test_missing_credential_env_vars_empty_for_local_ollama_model() -> None:
    """The concrete case the task calls out: local models must not require
    a key to be present."""
    assert missing_credential_env_vars("ollama/llama3") == []


def test_missing_credential_env_vars_empty_for_local_vllm_model() -> None:
    assert missing_credential_env_vars("vllm/my-local-model") == []


def test_missing_credential_env_vars_filters_non_credential_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit test of the filter itself, independent of any real provider's
    current env-var list: an env var that's clearly infra config (a base
    URL), not a secret, must never show up as a "missing credential"."""

    def fake_validate_environment(model):
        return {
            "keys_in_environment": False,
            "missing_keys": ["SOME_PROVIDER_API_BASE", "SOME_PROVIDER_API_KEY"],
        }

    monkeypatch.setattr("refract_core.llm.registry.litellm.validate_environment", fake_validate_environment)

    assert missing_credential_env_vars("some/model") == ["SOME_PROVIDER_API_KEY"]


def test_missing_credential_env_vars_never_raises_for_unrecognized_model() -> None:
    # Should degrade to [] rather than raising, per the module's contract.
    result = missing_credential_env_vars("totally-not-a-real-model-xyz-123")
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# supports_json_mode
# ---------------------------------------------------------------------------


def test_supports_json_mode_true_for_gpt4o() -> None:
    assert supports_json_mode("gpt-4o") is True


def test_supports_json_mode_never_raises_for_unrecognized_model() -> None:
    assert supports_json_mode("totally-not-a-real-model-xyz-123") is False


# ---------------------------------------------------------------------------
# get_model_capabilities
# ---------------------------------------------------------------------------


def test_get_model_capabilities_for_known_cloud_model() -> None:
    caps = get_model_capabilities("gpt-4o")

    assert isinstance(caps, ModelCapabilities)
    assert caps.model == "gpt-4o"
    assert caps.provider == "openai"
    assert caps.supports_json_mode is True
    assert caps.requires_api_key is True
    assert caps.max_input_tokens is not None and caps.max_input_tokens > 0
    assert caps.input_cost_per_token is not None and caps.input_cost_per_token > 0


def test_get_model_capabilities_for_local_ollama_model() -> None:
    caps = get_model_capabilities("ollama/llama3")

    assert caps.provider == "ollama"
    assert caps.requires_api_key is False


def test_get_model_capabilities_for_local_vllm_model() -> None:
    caps = get_model_capabilities("vllm/my-local-model")

    assert caps.provider == "vllm"
    assert caps.requires_api_key is False


def test_get_model_capabilities_degrades_gracefully_for_unknown_model() -> None:
    """An unrecognized model string must come back with conservative
    defaults, never raise — per the module's documented contract."""
    caps = get_model_capabilities("totally-not-a-real-model-xyz-123")

    assert isinstance(caps, ModelCapabilities)
    assert caps.model == "totally-not-a-real-model-xyz-123"
    assert caps.supports_json_mode is False
    assert caps.supports_function_calling is False
    assert caps.max_input_tokens is None
    assert caps.output_cost_per_token is None
    # Unknown model: conservative default is "assume a key is required"
    # rather than silently treating it as free/local.
    assert caps.requires_api_key is True


def test_get_model_capabilities_provider_agnostic_across_families() -> None:
    """No provider is special-cased — the same function works uniformly
    across OpenAI/Anthropic/Gemini-style model strings, per the explicit
    "provider-agnostic... modular" product requirement."""
    for model in ["gpt-4o", "claude-sonnet-4-5", "gemini/gemini-2.0-flash"]:
        caps = get_model_capabilities(model)
        assert caps.provider is not None
        assert caps.requires_api_key is True
