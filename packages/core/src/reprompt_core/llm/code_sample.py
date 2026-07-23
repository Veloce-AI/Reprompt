"""Working invocation code sample generator — one per model family.

Answers a different question from :mod:`reprompt_core.llm.model_card`
(prompt-text rewriting) and :mod:`reprompt_core.llm.registry` (capability
facts): *given a model string, what does a real call to it look like for
someone outside this codebase?* Deliberately generates plain
``litellm.completion()`` calls, not ``reprompt_core.llm.client.complete()``
— ``reprompt_core`` is this project's own internal package, not something
a Reprompt user's codebase has installed or would want to depend on. Every
curated model this project supports is reachable by any external caller
with nothing more than ``pip install litellm``, so that's what the sample
shows — the exact library this codebase's own :func:`reprompt_core.llm.
client.complete` is itself a thin wrapper around (see that function's own
``litellm.completion(**params)`` call). Pure text-in/text-out — no LLM
call, no I/O, no randomness, same discipline as
:mod:`reprompt_core.llm.model_card` (see that module's own docstring;
this module never imports or calls :func:`reprompt_core.llm.client.
complete`, only reads facts from :func:`reprompt_core.llm.registry.
get_model_capabilities` and :func:`reprompt_core.llm.model_card.
resolve_family`).

Why generated, not hand-written per model
-------------------------------------------------------------------------
The actual code differs only by (a) the model string and (b) whether
``tools=``/``thinking=`` are meaningful for that model — both already
known facts (:mod:`reprompt_core.llm.registry`'s ``supports_function_calling``/
``supports_reasoning``, sourced live from LiteLLM). Hand-writing one
snippet per curated model would mean 8 near-duplicate strings to keep in
sync by hand every time a model's capabilities change; generating from
already-live facts means this module never goes stale on its own, the
same reasoning already applied to why :mod:`reprompt_core.llm.model_select`
avoids a second hand-curated cost table.

Ollama/local-provider note
-------------------------------------------------------------------------
``tools=``/``thinking=`` are omitted from the generated sample for local
providers (see :data:`reprompt_core.llm.registry._NO_KEY_PROVIDERS`)
regardless of what the raw capability flags say — see
:class:`reprompt_core.llm.registry.ModelCapabilities`'s ``supports_reasoning``
docstring for why those flags are unreliable for this provider family
specifically. This module trusts the already-overridden
``ModelCapabilities`` it's given, it does not re-derive the override.
"""

from __future__ import annotations

from reprompt_core.llm.registry import ModelCapabilities

__all__ = ["generate_code_sample"]

_EXAMPLE_TOOL = """[{"type": "function", "function": {
        "name": "get_weather",
        "description": "Get current weather for a location",
        "parameters": {"type": "object", "properties": {"location": {"type": "string"}}, "required": ["location"]},
    }}]"""


def generate_code_sample(caps: ModelCapabilities) -> str:
    """Render a working ``complete()`` call for one model.

    Parameters
    ----------
    caps:
        The model's already-resolved capability facts (from
        :func:`reprompt_core.llm.registry.get_model_capabilities`) — this
        function trusts them as given, it does not call LiteLLM itself.
    """
    lines = [
        "import litellm",
        "",
        "response = litellm.completion(",
        f'    model="{caps.model}",',
        '    messages=[{"role": "user", "content": "..."}],',
    ]

    if caps.supports_function_calling:
        lines.append(f"    tools={_EXAMPLE_TOOL},")
    else:
        lines.append("    # tools= omitted — not supported for this model.")

    if caps.supports_reasoning:
        lines.append(
            '    thinking={"type": "enabled", "budget_tokens": 1024},'
            "  # or reasoning_effort=\"low\"|\"medium\"|\"high\""
        )
    else:
        lines.append("    # thinking= / reasoning_effort= omitted — not a reasoning-tier model.")

    lines.append(")")

    if caps.supports_reasoning:
        lines.append("# Reasoning-token usage: response.usage.thinking (see reprompt_core.trace.TokenUsage).")

    return "\n".join(lines)
