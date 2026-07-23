"""Tests for reprompt_core.llm.code_sample — see that module's docstring.

Real reprompt_core.llm.registry data is used (same convention as
test_llm_registry.py / test_model_select.py — LiteLLM's bundled model
metadata, no network call), so assertions below rely on real, stable
capability facts (e.g. claude-sonnet-4-5 supports reasoning, gpt-4o does
not).
"""

from __future__ import annotations

import ast
import inspect

from reprompt_core.llm import code_sample
from reprompt_core.llm.code_sample import generate_code_sample
from reprompt_core.llm.registry import get_model_capabilities


def test_includes_real_model_string() -> None:
    caps = get_model_capabilities("gpt-4o")
    result = generate_code_sample(caps)
    assert '"gpt-4o"' in result


def test_includes_tools_when_supported() -> None:
    caps = get_model_capabilities("gpt-4o")
    assert caps.supports_function_calling is True  # confirm the premise
    result = generate_code_sample(caps)
    assert "tools=" in result
    assert "omitted" not in result.split("tools=")[0].split("\n")[-1]


def test_omits_tools_when_not_supported() -> None:
    caps = get_model_capabilities("ollama/qwen2.5:14b")
    assert caps.supports_function_calling is False  # confirm the premise
    result = generate_code_sample(caps)
    assert "# tools= omitted" in result


def test_includes_thinking_for_reasoning_model() -> None:
    caps = get_model_capabilities("claude-sonnet-4-5")
    assert caps.supports_reasoning is True  # confirm the premise
    result = generate_code_sample(caps)
    assert "thinking=" in result
    assert "reasoning_effort" in result


def test_omits_thinking_for_non_reasoning_model() -> None:
    caps = get_model_capabilities("gpt-4o")
    assert caps.supports_reasoning is False  # confirm the premise
    result = generate_code_sample(caps)
    assert "# thinking= / reasoning_effort= omitted" in result


def test_omits_thinking_for_ollama_despite_raw_litellm_flag() -> None:
    # registry.py hand-overrides this to False for Ollama - confirm the
    # code sample respects that override, not a raw LiteLLM flag.
    caps = get_model_capabilities("ollama/llama3.1")
    assert caps.supports_reasoning is False  # confirm the override held
    result = generate_code_sample(caps)
    assert "# thinking= / reasoning_effort= omitted" in result


def test_uses_plain_litellm_not_the_internal_package() -> None:
    # reprompt_core is this project's own internal package - a Reprompt
    # user's codebase has no reason to have it installed, or want to
    # depend on it. The sample must be directly usable by an external
    # caller with nothing more than `pip install litellm` - see the
    # module's own docstring for why.
    caps = get_model_capabilities("gpt-4o")
    result = generate_code_sample(caps)
    assert "import litellm" in result
    assert "litellm.completion(" in result
    assert "reprompt_core" not in result


# ---------------------------------------------------------------------------
# Purity: no LLM calls, no network, no side effects
# ---------------------------------------------------------------------------


def test_module_never_calls_the_llm_client() -> None:
    """Same enforcement pattern as test_model_card.py's equivalent test —
    this module renders a call as text, it must never make one. Checked via
    imports (not a raw substring search): the generated *text* legitimately
    contains the literal string "litellm.completion(" now (see
    test_uses_plain_litellm_not_the_internal_package), so the only way to
    tell "renders text mentioning a call" apart from "actually imports and
    could make one" is to confirm neither `litellm` nor
    `reprompt_core.llm.client` is ever imported by this module itself."""
    source = inspect.getsource(code_sample)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported_names.add(module)
            imported_names.update(f"{module}.{alias.name}" for alias in node.names)

    assert not any("llm.client" in name for name in imported_names)
    assert "litellm" not in imported_names
