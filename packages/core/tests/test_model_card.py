"""Tests for the model-card transform layer (reprompt_core.llm.model_card).

Per the module's own contract (see its docstring): every transform here is
a pure, deterministic text rewrite — no LLM call, no network, no I/O, no
API key required. These tests exercise real transform *content* (assert on
the actual rewritten text), not just "it ran without error", per the task
that built this module.
"""

from __future__ import annotations

import ast
import inspect

from reprompt_core.llm import model_card
from reprompt_core.llm.model_card import (
    FamilyCard,
    TransformRule,
    applicable_rules,
    apply_model_card_transform,
    get_transform_rules,
    is_small_variant,
    resolve_family,
)

# ---------------------------------------------------------------------------
# Family resolution
# ---------------------------------------------------------------------------


def test_resolve_family_openai() -> None:
    assert resolve_family("gpt-4o") == "openai"


def test_resolve_family_anthropic() -> None:
    assert resolve_family("claude-sonnet-4-5") == "anthropic"


def test_resolve_family_gemini_with_provider_prefix() -> None:
    assert resolve_family("gemini/gemini-2.0-flash") == "gemini"


def test_resolve_family_llama_open_source_local() -> None:
    """The task's own concrete example: a local Ollama model resolves to
    the open-source/"llama" bucket."""
    assert resolve_family("ollama/llama3") == "llama"


def test_resolve_family_open_weight_marker_wins_over_aggregator_provider() -> None:
    """An open-weight model served through an aggregator (groq) still
    resolves by model name, not by lumping every groq-served model into
    one bucket."""
    assert resolve_family("groq/llama3-70b-8192") == "llama"
    assert resolve_family("together_ai/mistralai/Mixtral-8x7B-Instruct-v0.1") == "llama"


def test_resolve_family_azure_openai_folds_into_openai() -> None:
    """Documented lump: Azure OpenAI hosts the same underlying OpenAI
    models under a different provider string."""
    assert resolve_family("azure/gpt-4o") == "openai"


def test_resolve_family_claude_via_bedrock_still_anthropic() -> None:
    """Name-sniffing must win over provider-based mapping so a Claude
    model hosted on a non-Anthropic provider string still gets Claude's
    prompting rules."""
    assert resolve_family("bedrock/anthropic.claude-3-sonnet-20240229-v1:0") == "anthropic"


def test_resolve_family_falls_back_to_generic_for_unmapped_provider() -> None:
    """A real provider (Cohere) with no specific rule set hits the
    documented fallback rather than being mis-lumped into another family."""
    assert resolve_family("cohere/command-r-plus") == "generic"


def test_resolve_family_falls_back_to_generic_for_unknown_model_string() -> None:
    assert resolve_family("totally-not-a-real-model-xyz-123") == "generic"


def test_resolve_family_never_raises() -> None:
    # Empty string / garbage input must degrade, not raise.
    assert isinstance(resolve_family(""), str)
    assert isinstance(resolve_family("///"), str)


# ---------------------------------------------------------------------------
# Small/"nano" variant detection
# ---------------------------------------------------------------------------


def test_is_small_variant_true_for_mini_suffix() -> None:
    assert is_small_variant("gpt-4o-mini") is True


def test_is_small_variant_true_for_haiku() -> None:
    assert is_small_variant("claude-3-5-haiku-20241022") is True


def test_is_small_variant_true_for_flash_lite() -> None:
    assert is_small_variant("gemini-2.0-flash-lite") is True


def test_is_small_variant_true_for_small_param_count() -> None:
    assert is_small_variant("ollama/llama3:8b") is True


def test_is_small_variant_false_for_large_param_count() -> None:
    assert is_small_variant("ollama/llama3:70b") is False


def test_is_small_variant_false_for_flagship_models() -> None:
    assert is_small_variant("gpt-4o") is False
    assert is_small_variant("claude-sonnet-4-5") is False


def test_is_small_variant_does_not_false_positive_on_gemini_name() -> None:
    """Regression guard: a naive substring check for "mini" wrongly
    matches inside "gemini" itself. Word-boundary matching must reject
    this."""
    assert is_small_variant("gemini/gemini-2.0-flash") is False
    assert is_small_variant("gemini-1.5-pro") is False


# ---------------------------------------------------------------------------
# Registry structure / versioning
# ---------------------------------------------------------------------------


def test_get_transform_rules_returns_versioned_family_card() -> None:
    card = get_transform_rules("anthropic")
    assert isinstance(card, FamilyCard)
    assert card.family == "anthropic"
    assert isinstance(card.version, int)
    assert card.version >= 1
    assert len(card.rules) > 0
    assert all(isinstance(rule, TransformRule) for rule in card.rules)


def test_get_transform_rules_falls_back_to_generic_for_unknown_family() -> None:
    assert get_transform_rules("not-a-real-family") is get_transform_rules("generic")


def test_every_registered_family_has_a_version() -> None:
    for family in ("anthropic", "gemini", "openai", "llama", "generic"):
        card = get_transform_rules(family)
        assert card.version >= 1
        assert card.description  # non-empty, human-readable


def test_generic_family_has_no_structural_rule() -> None:
    """Sensible default per the task: families with no specific rules only
    get the universal small-model normalization, never a structural
    rewrite."""
    card = get_transform_rules("generic")
    assert all(rule.name == "terseify_if_small" for rule in card.rules)


def test_applicable_rules_gates_small_only_rules_by_size() -> None:
    large_rules = [rule.name for rule in applicable_rules("claude-sonnet-4-5")]
    small_rules = [rule.name for rule in applicable_rules("claude-3-5-haiku-20241022")]

    assert "terseify_if_small" not in large_rules
    assert "xml_wrap_sections" in large_rules

    assert "terseify_if_small" in small_rules
    assert "xml_wrap_sections" in small_rules


# ---------------------------------------------------------------------------
# Anthropic: XML-tag structuring (real, content-level assertions)
# ---------------------------------------------------------------------------

_STRUCTURED_PROMPT = """Instructions:
Answer using only the provided context. Do not speculate.

Context:
The customer's order #A123 shipped yesterday.

Examples:
Q: Where is my order? A: Your order shipped yesterday."""


def test_anthropic_transform_wraps_sections_in_xml_tags() -> None:
    result = apply_model_card_transform(_STRUCTURED_PROMPT, "claude-sonnet-4-5")

    assert "<instructions>" in result and "</instructions>" in result
    assert "<context>" in result and "</context>" in result
    assert "<example>" in result and "</example>" in result
    assert "Answer using only the provided context. Do not speculate." in result
    assert "The customer's order #A123 shipped yesterday." in result
    # No markdown headers should appear for a Claude target.
    assert "## " not in result


def test_anthropic_transform_is_noop_on_unstructured_prose() -> None:
    prose = "Just answer the question directly, in one sentence."
    assert apply_model_card_transform(prose, "claude-sonnet-4-5") == prose


# ---------------------------------------------------------------------------
# Gemini: markdown-header structuring (real, content-level assertions)
# ---------------------------------------------------------------------------


def test_gemini_transform_uses_markdown_headers_not_xml() -> None:
    result = apply_model_card_transform(_STRUCTURED_PROMPT, "gemini/gemini-2.0-flash")

    assert "## Instructions" in result
    assert "## Context" in result
    assert "## Examples" in result
    assert "Answer using only the provided context. Do not speculate." in result
    assert "<instructions>" not in result
    assert "<context>" not in result


def test_gemini_transform_converts_existing_xml_tags_to_markdown() -> None:
    """A prompt already authored with Claude-style XML tags (e.g. carried
    over from a previous migration) gets un-XML'd for a Gemini target."""
    xml_prompt = "<instructions>\nAnswer concisely.\n</instructions>\n\n<example>\nQ: 1+1 A: 2\n</example>"

    result = apply_model_card_transform(xml_prompt, "gemini/gemini-2.0-flash")

    assert "## Instructions" in result
    assert "## Examples" in result
    assert "Answer concisely." in result
    assert "<instructions>" not in result
    assert "<example>" not in result


def test_gemini_transform_is_noop_on_unstructured_prose() -> None:
    prose = "Just answer the question directly, in one sentence."
    assert apply_model_card_transform(prose, "gemini/gemini-2.0-flash") == prose


# ---------------------------------------------------------------------------
# Nano/small models: real compression, not a no-op stub
# ---------------------------------------------------------------------------


def test_nano_model_transform_compresses_verbose_instructions() -> None:
    verbose = (
        "Please make sure to always respond in JSON format. "
        "It is important that you include all required fields. "
        "Kindly avoid extra commentary."
    )

    result = apply_model_card_transform(verbose, "gpt-4o-mini")

    # Filler/hedging phrases must actually be gone, not just reworded.
    assert "please" not in result.lower()
    assert "kindly" not in result.lower()
    assert "it is important that you" not in result.lower()
    # Each instruction becomes a terse imperative bullet.
    assert result == (
        "- Always respond in JSON format.\n"
        "- Include all required fields.\n"
        "- Avoid extra commentary."
    )
    # The result must genuinely be shorter than the input.
    assert len(result) < len(verbose)


def test_nano_model_transform_does_not_apply_to_flagship_model() -> None:
    verbose = "Please make sure to always respond in JSON format. It is important that you include all fields."
    result = apply_model_card_transform(verbose, "gpt-4o")
    assert result == verbose  # openai family has no structural rule and is not "small"


def test_nano_model_transform_leaves_single_sentence_unbulleted() -> None:
    result = apply_model_card_transform("Please respond concisely.", "gpt-4o-mini")
    assert result == "Respond concisely."


def test_nano_and_structural_rules_compose_for_small_family_specific_model() -> None:
    """A small Claude model (Haiku) is both "nano" and "anthropic" — it
    should get compression *and* XML structuring, not one at the expense
    of the other."""
    result = apply_model_card_transform(_STRUCTURED_PROMPT, "claude-3-5-haiku-20241022")

    assert "<instructions>" in result
    assert "<context>" in result
    assert "- " in result  # compression produced bullet points inside a section
    assert "please" not in result.lower()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_transform_is_deterministic_across_repeated_calls() -> None:
    for target in ("claude-sonnet-4-5", "gemini/gemini-2.0-flash", "gpt-4o-mini", "ollama/llama3"):
        first = apply_model_card_transform(_STRUCTURED_PROMPT, target)
        second = apply_model_card_transform(_STRUCTURED_PROMPT, target)
        assert first == second


def test_transform_is_deterministic_and_idempotent_for_xml_wrap() -> None:
    """Applying the same rule twice to an already-transformed prompt
    should not corrupt it further (headers are already tags, not
    "Label:" lines, so the second pass is a no-op)."""
    once = apply_model_card_transform(_STRUCTURED_PROMPT, "claude-sonnet-4-5")
    twice = apply_model_card_transform(once, "claude-sonnet-4-5")
    assert once == twice


# ---------------------------------------------------------------------------
# Purity: no LLM calls, no network, no side effects
# ---------------------------------------------------------------------------


def test_module_never_imports_or_calls_the_llm_client() -> None:
    """Cheap enforcement that this stayed mechanical: parse the module's
    actual import statements (not just grep prose/comments/docstrings,
    which legitimately *mention* reprompt_core.llm.client to explain what
    this module is not) and assert none of them pull in the LLM client or
    `complete`. Also asserts the module namespace never bound `complete`
    and that `litellm.completion` (the one call that would hit a network/
    provider) is never referenced anywhere in the source."""
    source = inspect.getsource(model_card)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported_names.add(module)
            imported_names.update(f"{module}.{alias.name}" for alias in node.names)

    assert not any("llm.client" in name or name == "complete" for name in imported_names)
    assert not hasattr(model_card, "complete")
    assert "litellm.completion" not in source


def test_transform_requires_no_api_key(monkeypatch) -> None:  # noqa: ANN001
    """No credential of any kind should be needed to run a transform —
    it never reaches litellm.completion / any network call."""
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    result = apply_model_card_transform(_STRUCTURED_PROMPT, "claude-sonnet-4-5")
    assert "<instructions>" in result
