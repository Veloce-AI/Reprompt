"""Local NLI cross-encoder — entailment scoring between two text strings.

Mirrors ``embedding.py``'s architecture exactly (D4 from the conflict flags):
- Zero FastAPI imports, zero ``call``/LLM dependency.
- Lazy-load via ``lru_cache`` so the first call pays the model-download cost,
  subsequent calls are free.
- Module-level ``DEFAULT_NLI_MODEL`` constant, freely overridable per-call so
  tests can inject a fake callable instead of loading any model at all.
- ``sentence_transformers`` / ``torch`` are optional heavy imports — guarded
  so the full suite runs without them (unit tests inject a fake ``entails``
  callable; live tests are skipped when the package is absent).

Usage in production:
    from reprompt_core.nli import entails, entailment_score
    score = entailment_score("Paris is in France", "Paris is a European city")
    # → float in [0, 1]

Usage in tests (no model, no download):
    # Pass a fake entails callable directly to cluster_by_meaning / mine_contract
    def exact_match(a, b): return a.strip() == b.strip()
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

__all__ = [
    "DEFAULT_NLI_MODEL",
    "NLI_AVAILABLE",
    "entailment_score",
    "nli_label",
    "entails",
]

DEFAULT_NLI_MODEL: Final[str] = "cross-encoder/nli-deberta-v3-base"
"""Default local NLI cross-encoder model.

Overridable per-call: pass ``model_name=`` to any function in this module.
Do not change this default for tests — pass a fake callable instead.
"""

try:
    from sentence_transformers import CrossEncoder as _CrossEncoder  # noqa: F401
    NLI_AVAILABLE: bool = True
except ImportError:
    NLI_AVAILABLE = False


@lru_cache(maxsize=None)
def _load_model(model_name: str) -> "CrossEncoder":
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name)


def _entailment_idx(model: "CrossEncoder") -> int:
    """Return the output-array index that corresponds to 'entailment'."""
    try:
        for idx, label in model.config.id2label.items():
            if "entail" in str(label).lower():
                return int(idx)
    except AttributeError:
        pass
    return 1  # NLI convention: most models use index 1 for entailment


def entailment_score(
    premise: str,
    hypothesis: str,
    model_name: str = DEFAULT_NLI_MODEL,
) -> float:
    """Return the probability (0–1) that *premise* entails *hypothesis*.

    Raises ``ImportError`` if ``sentence_transformers`` is not installed.
    Raises ``ValueError`` if either input is empty.
    """
    if not premise.strip():
        raise ValueError("nli: premise is empty")
    if not hypothesis.strip():
        raise ValueError("nli: hypothesis is empty")

    model = _load_model(model_name)
    scores = model.predict([(premise, hypothesis)], apply_softmax=True)
    ent_idx = _entailment_idx(model)
    raw = float(scores[0][ent_idx])
    return max(0.0, min(1.0, raw))


def nli_label(
    premise: str,
    hypothesis: str,
    model_name: str = DEFAULT_NLI_MODEL,
) -> Literal["entailment", "neutral", "contradiction"]:
    """Return the most likely NLI relation (highest-probability label)."""
    if not premise.strip():
        raise ValueError("nli: premise is empty")
    if not hypothesis.strip():
        raise ValueError("nli: hypothesis is empty")

    model = _load_model(model_name)
    scores = model.predict([(premise, hypothesis)], apply_softmax=True)
    idx = int(scores[0].argmax())

    try:
        raw_label = str(model.config.id2label[idx]).lower()
    except (AttributeError, KeyError):
        raw_label = ["contradiction", "entailment", "neutral"][idx]

    if "entail" in raw_label:
        return "entailment"
    if "contradict" in raw_label:
        return "contradiction"
    return "neutral"


def entails(
    premise: str,
    hypothesis: str,
    threshold: float = 0.5,
    model_name: str = DEFAULT_NLI_MODEL,
) -> bool:
    """Return True if the NLI entailment probability ≥ *threshold*."""
    return entailment_score(premise, hypothesis, model_name) >= threshold
