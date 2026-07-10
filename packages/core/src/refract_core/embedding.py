"""Embedding-similarity half of the evaluation engine.

Per refract-parity-engine-plan.md §3 ("Evaluation Engine"), a stage's score
is a weighted blend::

    Score = w1 * deterministic + w2 * LLM-judge + w3 * embedding-sim

This module owns the ``embedding-sim`` term: a local, no-API-key-needed
measure of how semantically similar a candidate stage output is to the
benchmark stage output for that stage. "Local" is a deliberate product
choice (plan §10, open question 2) — it keeps the on-prem story clean,
since a customer running fully air-gapped shouldn't need an embeddings API
call just to score a candidate.

This module has **zero FastAPI imports** — per the working rules,
``packages/core`` must stay runnable headless/CLI.

Model
-----
The default model is ``BAAI/bge-m3`` (per plan §2 and §10 — this was an
explicit, already-decided choice, not something this module should
relitigate). It is a ~2GB download on first use and slow-ish to load
on CPU; see ``model_name`` below for how to override it (e.g. for a fast
test suite — this module does not swap the default for you).

Score
-----
``score()`` returns cosine similarity between the two texts' embeddings,
clamped to ``[0.0, 1.0]``. Cosine similarity is mathematically in
``[-1, 1]``, but for natural-language sentence embeddings from the same
model, near-zero-or-negative values only ever show up for genuinely
unrelated text — there's no meaningful distinction between "unrelated"
and "opposite" for this use case, so clamping the (rare) negative tail to
0 keeps the score compatible with the ``w1*det + w2*judge + w3*embed``
blend, where all three terms are expected to live on a common 0-1 scale.
1.0 is the ceiling: identical text embeds to itself with cosine
similarity 1.0 (up to floating-point noise, which clamping also absorbs).

Empty input
-----------
An empty (or whitespace-only) string has no well-defined semantic
embedding, and silently scoring it (e.g. returning 0.0) would mask a real
upstream bug — a stage that produced no output at all is a different
failure mode than a stage whose output is merely dissimilar. So
``score()`` raises ``ValueError`` naming which side (benchmark/candidate)
was empty, rather than returning a number.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "EmbeddingSimilarityScorer",
    "embedding_similarity",
]

DEFAULT_EMBEDDING_MODEL: Final[str] = "BAAI/bge-m3"
"""Default local embedding model, per refract-parity-engine-plan.md §2/§10.

Deliberately just a string constant, not hardwired into the class below,
so callers (and tests) can override it per-instance without touching this
module. Do not change this default to speed up tests — override
``EmbeddingSimilarityScorer.model_name`` at the call site instead."""


@lru_cache(maxsize=None)
def _load_model(model_name: str) -> "SentenceTransformer":
    """Load and cache a SentenceTransformer by name.

    ``lru_cache`` gives us a process-wide singleton per ``model_name`` for
    free — the (potentially multi-GB) model is downloaded/loaded once no
    matter how many :class:`EmbeddingSimilarityScorer` instances or
    ``score()`` calls request it. The import is local to this function so
    that importing ``refract_core.embedding`` (or ``refract_core`` as a
    whole) never pays the ``sentence_transformers`` -> ``torch`` import
    cost unless embedding scoring is actually used.
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(frozen=True)
class EmbeddingSimilarityScorer:
    """Scores semantic similarity between a benchmark and candidate output.

    ``model_name`` defaults to :data:`DEFAULT_EMBEDDING_MODEL` (bge-m3) but
    is freely overridable — e.g. tests use a much smaller/faster
    sentence-transformers model so the suite doesn't pay bge-m3's load
    time on every run. See module docstring for the score range and empty
    -string policy.
    """

    model_name: str = DEFAULT_EMBEDDING_MODEL

    def score(self, benchmark_output: str, candidate_output: str) -> float:
        """Cosine similarity between the two texts' embeddings, in [0, 1].

        Raises ``ValueError`` if either input is empty or whitespace-only.
        """
        if not benchmark_output.strip():
            raise ValueError("embedding_similarity: benchmark_output is empty")
        if not candidate_output.strip():
            raise ValueError("embedding_similarity: candidate_output is empty")

        from sentence_transformers import util

        model = _load_model(self.model_name)
        embeddings = model.encode(
            [benchmark_output, candidate_output],
            convert_to_tensor=True,
            normalize_embeddings=True,
        )
        raw_similarity = float(util.cos_sim(embeddings[0], embeddings[1])[0][0])
        return _clamp01(raw_similarity)


def embedding_similarity(
    benchmark_output: str,
    candidate_output: str,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
) -> float:
    """Module-level convenience wrapper around :class:`EmbeddingSimilarityScorer`.

    Equivalent to ``EmbeddingSimilarityScorer(model_name).score(...)``. The
    underlying model is still cached process-wide (see :func:`_load_model`),
    so calling this repeatedly with the same ``model_name`` does not reload
    the model.
    """
    return EmbeddingSimilarityScorer(model_name=model_name).score(
        benchmark_output, candidate_output
    )
