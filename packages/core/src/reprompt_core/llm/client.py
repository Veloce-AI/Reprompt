"""Provider-agnostic BYOK completion wrapper around LiteLLM.

Per ``reprompt-master-build-prompt.md`` working rule 6 ("Never hardcode API
keys. All model access is BYOK via env/user-supplied keys through LiteLLM")
and §2 (stack: "litellm for all model calls + registry"), this module is
the *only* place ``packages/core`` talks to a model provider. Every future
LLM-powered piece — the rubric generator, the LLM judge, the M3 optimizer
loop — calls :func:`complete`, not ``litellm`` directly.

Provider-agnostic by construction
----------------------------------
The user explicitly asked for this to work with "any API provider or local
also" rather than pin one BYOK provider. Nothing in this module special-
cases OpenAI/Anthropic/Gemini/etc. — ``model`` is just a LiteLLM model
string (``"gpt-4o"``, ``"claude-sonnet-4-5"``, ``"gemini/gemini-2.0-flash"``,
``"ollama/llama3"``, ``"vllm/..."``, ...) and LiteLLM's own routing +
env-var convention decides where the call goes and which credential (if
any) it reads. See :mod:`reprompt_core.llm.registry` for the thin capability
layer this module leans on for JSON-mode support and credential checks.

Keys are never accepted as function arguments
-----------------------------------------------
There is deliberately no public ``api_key=`` parameter on :func:`complete`.
LiteLLM already reads the standard per-provider env var
(``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, ``GEMINI_API_KEY``,
``AWS_ACCESS_KEY_ID``, ...) automatically — this wrapper does not reinvent
that mapping, and refuses to add a code path where a key could flow
through a *public* function argument (and, from there, a log line or
stack trace some request-logging middleware writes by dumping kwargs).
Local/self-hosted models (``ollama/...``, ``vllm/...``) need no key at all
and are handled gracefully — see
:func:`reprompt_core.llm.registry.missing_credential_env_vars`.

The one narrow exception is ``_scoped_api_key`` (leading underscore,
keyword-only, absent from every example/doc above): an internal escape
hatch for ``apps/api``'s per-request BYOK credential scoping
(``reprompt_api.llm_context``), which resolves a *workspace's* encrypted,
DB-stored key and must hand it to LiteLLM for exactly one call without
ever touching the process environment (see that module's docstring for
the full concurrency reasoning — env-var injection is not safe across
concurrent requests for different workspaces in this multi-tenant
service). It is intentionally named and documented to be unmistakably
different from a public ``api_key=`` a caller might reach for out of
habit and have logged. Nothing in ``packages/core`` itself ever sets it.

Error categories
-----------------
Callers (the future rubric generator / optimizer loop) need to make a
retry-or-not decision without parsing exception text, so every error
:func:`complete` can raise is one of exactly two shapes:

* :class:`TransientLLMError` — rate limits, timeouts, connection blips,
  5xx-ish provider errors. Safe to retry (ideally with backoff); a second
  identical call may well succeed.
* :class:`PermanentLLMError` (and its subclasses
  :class:`MissingAPIKeyError`, :class:`AuthenticationLLMError`,
  :class:`UnsupportedFeatureError`) — the request will not succeed as-is.
  Retrying the identical call is pointless; something about the request,
  credentials, or model choice needs to change first.

:class:`UnknownLLMError` exists for the rare case LiteLLM raises something
this module doesn't recognize — it is intentionally its own category
(not silently folded into "permanent") rather than guessed at.

Zero FastAPI imports, per the working rules for ``packages/core``.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import litellm
from litellm import exceptions as litellm_exceptions
from pydantic import BaseModel

from reprompt_core.llm.registry import missing_credential_env_vars, supports_json_mode
from reprompt_core.trace import TokenUsage

__all__ = [
    "Message",
    "LLMResponse",
    "complete",
    "RepromptLLMError",
    "MissingAPIKeyError",
    "AuthenticationLLMError",
    "TransientLLMError",
    "PermanentLLMError",
    "UnsupportedFeatureError",
    "UnknownLLMError",
]

Message = Mapping[str, Any]
"""A single chat message, e.g. ``{"role": "user", "content": "..."}`` —
standard OpenAI-style chat format, which LiteLLM normalizes to whatever the
target provider actually expects."""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RepromptLLMError(Exception):
    """Base class for every error :func:`complete` raises.

    Never raised directly — catch this to mean "something went wrong
    talking to a model provider", or catch one of the more specific
    subclasses below to make a retry decision. See the module docstring
    for the retryable/non-retryable split.
    """


class TransientLLMError(RepromptLLMError):
    """Rate limit, timeout, connection blip, or transient provider error.

    Safe to retry, ideally with backoff — the same request may succeed on
    a later attempt.
    """


class PermanentLLMError(RepromptLLMError):
    """The request will not succeed as-is; retrying it unchanged is pointless.

    Covers bad model names, malformed requests, context-length overruns,
    content-policy rejections, and unsupported parameters. See
    :class:`MissingAPIKeyError`, :class:`AuthenticationLLMError`, and
    :class:`UnsupportedFeatureError` for the more actionable subtypes.
    """


class MissingAPIKeyError(PermanentLLMError):
    """No credential is present in the environment for this model's provider.

    Raised *before* any network call is made (see :func:`complete`), so
    this is the fast, clear failure mode for the most common real-world
    BYOK mistake — forgetting to set a key — rather than a provider's own
    (often much less clear) authentication error surfacing several seconds
    later.
    """

    def __init__(self, provider: str | None, env_vars: Sequence[str]) -> None:
        provider_label = provider or "this model"
        vars_label = ", ".join(env_vars) if env_vars else "the required API key"
        message = f"No API key found for provider '{provider_label}'. Set {vars_label}."
        super().__init__(message)
        self.provider = provider
        self.env_vars = tuple(env_vars)


class AuthenticationLLMError(PermanentLLMError):
    """A credential was present but the provider rejected it.

    Distinct from :class:`MissingAPIKeyError` (no key set at all) because
    the fix is different — the key that *is* set is wrong, revoked, or
    lacks permission for this model, not merely absent.
    """


class UnsupportedFeatureError(PermanentLLMError):
    """The request asked for a feature this model/provider doesn't support.

    Currently only raised for ``response_format`` (structured/JSON-mode
    output) requested against a model LiteLLM doesn't report
    ``response_format`` support for. Raised before any network call —
    see :func:`complete`.
    """


class UnknownLLMError(RepromptLLMError):
    """LiteLLM raised something this module doesn't have a mapping for.

    Deliberately its own category rather than being folded into
    :class:`PermanentLLMError` — this module would rather say "not sure,
    look closer" than guess wrong about whether a retry could help.
    """


# Exception categories, most-specific-first within each tuple where it
# matters. litellm/openai's hierarchy: RateLimitError, Timeout,
# APIConnectionError, ServiceUnavailableError, and InternalServerError are
# all distinct branches (not subclasses of one another) so order between
# them is not significant. AuthenticationError and PermissionDeniedError
# are likewise distinct branches. BadRequestError's subclasses
# (ContextWindowExceededError, ContentPolicyViolationError,
# UnsupportedParamsError) and NotFoundError/UnprocessableEntityError are
# all "this exact request will not work" errors.
_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    litellm_exceptions.RateLimitError,
    litellm_exceptions.Timeout,
    litellm_exceptions.APIConnectionError,
    litellm_exceptions.ServiceUnavailableError,
    litellm_exceptions.InternalServerError,
)
_AUTH_EXCEPTIONS: tuple[type[Exception], ...] = (
    litellm_exceptions.AuthenticationError,
    litellm_exceptions.PermissionDeniedError,
)
_PERMANENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    litellm_exceptions.BadRequestError,
    litellm_exceptions.NotFoundError,
    litellm_exceptions.UnprocessableEntityError,
)


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMResponse:
    """A typed, parsed result from :func:`complete` — never LiteLLM's raw response.

    ``usage`` reuses :class:`reprompt_core.trace.TokenUsage` (the same
    ``tokens{in, out, thinking}`` shape a :class:`~reprompt_core.trace.StageRecord`
    carries) rather than inventing a parallel token-count type, since this
    is exactly the accounting a future "replay this call as a stage" path
    would want to record.
    """

    content: str
    """The model's text output. Empty string if the model returned no content
    (e.g. a tool-call-only response) rather than ``None``, so callers can
    always treat this as a string."""

    model: str
    """The model actually used, as reported back by the provider response
    (falls back to the requested model string if the response didn't echo
    one back)."""

    provider: str | None
    """The LiteLLM provider this model routed to (``"openai"``, ``"anthropic"``,
    ``"ollama"``, ...), or ``None`` if it couldn't be determined."""

    usage: TokenUsage
    cost_usd: float | None
    """Computed via ``litellm.completion_cost()``. ``None`` if cost could not
    be computed at all (unexpected error). ``0.0`` covers two distinct cases
    LiteLLM does not itself distinguish: a genuinely free/local call, or a
    model LiteLLM has no pricing data for — treat ``0.0`` from an unfamiliar
    cloud model with suspicion, but it is always accurate for local models."""

    latency_ms: float
    """Wall-clock time for the ``litellm.completion()`` call, in milliseconds."""

    finish_reason: str | None


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------


def _provider_name(model: str) -> str | None:
    try:
        return litellm.get_llm_provider(model)[1]
    except Exception:
        return None


def complete(
    model: str,
    messages: Sequence[Message],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: type[BaseModel] | dict[str, Any] | None = None,
    timeout: float | None = None,
    _scoped_api_key: str | None = None,
    **extra_params: Any,
) -> LLMResponse:
    """Make a single provider-agnostic completion call via LiteLLM.

    Parameters
    ----------
    model:
        A LiteLLM model string — e.g. ``"gpt-4o"``, ``"claude-sonnet-4-5"``,
        ``"gemini/gemini-2.0-flash"``, ``"ollama/llama3"``. This function
        never special-cases a provider; LiteLLM's own ``provider/model``
        convention decides where the call routes.
    messages:
        Standard chat-format messages: ``[{"role": "user", "content": "..."}, ...]``.
    temperature, max_tokens:
        Passed through to LiteLLM if given; omitted from the request
        entirely (provider default applies) if left ``None``.
    response_format:
        A Pydantic model class or a raw ``{"type": "json_object", ...}``
        dict to request structured/JSON output, for models that support it
        (see :func:`reprompt_core.llm.registry.supports_json_mode`). Raises
        :class:`UnsupportedFeatureError` *before* making a network call if
        the model doesn't support it — callers that want to try anyway
        (e.g. a prompted-JSON fallback with manual parsing) should catch
        that and not pass ``response_format`` on retry.
    timeout:
        Per-call timeout in seconds, passed through to LiteLLM.
    _scoped_api_key:
        Internal use only — see the module docstring's "Keys are never
        accepted as function arguments" section. When given, this exact
        call uses this credential (passed straight to LiteLLM as its own
        ``api_key`` kwarg) instead of consulting the environment at all,
        and the environment-credential pre-flight check below is skipped
        entirely for this call.
    **extra_params:
        Any other LiteLLM ``completion()`` keyword argument (``top_p``,
        ``stop``, ``tools``, ``seed``, ...) — passed through unmodified.

    Returns
    -------
    :class:`LLMResponse`

    Raises
    ------
    :class:`MissingAPIKeyError`
        No credential found in the environment for this model's provider
        (only checked when ``_scoped_api_key`` is not given). Never
        reaches the network — see the module docstring.
    :class:`UnsupportedFeatureError`
        ``response_format`` was requested but this model doesn't support it.
    :class:`AuthenticationLLMError`
        A credential was present but the provider rejected it.
    :class:`TransientLLMError`
        Rate limit / timeout / connection / transient server error — safe
        to retry.
    :class:`PermanentLLMError`
        Bad model name, malformed request, context length exceeded,
        content policy rejection, or unsupported parameter — retrying the
        identical request will not help.
    :class:`UnknownLLMError`
        An error LiteLLM raised that this module doesn't have a mapping
        for.
    """
    if _scoped_api_key is None:
        missing = missing_credential_env_vars(model)
        if missing:
            raise MissingAPIKeyError(_provider_name(model), missing)
    # else: a credential was supplied directly for this one call (see
    # `_scoped_api_key`'s docstring above) — the environment-based
    # pre-flight check would incorrectly report "missing" for a workspace
    # key that was never written to `os.environ` in the first place, so it
    # is skipped. LiteLLM itself will still raise a real authentication
    # error below if this credential turns out to be invalid.

    if response_format is not None and not supports_json_mode(model):
        raise UnsupportedFeatureError(
            f"Model '{model}' does not appear to support structured/JSON "
            "response_format (LiteLLM reports no 'response_format' support "
            "for this model). Omit response_format and parse the model's "
            "free-text output instead, or choose a model that supports it."
        )

    params: dict[str, Any] = {"model": model, "messages": list(messages), **extra_params}
    if temperature is not None:
        params["temperature"] = temperature
    if max_tokens is not None:
        params["max_tokens"] = max_tokens
    if response_format is not None:
        params["response_format"] = response_format
    if timeout is not None:
        params["timeout"] = timeout
    if _scoped_api_key is not None:
        # LiteLLM's own `completion()` accepts `api_key` as a plain
        # per-call keyword argument, independent of the env-var
        # convention — this never touches `os.environ`, so it carries no
        # cross-request/cross-workspace leakage risk (see
        # reprompt_api.llm_context for the full reasoning on the caller
        # side). Set last so nothing above can silently override it.
        params["api_key"] = _scoped_api_key

    start = time.monotonic()
    try:
        response = litellm.completion(**params)
    except _AUTH_EXCEPTIONS as exc:
        raise AuthenticationLLMError(
            f"Provider rejected the credentials for model '{model}': {exc}"
        ) from exc
    except _TRANSIENT_EXCEPTIONS as exc:
        raise TransientLLMError(
            f"Transient error calling model '{model}' (safe to retry): {exc}"
        ) from exc
    except _PERMANENT_EXCEPTIONS as exc:
        raise PermanentLLMError(
            f"Request to model '{model}' will not succeed as-is: {exc}"
        ) from exc
    except litellm_exceptions.APIError as exc:
        raise UnknownLLMError(f"Unrecognized provider error calling model '{model}': {exc}") from exc
    except Exception as exc:  # belt-and-braces: never leak a raw LiteLLM/library traceback
        raise UnknownLLMError(f"Unexpected error calling model '{model}': {exc}") from exc
    latency_ms = (time.monotonic() - start) * 1000

    choice = response.choices[0]
    content = choice.message.content or ""
    finish_reason = getattr(choice, "finish_reason", None)

    usage_obj = response.usage
    thinking_tokens: int | None = None
    details = getattr(usage_obj, "completion_tokens_details", None)
    if details is not None:
        thinking_tokens = getattr(details, "reasoning_tokens", None)
    usage = TokenUsage(
        input=usage_obj.prompt_tokens,
        output=usage_obj.completion_tokens,
        thinking=thinking_tokens,
    )

    try:
        cost_usd: float | None = litellm.completion_cost(completion_response=response, model=model)
    except Exception:
        cost_usd = None

    return LLMResponse(
        content=content,
        model=getattr(response, "model", None) or model,
        provider=_provider_name(model),
        usage=usage,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        finish_reason=finish_reason,
    )
