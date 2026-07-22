"""Tests for reprompt_core.llm.model_select — see that module's docstring
for the algorithm (curated tier ∩ available, cost tiebreak within a tier,
explicit override, no-tier-match fallback, empty-available error).

Real reprompt_core.llm.registry data is used for cost lookups (same
convention as test_llm_registry.py — LiteLLM's model metadata is a bundled
static table, no network call), so tier ordering assertions below rely on
real, stable relative pricing (e.g. gpt-4o-mini is cheaper than gpt-4o).
"""

from __future__ import annotations

import pytest

from reprompt_core.llm.model_select import NoAvailableModelError, select_model


# ---------------------------------------------------------------------------
# Explicit override always wins
# ---------------------------------------------------------------------------


def test_explicit_override_wins_even_if_not_in_available_models() -> None:
    """"Don't second-guess" - an explicit choice is returned as-is, without
    being checked against available_models at all."""
    result = select_model(
        "rubric_generation",
        ["gpt-4o-mini"],
        explicit="some/totally-uncurated-model",
    )
    assert result == "some/totally-uncurated-model"


def test_explicit_override_wins_even_with_empty_available_models() -> None:
    result = select_model("rubric_generation", [], explicit="claude-sonnet-4-5")
    assert result == "claude-sonnet-4-5"


def test_no_explicit_falls_through_to_normal_selection() -> None:
    result = select_model("rubric_generation", ["gpt-4o-mini"], explicit=None)
    assert result == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Curated tier ∩ available
# ---------------------------------------------------------------------------


def test_picks_from_the_best_available_tier() -> None:
    """Tier 1 (claude-sonnet-4-5/gpt-4o/gemini-2.0-flash) beats tier 2
    (claude-haiku-4-5/gpt-4o-mini/...) when both are available."""
    result = select_model("rubric_generation", ["gpt-4o-mini", "claude-sonnet-4-5"])
    assert result == "claude-sonnet-4-5"


def test_falls_back_to_next_tier_when_top_tier_unavailable() -> None:
    """Only tier-2/tier-3 models are available - the top tier isn't offered
    at all, so the next tier down is used instead of raising."""
    result = select_model("rubric_generation", ["ollama/llama3.1", "gpt-4o-mini"])
    assert result == "gpt-4o-mini"


def test_ignores_models_outside_available_even_if_in_top_tier() -> None:
    """gpt-4o is tier 1 but not available; only claude-haiku-4-5 (tier 2) and
    an uncurated model are available - claude-haiku-4-5 must win, not gpt-4o
    (which isn't actually usable) and not the uncurated model (a curated
    tier match always beats the no-tier-match fallback)."""
    result = select_model("rubric_generation", ["claude-haiku-4-5", "some/uncurated-model"])
    assert result == "claude-haiku-4-5"


# ---------------------------------------------------------------------------
# Cost tiebreak among equally-capable (same-tier) options
# ---------------------------------------------------------------------------


def test_cost_tiebreak_within_a_tier_picks_the_cheaper_model() -> None:
    """claude-sonnet-4-5 and gpt-4o are both tier 1; gpt-4o-mini is
    deliberately NOT offered here so this isolates the *within-tier*
    tiebreak. Real registry pricing: gpt-4o is materially cheaper per-token
    than claude-sonnet-4-5 as of this writing - the exact cheaper one
    doesn't matter for the test's intent, just that the result is
    genuinely the cheaper of the two per live registry data."""
    from reprompt_core.llm.registry import get_model_capabilities

    a_cost = get_model_capabilities("claude-sonnet-4-5")
    b_cost = get_model_capabilities("gpt-4o")
    expected_cheaper = "claude-sonnet-4-5" if (
        (a_cost.input_cost_per_token or 0) + (a_cost.output_cost_per_token or 0)
    ) <= (
        (b_cost.input_cost_per_token or 0) + (b_cost.output_cost_per_token or 0)
    ) else "gpt-4o"

    result = select_model("rubric_generation", ["claude-sonnet-4-5", "gpt-4o"])
    assert result == expected_cheaper


def test_cost_tiebreak_treats_unknown_price_as_free() -> None:
    """Both ollama models (tier 3) have no vendor price data in LiteLLM's
    table - neither should be excluded or blow up the cost comparison, and
    a deterministic pick (not an error) must come back."""
    result = select_model("rubric_generation", ["ollama/llama3.1", "ollama/qwen2.5:14b"])
    assert result in {"ollama/llama3.1", "ollama/qwen2.5:14b"}


# ---------------------------------------------------------------------------
# No curated tier match at all -> cheapest-available fallback
# ---------------------------------------------------------------------------


def test_falls_back_to_cheapest_available_when_nothing_matches_any_tier() -> None:
    result = select_model("rubric_generation", ["some/uncurated-model"])
    assert result == "some/uncurated-model"


def test_fallback_among_multiple_uncurated_models_picks_cheapest() -> None:
    # gpt-4o-mini-transcribe is a real, cheap-but-different-purpose LiteLLM
    # model id not present in any curated tier - used here purely as "some
    # other real model LiteLLM has pricing data for" alongside a fictional
    # one with no pricing data at all (treated as free, so it wins).
    result = select_model("rubric_generation", ["gpt-4o-mini-transcribe", "totally-fictional-model-xyz"])
    assert result == "totally-fictional-model-xyz"


# ---------------------------------------------------------------------------
# Empty-available edge case
# ---------------------------------------------------------------------------


def test_empty_available_and_no_explicit_raises() -> None:
    with pytest.raises(NoAvailableModelError):
        select_model("rubric_generation", [])


def test_empty_available_error_message_names_the_purpose() -> None:
    with pytest.raises(NoAvailableModelError, match="judge"):
        select_model("judge", [])


# ---------------------------------------------------------------------------
# purpose is respected (all three declared purposes work end-to-end)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("purpose", ["rubric_generation", "judge", "mutator"])
def test_every_declared_purpose_selects_successfully(purpose: str) -> None:
    result = select_model(purpose, ["claude-sonnet-4-5", "gpt-4o-mini"])  # type: ignore[arg-type]
    assert result == "claude-sonnet-4-5"


# ---------------------------------------------------------------------------
# target_models: never self-grade, prefer cross-family for judge
# ---------------------------------------------------------------------------


def test_target_model_is_excluded_from_candidates() -> None:
    # gpt-4o-mini is normally the tier-2 pick, but it's the target here.
    result = select_model(
        "judge",
        ["claude-haiku-4-5", "gpt-4o-mini"],
        target_models=["gpt-4o-mini"],
    )
    assert result == "claude-haiku-4-5"


def test_only_target_models_available_raises() -> None:
    with pytest.raises(NoAvailableModelError):
        select_model("judge", ["gpt-4o-mini"], target_models=["gpt-4o-mini"])


def test_judge_prefers_cross_family_over_cheaper_same_family() -> None:
    # gpt-4o-mini is cheaper than claude-haiku-4-5, but shares a family
    # with the target (gpt-4o) - cross-family must win anyway.
    result = select_model(
        "judge",
        ["gpt-4o-mini", "claude-haiku-4-5"],
        target_models=["gpt-4o"],
    )
    assert result == "claude-haiku-4-5"


def test_judge_degrades_to_same_family_when_nothing_else_available() -> None:
    # Only openai-family candidates exist anywhere - must still return one
    # rather than raising, per the module's "some pick beats none" stance.
    result = select_model(
        "judge",
        ["gpt-4o-mini"],
        target_models=["gpt-4o"],
    )
    assert result == "gpt-4o-mini"


def test_mutator_does_not_apply_cross_family_preference() -> None:
    # Cross-family preference is judge-only per the doc; mutator only
    # excludes exact target_models matches, cost still breaks all ties.
    result = select_model(
        "mutator",
        ["gpt-4o-mini", "claude-haiku-4-5"],
        target_models=["gpt-4o"],
    )
    assert result == "gpt-4o-mini"
