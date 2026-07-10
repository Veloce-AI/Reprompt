"""Tests for the embedding-similarity evaluator (refract_core.embedding).

Model choice for this suite
----------------------------
The product default is ``BAAI/bge-m3`` (see refract_core/embedding.py and
refract-parity-engine-plan.md §2/§10) and stays the default in the
module — this suite does NOT change that. But bge-m3 is a ~2GB download
and slow to load on CPU, which is impractical to pay on every test run.
So these tests explicitly pass a much smaller, fast model,
``sentence-transformers/all-MiniLM-L6-v2`` (~90MB, seconds to load), via
the ``model_name`` override that ``EmbeddingSimilarityScorer`` exposes
for exactly this reason. Only the *tests* swap models; production code
that doesn't pass ``model_name`` still gets bge-m3.
"""

from __future__ import annotations

import pytest

from refract_core.embedding import EmbeddingSimilarityScorer

TEST_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@pytest.fixture(scope="module")
def scorer() -> EmbeddingSimilarityScorer:
    return EmbeddingSimilarityScorer(model_name=TEST_MODEL)


def test_identical_strings_score_near_one(scorer: EmbeddingSimilarityScorer) -> None:
    text = "The invoice total is $1,204.50, due on the 15th of next month."
    score = scorer.score(text, text)
    assert score == pytest.approx(1.0, abs=1e-4)


def test_near_identical_strings_score_high(scorer: EmbeddingSimilarityScorer) -> None:
    benchmark = "The customer's order was shipped on Tuesday and should arrive by Friday."
    candidate = "The customer's order shipped on Tuesday and will arrive by Friday."
    score = scorer.score(benchmark, candidate)
    assert score > 0.9


def test_unrelated_strings_score_low(scorer: EmbeddingSimilarityScorer) -> None:
    benchmark = "The quarterly revenue grew 12% driven by strong enterprise renewals."
    candidate = "Photosynthesis converts sunlight, water, and carbon dioxide into glucose."
    score = scorer.score(benchmark, candidate)
    assert score < 0.5


def test_score_is_clamped_to_unit_interval(scorer: EmbeddingSimilarityScorer) -> None:
    pairs = [
        ("hello world", "hello world"),
        ("hello world", "goodbye moon"),
        ("The cat sat on the mat.", "Quarterly tax filings are due in April."),
    ]
    for benchmark, candidate in pairs:
        score = scorer.score(benchmark, candidate)
        assert 0.0 <= score <= 1.0


def test_score_is_symmetric(scorer: EmbeddingSimilarityScorer) -> None:
    a = "Approve the migration once parity exceeds 95%."
    b = "Once parity exceeds 95%, approve the migration."
    assert scorer.score(a, b) == pytest.approx(scorer.score(b, a), abs=1e-6)


def test_empty_benchmark_output_raises(scorer: EmbeddingSimilarityScorer) -> None:
    with pytest.raises(ValueError, match="benchmark_output is empty"):
        scorer.score("", "some candidate text")


def test_whitespace_only_benchmark_output_raises(scorer: EmbeddingSimilarityScorer) -> None:
    with pytest.raises(ValueError, match="benchmark_output is empty"):
        scorer.score("   \n\t  ", "some candidate text")


def test_empty_candidate_output_raises(scorer: EmbeddingSimilarityScorer) -> None:
    with pytest.raises(ValueError, match="candidate_output is empty"):
        scorer.score("some benchmark text", "")


def test_both_empty_raises_on_benchmark_first(scorer: EmbeddingSimilarityScorer) -> None:
    with pytest.raises(ValueError, match="benchmark_output is empty"):
        scorer.score("", "")


def test_model_is_cached_across_scorer_instances(scorer: EmbeddingSimilarityScorer) -> None:
    """Two scorers with the same model_name must share the underlying model.

    This exercises the module-level lru_cache singleton directly, so we
    know a second EmbeddingSimilarityScorer(model_name=...) doesn't
    trigger a second (slow) model load.
    """
    from refract_core.embedding import _load_model

    other_scorer = EmbeddingSimilarityScorer(model_name=TEST_MODEL)
    assert _load_model(scorer.model_name) is _load_model(other_scorer.model_name)


def test_module_level_convenience_function_matches_class() -> None:
    from refract_core.embedding import embedding_similarity

    a, b = "Refract migrates LLM pipelines.", "Refract migrates pipelines between LLMs."
    direct = embedding_similarity(a, b, model_name=TEST_MODEL)
    via_class = EmbeddingSimilarityScorer(model_name=TEST_MODEL).score(a, b)
    assert direct == pytest.approx(via_class, abs=1e-9)
