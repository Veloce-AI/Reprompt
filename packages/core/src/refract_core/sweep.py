"""Param/format sweep candidate generator.

Per ``refract-master-build-prompt.md`` §2 (stack: "optuna (param sweeps,
grid sampler for MVP)") and §5 M3(c) ("Optuna grid sweep over temperature x
format (XML/JSON/plain) x structured-output mode") and
``refract-parity-engine-plan.md`` §7 ("Cut from MVP: ... Optuna (grid sweep
is fine at this scale)"), this module only *generates* the grid of
candidate params to try for one target model — it does not execute anything
against a real model. Executing a candidate (calling
:func:`refract_core.llm.client.complete`) and scoring it
(:mod:`refract_core.scoring`) are the M3 optimizer loop's job, a later,
still-unbuilt piece that consumes what this module produces.

Why ``optuna.samplers.GridSampler`` instead of ``itertools.product``
----------------------------------------------------------------------
Grid search is conceptually trivial — a plain nested loop or
``itertools.product`` would enumerate the same combinations. We use
Optuna's ``GridSampler`` anyway because the stack doc names Optuna
specifically even for "just" grid search: driving enumeration through a
``optuna.Study``/``sampler`` means the *caller's* interface (call
:func:`generate_param_format_grid`, get back candidates) never has to
change when a later milestone swaps ``GridSampler`` for one of Optuna's
Bayesian samplers (``TPESampler``, etc.) to search a much larger space
(e.g. once DSPy few-shot variants are added to the search dimensions too).
Hand-rolling the product now would mean re-plumbing this whole module
later instead of changing one line (the sampler construction).

Zero FastAPI imports, per the working rules for ``packages/core``.

Design decision: invalid combinations are generated, not filtered
------------------------------------------------------------------------
A candidate combination can be invalid for a target model in two ways:

1. ``structured_output_mode=True`` requested against a model that doesn't
   support JSON mode at all (per
   :func:`refract_core.llm.registry.supports_json_mode`).
2. ``structured_output_mode=True`` combined with a ``format_mode`` other
   than ``"json"`` — structured/JSON-mode output is, by definition, JSON;
   asking for it while also asking for an XML/markdown/plain-text
   *wrapping* format is an incoherent request, not a model limitation.

This module generates the **full rectangular grid** (via ``GridSampler``,
which requires a fixed set of possible values per dimension — it has no
concept of per-model conditional exclusion) and then annotates each
resulting candidate with ``is_valid`` / ``invalid_reason`` rather than
filtering before generation, for two reasons:

* ``GridSampler`` itself cannot express a jagged/conditional search space
  — filtering first would mean hand-building the grid per model anyway,
  defeating the point of using it at all.
* Keeping invalid candidates visible (rather than silently absent) gives
  the future UI's iteration timeline an honest audit trail — "why didn't
  the sweep try structured mode on this model" has a concrete, attached
  answer instead of a mysteriously smaller candidate count.

Callers that only want runnable candidates should filter on
``candidate.is_valid`` themselves (or see
:func:`refract_core.budget.filter_affordable_candidates`, which does this
as part of a budget-aware preview).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import optuna
from pydantic import BaseModel, ConfigDict, Field

from refract_core.llm.registry import supports_json_mode
from refract_core.trace import FormatMode

__all__ = [
    "DEFAULT_TEMPERATURES",
    "DEFAULT_FORMAT_MODES",
    "DEFAULT_STRUCTURED_OUTPUT_MODES",
    "SweepCandidate",
    "generate_param_format_grid",
]

# Silence Optuna's per-trial INFO logging (e.g. "Trial 0 finished...") — this
# module runs the sampler purely to enumerate a grid, not to report
# optimization progress, and the default verbosity is noisy for that use.
optuna.logging.set_verbosity(optuna.logging.WARNING)

DEFAULT_TEMPERATURES: tuple[float, ...] = (0.0, 0.2, 0.7, 1.0)
"""Default temperature values to sweep. Not specified by the plan beyond
"temp x format x structured-output-mode" — chosen to span deterministic
(0.0), a low-creativity "close to deterministic" point (0.2) commonly used
for structured extraction tasks, a typical default (0.7), and a
high-variance point (1.0)."""

DEFAULT_FORMAT_MODES: tuple[FormatMode, ...] = ("json", "xml", "plain")
"""Default format modes to sweep — exactly the plan's own parenthetical
("format(XML/JSON/plain)"). ``FormatMode`` (reused directly from
``refract_core.trace.StageParams``) is a superset that also allows
``"markdown"``; callers that want it in the sweep can pass
``format_modes=("json", "xml", "markdown", "plain")`` explicitly."""

DEFAULT_STRUCTURED_OUTPUT_MODES: tuple[bool, ...] = (False, True)
"""Default structured-output-mode values: off (free-text output, optionally
wrapped per ``format_mode``) and on (provider-native JSON mode via
``response_format``, see :func:`refract_core.llm.registry.supports_json_mode`)."""


class SweepCandidate(BaseModel):
    """One point in the param/format sweep grid for a specific target model.

    Frozen (immutable) — a candidate's identity and params never change
    after generation; only its *score* (attached later, see
    :mod:`refract_core.selection`) varies across a run.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(
        description="Stable, deterministic id derived from (model, temperature, format_mode, "
        "structured_output_mode) — identical inputs always produce the identical id, "
        "independent of grid enumeration order or which process generated it."
    )
    label: str = Field(description="Human-readable label for logs/UI, e.g. 'temp=0.2 fmt=xml structured=off'.")
    model: str = Field(description="LiteLLM-style target model identifier this candidate is scoped to.")
    temperature: float
    format_mode: FormatMode
    structured_output_mode: bool
    is_valid: bool = Field(
        description="False if this combination is pre-known-invalid for `model` (see module docstring) "
        "and should not actually be attempted against a real model."
    )
    invalid_reason: str | None = Field(
        default=None, description="Human-readable reason, set iff is_valid is False."
    )


def _candidate_id(model: str, temperature: float, format_mode: str, structured_output_mode: bool) -> str:
    """Deterministic short id from the candidate's content, not its position.

    Uses a content hash (rather than e.g. a running index) so the id is
    stable across repeated calls, across processes, and regardless of the
    order Optuna's sampler happens to enumerate the grid in.
    """
    canonical = f"{model}|{temperature:.6g}|{format_mode}|{int(structured_output_mode)}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _candidate_label(temperature: float, format_mode: str, structured_output_mode: bool) -> str:
    structured_label = "on" if structured_output_mode else "off"
    return f"temp={temperature:g} fmt={format_mode} structured={structured_label}"


def _validate_candidate(
    model: str,
    format_mode: str,
    structured_output_mode: bool,
    *,
    model_supports_json_mode: bool,
) -> tuple[bool, str | None]:
    """The two pre-known-invalid rules from the module docstring."""
    if structured_output_mode and format_mode != "json":
        return False, (
            "structured_output_mode requests the provider's native JSON mode, which forces "
            f"JSON-shaped output — incompatible with format_mode='{format_mode}' (only "
            "format_mode='json' is coherent together with structured_output_mode=True)."
        )
    if structured_output_mode and not model_supports_json_mode:
        return False, (
            f"Model '{model}' does not support structured/JSON response_format "
            "(refract_core.llm.registry.supports_json_mode reports False for this model)."
        )
    return True, None


def generate_param_format_grid(
    model: str,
    *,
    temperatures: Sequence[float] = DEFAULT_TEMPERATURES,
    format_modes: Sequence[FormatMode] = DEFAULT_FORMAT_MODES,
    structured_output_modes: Sequence[bool] = DEFAULT_STRUCTURED_OUTPUT_MODES,
    seed: int | None = 0,
) -> list[SweepCandidate]:
    """Enumerate the full temp x format x structured-output-mode grid for ``model``.

    Uses ``optuna.samplers.GridSampler`` to do the actual enumeration (see
    module docstring for why) — no network calls, no model execution, pure
    local computation.

    Parameters
    ----------
    model:
        LiteLLM-style target model identifier the candidates are scoped to.
        Used only to look up capability facts (currently: JSON-mode support,
        via :func:`refract_core.llm.registry.supports_json_mode`) for the
        ``is_valid``/``invalid_reason`` annotation — no model call is made.
    temperatures, format_modes, structured_output_modes:
        The three search dimensions. Each must be non-empty. Defaults are
        :data:`DEFAULT_TEMPERATURES`, :data:`DEFAULT_FORMAT_MODES`,
        :data:`DEFAULT_STRUCTURED_OUTPUT_MODES`.
    seed:
        Passed through to ``GridSampler`` for reproducible internal trial
        ordering. Irrelevant to the *returned* order or content — this
        function always returns candidates sorted into a fixed canonical
        order (by temperature, then format_mode, then structured_output_mode)
        regardless of Optuna's internal enumeration order, so the result is
        deterministic even if Optuna's own ordering behavior changes across
        versions.

    Returns
    -------
    A list of :class:`SweepCandidate`, one per grid point
    (``len(temperatures) * len(format_modes) * len(structured_output_modes)``),
    sorted into a fixed canonical order. Some may have ``is_valid=False`` —
    see the module docstring.
    """
    if not temperatures:
        raise ValueError("temperatures must be non-empty")
    if not format_modes:
        raise ValueError("format_modes must be non-empty")
    if not structured_output_modes:
        raise ValueError("structured_output_modes must be non-empty")

    search_space: dict[str, list] = {
        "temperature": list(temperatures),
        "format_mode": list(format_modes),
        "structured_output_mode": list(structured_output_modes),
    }
    grid_size = len(search_space["temperature"]) * len(search_space["format_mode"]) * len(
        search_space["structured_output_mode"]
    )

    sampler = optuna.samplers.GridSampler(search_space, seed=seed)
    study = optuna.create_study(sampler=sampler, study_name=f"refract-param-format-sweep-{model}")

    seen_params: list[dict] = []

    def _objective(trial: optuna.trial.Trial) -> float:
        # The suggest_categorical calls are what actually drive GridSampler's
        # enumeration; the (unused) dummy return value exists only because
        # study.optimize() requires an objective function that returns one.
        temperature = trial.suggest_categorical("temperature", search_space["temperature"])
        format_mode = trial.suggest_categorical("format_mode", search_space["format_mode"])
        structured_output_mode = trial.suggest_categorical(
            "structured_output_mode", search_space["structured_output_mode"]
        )
        seen_params.append(
            {
                "temperature": temperature,
                "format_mode": format_mode,
                "structured_output_mode": structured_output_mode,
            }
        )
        return 0.0

    # GridSampler stops enumerating once every grid point has been visited
    # exactly once, even if n_trials asks for more — grid_size is exact here
    # (not a cap) since the whole point is to visit every point exactly once.
    study.optimize(_objective, n_trials=grid_size)

    model_supports_json = supports_json_mode(model)

    candidates: list[SweepCandidate] = []
    for params in seen_params:
        temperature = float(params["temperature"])
        format_mode = params["format_mode"]
        structured_output_mode = bool(params["structured_output_mode"])
        is_valid, reason = _validate_candidate(
            model,
            format_mode,
            structured_output_mode,
            model_supports_json_mode=model_supports_json,
        )
        candidates.append(
            SweepCandidate(
                id=_candidate_id(model, temperature, format_mode, structured_output_mode),
                label=_candidate_label(temperature, format_mode, structured_output_mode),
                model=model,
                temperature=temperature,
                format_mode=format_mode,
                structured_output_mode=structured_output_mode,
                is_valid=is_valid,
                invalid_reason=reason,
            )
        )

    candidates.sort(key=lambda c: (c.temperature, c.format_mode, c.structured_output_mode))
    return candidates
