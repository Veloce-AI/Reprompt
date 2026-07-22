"""Model capability registry — a thin layer on top of LiteLLM's own metadata.

Per ``reprompt-master-build-prompt.md`` §2 ("litellm for all model calls +
registry") and ``reprompt-parity-engine-plan.md`` §3/§6 ("Model cards:
registry layer, versioned... Base: LiteLLM model_prices_and_context_window.json
+ custom layer..."), this module answers cheap per-model questions —
does this model support JSON mode? Tool use? What does it cost per token?
Does it need an API key at all? — by leaning on what LiteLLM already
exposes (``litellm.get_model_info``, ``litellm.get_supported_openai_params``,
``litellm.supports_function_calling``, ``litellm.validate_environment``)
rather than hand-rolling a second copy of that data.

This is deliberately **not** the full M3 "model card" system (mechanical
prompt-rewrite rules per model family, e.g. "XML tags for Claude, markdown
headers for Gemini") — that is explicitly later work per the master build
prompt's build order. This module only exposes coarse yes/no/number
capability facts for today's callers (the not-yet-built rubric generator
and LLM judge, plus this package's own :mod:`reprompt_core.llm.client`).

Zero FastAPI imports, per the working rules for ``packages/core``.
"""

from __future__ import annotations

from dataclasses import dataclass

import litellm

__all__ = [
    "ModelCapabilities",
    "get_model_capabilities",
    "supports_json_mode",
    "missing_credential_env_vars",
]

# Providers LiteLLM routes to a local/self-hosted endpoint by convention
# (default ``http://localhost:11434`` for Ollama, a user-supplied
# ``api_base`` for vLLM's OpenAI-compatible server, ...). These never
# require an API key — per the task's own examples ("ollama/llama3" for
# local). Kept as an explicit small set rather than inferred, since
# "local vs. cloud" isn't something LiteLLM's env-var check can answer on
# its own (a cloud key that happens to already be set in the environment
# looks identical to "no key needed" from that check alone).
_NO_KEY_PROVIDERS = frozenset({"ollama", "ollama_chat", "vllm"})

# Env vars LiteLLM's ``validate_environment`` reports as "missing" that are
# infra/config plumbing (endpoint URLs, region-ish config) rather than a
# secret credential. A local/self-hosted model (ollama, vllm, ...) typically
# reports one of these as "missing" even though no key is required at all —
# it just means "using the default endpoint". We don't want that to trip a
# MissingAPIKeyError for local models, so any missing env var ending in one
# of these suffixes is not treated as a credential requirement.
_NON_CREDENTIAL_ENV_SUFFIXES = ("_API_BASE", "_BASE_URL", "_ENDPOINT")


def missing_credential_env_vars(model: str) -> list[str]:
    """Env vars that look like a genuinely-missing credential for ``model``.

    Wraps ``litellm.validate_environment(model)``, which already knows the
    per-provider env var convention (``OPENAI_API_KEY``,
    ``ANTHROPIC_API_KEY``, ``GEMINI_API_KEY``/``GOOGLE_API_KEY``, ...) —
    this function does not reinvent that mapping. It only filters the
    result down to entries that look like a secret credential (as opposed
    to e.g. ``OLLAMA_API_BASE``, which LiteLLM lists as "missing" for every
    local Ollama model even though no key is needed).

    Returns an empty list if nothing looks missing, which is the expected
    result for local/self-hosted model strings (``ollama/...``,
    ``vllm/...``) that have no credential requirement at all. Never raises:
    if LiteLLM can't classify the model string, this returns ``[]`` rather
    than guessing — the actual API call will surface a clear error itself
    if something really is missing.
    """
    try:
        result = litellm.validate_environment(model)
    except Exception:
        return []
    if result.get("keys_in_environment"):
        return []
    return [key for key in result.get("missing_keys", []) if not key.endswith(_NON_CREDENTIAL_ENV_SUFFIXES)]


def _provider_name(model: str) -> str | None:
    try:
        return litellm.get_llm_provider(model)[1]
    except Exception:
        return None


def supports_json_mode(model: str) -> bool:
    """Whether LiteLLM reports ``response_format`` as a supported param for ``model``.

    Used both by :mod:`reprompt_core.llm.client` (to fail fast with a clear
    error instead of an opaque provider error) and directly by callers that
    want to branch ahead of time (e.g. the future rubric generator choosing
    between JSON mode and a prompted-JSON fallback).
    """
    try:
        supported = litellm.get_supported_openai_params(model=model)
    except Exception:
        return False
    return "response_format" in (supported or [])


@dataclass(frozen=True)
class ModelCapabilities:
    """Coarse capability facts about one LiteLLM model string.

    Every field degrades to a conservative default (``False``/``None``)
    rather than raising if LiteLLM doesn't have data for the model —
    an unrecognized or brand-new model string should not crash the
    caller, it should just come back with fewer known facts.
    """

    model: str
    provider: str | None
    supports_json_mode: bool
    supports_function_calling: bool
    max_input_tokens: int | None
    max_output_tokens: int | None
    input_cost_per_token: float | None
    output_cost_per_token: float | None
    requires_api_key: bool
    """False for local/self-hosted models (ollama, vllm, ...) that LiteLLM
    can call without any credential in the environment. True for every
    cloud provider, regardless of whether the key is currently set — this
    describes the *model*, not the current environment (use
    :func:`missing_credential_env_vars` to check the environment)."""
    supports_reasoning: bool
    """Whether the model has a genuine extended-thinking/reasoning mode
    invocable via LiteLLM's ``thinking=``/``reasoning_effort=`` params
    (e.g. Claude's ``thinking`` param, an o-series/gpt-5-class model's
    ``reasoning_effort``) — sourced from LiteLLM's own
    ``get_model_info()["supports_reasoning"]``, same pattern as every
    other field here. Hand-overridden to ``False`` for local providers in
    :data:`_NO_KEY_PROVIDERS` regardless of what LiteLLM reports: LiteLLM
    permissively forwards the ``reasoning_effort`` OpenAI-compat param to
    Ollama's chat API even though Ollama has no first-class reasoning-mode
    concept the way OpenAI/Anthropic/Gemini do, and this flag was observed
    to disagree with :attr:`supports_function_calling` between two Ollama
    models with otherwise-identical capability profiles — a sign it's
    param-passthrough leniency, not a genuine capability signal, for this
    provider family specifically."""


def get_model_capabilities(model: str) -> ModelCapabilities:
    """Look up coarse capability facts for a LiteLLM model string.

    Never raises: each underlying LiteLLM lookup is independently guarded,
    so a model LiteLLM only partially recognizes still returns a
    :class:`ModelCapabilities` with whatever facts were available and
    conservative defaults for the rest.
    """
    provider = _provider_name(model)

    try:
        supports_tools = bool(litellm.supports_function_calling(model=model))
    except Exception:
        supports_tools = False

    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    input_cost_per_token: float | None = None
    output_cost_per_token: float | None = None
    reasoning: bool = False
    try:
        info = litellm.get_model_info(model)
        max_input_tokens = info.get("max_input_tokens")
        max_output_tokens = info.get("max_output_tokens")
        input_cost_per_token = info.get("input_cost_per_token")
        output_cost_per_token = info.get("output_cost_per_token")
        reasoning = bool(info.get("supports_reasoning"))
    except Exception:
        pass  # unrecognized model: leave the cost/context/reasoning fields at defaults

    # See ModelCapabilities.supports_reasoning's docstring: LiteLLM's raw
    # flag for local providers is param-passthrough leniency, not a real
    # capability signal, so it's overridden regardless of what was found.
    if provider in _NO_KEY_PROVIDERS:
        reasoning = False

    return ModelCapabilities(
        model=model,
        provider=provider,
        supports_json_mode=supports_json_mode(model),
        supports_function_calling=supports_tools,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        input_cost_per_token=input_cost_per_token,
        output_cost_per_token=output_cost_per_token,
        requires_api_key=provider not in _NO_KEY_PROVIDERS,
        supports_reasoning=reasoning,
    )
