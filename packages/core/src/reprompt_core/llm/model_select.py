"""Model auto-selection — pick a good model for a pipeline task without
requiring the caller to know the current model landscape by heart.

The gap this closes: :func:`reprompt_core.rubric_generator.generate_rubric`
(and, in principle, the judge/mutator call sites) require a caller-supplied
model string with no default — a fine contract for a deliberate BYOK choice,
but it means *every* rubric-generation call in ``apps/api`` needs a human to
pick a model first, even when there is an obviously reasonable default given
what the workspace already has configured.

Approach — deliberately simple, per the task's own instruction not to build
a "complex heuristic"
-------------------------------------------------------------------------
1. A small curated **capability tier table** (:data:`_CAPABILITY_TIERS`),
   one ordered tuple-of-tiers per purpose, best tier first. This is
   editorial/curated data, not derived from
   :mod:`reprompt_core.llm.registry` — that module deliberately only
   exposes cost/context-window/JSON-mode/tool-use facts (see its own
   docstring), nothing resembling "how good is this model at analysis or
   instruction-following," which isn't something LiteLLM's metadata
   encodes at all. A hand-curated table is therefore the honest way to
   answer that question today, versioned the same lightweight way
   :mod:`reprompt_core.llm.model_card` versions its family cards (edit the
   table when the field's consensus changes).
2. Intersect each tier, in order, with ``available_models`` (whatever the
   caller says the workspace can actually use — apps/api passes its
   BYOK-filtered "configured models" list). The first tier with any overlap
   wins.
3. Within that tier, break ties by cost (cheapest first), via
   :func:`reprompt_core.llm.registry.get_model_capabilities` — never a
   second hand-curated cost table, always the live registry data.
4. If no tier has any overlap at all (``available_models`` contains only
   models this table doesn't recognize), fall back to the cheapest
   available model rather than raising — some usable pick beats none for
   an uncurated provider.

Explicit override
-------------------------------------------------------------------------
``explicit`` always wins outright, before any of the above runs, and
without validating it against ``available_models`` — per the task's own
framing, "if caller passes a specific model, use it, don't second-guess."
A caller that already knows exactly which model it wants (a user's
deliberate choice in the UI, an explicit ``generator_model`` argument
threaded through from a test) should never have that choice silently
overridden or rejected by this module.

Zero FastAPI imports, per the working rules for ``packages/core`` — this
module only knows about model strings and the (also-FastAPI-free)
:mod:`reprompt_core.llm.registry`.
"""

from __future__ import annotations

from typing import Literal, Sequence

from reprompt_core.llm.model_card import resolve_family
from reprompt_core.llm.registry import get_model_capabilities

__all__ = ["Purpose", "NoAvailableModelError", "select_model"]

Purpose = Literal["rubric_generation", "judge", "mutator"]


class NoAvailableModelError(ValueError):
    """Raised when there is nothing to select from at all.

    Specifically: no ``explicit`` model was given, and ``available_models``
    is empty. This is a caller-input problem (e.g. a workspace with zero
    configured providers and zero no-key-required models in its curated
    list) rather than something this module can paper over — there is
    truly no model to return.
    """


# Curated capability tiers per purpose, best first. Each tier is an ordered
# tuple of LiteLLM model strings this table considers roughly
# equally-capable for that purpose; order *within* a tier does not matter
# for selection (cost breaks ties — see module docstring), but is kept
# roughly cost-ascending here for readability.
#
# All three purposes share the same tiers today — "which models are
# strong at careful analysis + strict instruction-following" is the same
# underlying question for reverse-engineering a rubric from examples
# (rubric_generation), judging one output against another (judge), and
# proposing a mutated prompt (mutator). A future purpose-specific split is
# a one-line change (add a differently-ordered tuple for that purpose) —
# nothing about the selection algorithm assumes the tiers are shared.
_GENERAL_ANALYSIS_TIERS: tuple[tuple[str, ...], ...] = (
    # Tier 1: frontier-class models — strong multi-step reasoning over
    # unstructured evidence and reliable adherence to a detailed JSON
    # response schema (see rubric_generator.py's own notes on how often
    # models get a discriminated-union-shaped schema "almost right").
    ("claude-sonnet-4-5", "gpt-4o", "gemini/gemini-2.0-flash"),
    # Tier 2: smaller/cheaper siblings of the same families — capable,
    # not first choice. Includes Nemotron (free NVIDIA NIM, strong
    # instruction-following) alongside the smaller cloud siblings.
    ("claude-haiku-4-5", "gpt-4o-mini", "gemini/gemini-2.0-flash-lite", "nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1"),
    # Tier 3: local/open-weight — last resort: no vendor cost data and
    # generally weaker instruction-following guarantees than the cloud
    # frontier tiers above.
    ("ollama/qwen2.5:14b", "ollama/llama3.1"),
)

_CAPABILITY_TIERS: dict[Purpose, tuple[tuple[str, ...], ...]] = {
    "rubric_generation": _GENERAL_ANALYSIS_TIERS,
    "judge": _GENERAL_ANALYSIS_TIERS,
    "mutator": _GENERAL_ANALYSIS_TIERS,
}


def _combined_cost_per_token(model: str) -> float:
    """Ascending sort key used to break ties within a tier.

    Unknown pricing (``None`` — typically a local/self-hosted model
    LiteLLM has no vendor price sheet for) is treated as free (``0.0``)
    rather than excluding the model or treating it as infinitely
    expensive: cost is only a tiebreak among models this table already
    considers equally capable, and a missing price is not evidence a
    model is expensive.
    """
    caps = get_model_capabilities(model)
    return (caps.input_cost_per_token or 0.0) + (caps.output_cost_per_token or 0.0)


def select_model(
    purpose: Purpose,
    available_models: list[str],
    *,
    explicit: str | None = None,
    target_models: Sequence[str] = (),
) -> str:
    """Pick a good model for ``purpose`` out of ``available_models``.

    Parameters
    ----------
    purpose:
        Which pipeline task the model is being picked for. Looked up in
        :data:`_CAPABILITY_TIERS`; a purpose not present there (shouldn't
        happen for any of the three declared in the :data:`Purpose` type,
        but kept defensive for a future addition to the type that hasn't
        had its table entry added yet) is treated as having no curated
        tiers at all, falling straight to the cheapest-available fallback.
    available_models:
        What the caller can actually use right now — e.g. a workspace's
        BYOK-filtered curated model list. Not validated against any global
        registry; this function trusts the caller's list completely.
    explicit:
        A caller-supplied model choice that always wins immediately,
        without being checked against ``available_models``, ``target_models``,
        or any tier — see module docstring's "Explicit override" section.
        Pass the caller's already-chosen model here (if any) rather than
        branching around this function at the call site.
    target_models:
        The model(s) actually under test in the caller's context (e.g. a
        migration's chosen target model list) — never auto-selected for
        ``purpose="judge"``/``"mutator"``, so a target model can never
        silently grade or refine its own output. Ignored for
        ``purpose="rubric_generation"`` (there is no "target" in that
        context). For ``purpose="judge"`` specifically, candidates whose
        :func:`~reprompt_core.llm.model_card.resolve_family` matches any
        target model's family are also deprioritized (not hard-excluded —
        see "Cross-family judging" below): same-family judging has been
        observed to favor a model's own stylistic output even when the
        exact model differs, so a same-family judge is a real but lesser
        risk than the target literally judging itself.

    Cross-family judging
    ---------------------------------------------------------------------
    For ``purpose="judge"``, within a tier, candidates from a family that
    doesn't match any ``target_models`` entry are preferred over
    same-family candidates — cost only breaks ties *within* that
    preference group, not across it. If every candidate in every tier
    happens to share a family with a target model, the best same-family
    candidate is still returned (degrade gracefully, matching this
    module's existing "some pick beats none" stance) rather than raising.

    Returns
    -------
    The selected model string.

    Raises
    ------
    NoAvailableModelError
        ``explicit`` is not given and ``available_models`` (after
        excluding any exact ``target_models`` matches) is empty — there is
        nothing to select from.
    """
    if explicit:
        return explicit

    # Hard rule, all purposes this applies to: a model under test is never
    # a candidate for judging/mutating itself, regardless of cost/tier.
    usable_models = [m for m in available_models if m not in set(target_models)]

    if not usable_models:
        raise NoAvailableModelError(
            f"No models available to select from for purpose={purpose!r} "
            "(available_models was empty, or only contained target_models "
            "excluded to prevent self-grading, and no explicit model was given)."
        )

    available_set = set(usable_models)
    target_families = (
        {resolve_family(m) for m in target_models} if purpose == "judge" and target_models else set()
    )
    for tier in _CAPABILITY_TIERS.get(purpose, ()):
        candidates = [model for model in tier if model in available_set]
        if not candidates:
            continue
        if target_families:
            cross_family = [m for m in candidates if resolve_family(m) not in target_families]
            if cross_family:
                candidates = cross_family
            # else: every candidate in this tier shares a family with a
            # target model — fall through and pick the best of them
            # anyway rather than skip the tier, per "degrade gracefully".
        return min(candidates, key=_combined_cost_per_token)

    # Nothing in usable_models appears in any curated tier for this
    # purpose (e.g. an uncurated provider) — still return something usable
    # rather than raising, per the module's "some pick beats none" stance.
    return min(usable_models, key=_combined_cost_per_token)
