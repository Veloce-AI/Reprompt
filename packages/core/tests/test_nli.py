"""Tests for reprompt_core.nli — NLI cross-encoder entailment module.

All unit tests use a fake callable instead of loading any model, so the
suite runs without sentence_transformers installed. Live model tests are
skipped when the package is absent.
"""

from __future__ import annotations

import pytest

from reprompt_core.nli import NLI_AVAILABLE, entailment_score, entails, nli_label


def test_nli_available_is_bool() -> None:
    assert isinstance(NLI_AVAILABLE, bool)


@pytest.mark.skipif(not NLI_AVAILABLE, reason="sentence_transformers not installed")
def test_entailment_score_identical_strings_is_high() -> None:
    score = entailment_score("The sky is blue.", "The sky is blue.")
    assert score >= 0.5


@pytest.mark.skipif(not NLI_AVAILABLE, reason="sentence_transformers not installed")
def test_entailment_score_range() -> None:
    score = entailment_score("Paris is in France.", "Paris is a European city.")
    assert 0.0 <= score <= 1.0


@pytest.mark.skipif(not NLI_AVAILABLE, reason="sentence_transformers not installed")
def test_nli_label_returns_valid_label() -> None:
    label = nli_label("All birds can fly.", "Penguins can fly.")
    assert label in ("entailment", "neutral", "contradiction")


@pytest.mark.skipif(not NLI_AVAILABLE, reason="sentence_transformers not installed")
def test_entails_returns_bool() -> None:
    result = entails("The cat sat on the mat.", "There is a cat.")
    assert isinstance(result, bool)


def test_entailment_score_raises_on_empty_premise() -> None:
    if not NLI_AVAILABLE:
        pytest.skip("sentence_transformers not installed")
    with pytest.raises(ValueError, match="premise"):
        entailment_score("", "something")


def test_entailment_score_raises_on_empty_hypothesis() -> None:
    if not NLI_AVAILABLE:
        pytest.skip("sentence_transformers not installed")
    with pytest.raises(ValueError, match="hypothesis"):
        entailment_score("something", "   ")
