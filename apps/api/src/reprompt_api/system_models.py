"""Operator-configured overrides for which model Reprompt's own harness
uses for rubric generation, judging, and prompt mutation - the "system"
models, as opposed to a workspace's own target models under test.

Per-purpose env vars (``REPROMPT_RUBRIC_MODEL`` / ``REPROMPT_JUDGE_MODEL``
/ ``REPROMPT_MUTATOR_MODEL``) take priority over
:func:`reprompt_core.llm.model_select.select_model`'s own capability-tier
auto-selection entirely, via that function's existing ``explicit=``
parameter — no changes needed there, ``explicit`` was already designed to
bypass tier selection unconditionally and without validation.

Priority order at every call site: a per-call explicit choice (a user's
own pick in the UI, or a migration's ``judge_model``/``mutator_model``)
still wins first — this module's override sits *between* that and
auto-select, not above it.

A configured override is a **hard** requirement, not a soft default: if
the operator sets ``REPROMPT_JUDGE_MODEL`` to a model whose provider this
workspace has no BYOK key for, the call fails with a clear
``ProviderKeyNotConfigured`` error (from the downstream
``complete_with_workspace_credentials`` call) rather than silently
falling back to auto-select — "pin exactly this model" is the whole
point of setting the env var; a silent fallback would defeat it. This
module does no validation of its own for exactly that reason: it just
returns the configured string as-is (or ``None``), the same "trust the
caller" contract ``select_model``'s own ``explicit`` parameter already
has.
"""

from __future__ import annotations

import os

from reprompt_core.llm.model_select import Purpose

__all__ = ["system_model_override", "system_model_env_var_name"]

_ENV_VAR_BY_PURPOSE: dict[Purpose, str] = {
    "rubric_generation": "REPROMPT_RUBRIC_MODEL",
    "judge": "REPROMPT_JUDGE_MODEL",
    "mutator": "REPROMPT_MUTATOR_MODEL",
}


def system_model_env_var_name(purpose: Purpose) -> str:
    """The env var name that controls ``purpose`` — exposed so callers can
    build a human-readable "why" (e.g. Settings' system-models visibility
    endpoint) without duplicating this mapping."""
    return _ENV_VAR_BY_PURPOSE[purpose]


def system_model_override(purpose: Purpose) -> str | None:
    """The operator-pinned model for ``purpose``, if its env var is set —
    ``None`` if unset/blank, meaning "fall through to auto-select"."""
    value = os.environ.get(_ENV_VAR_BY_PURPOSE[purpose], "").strip()
    return value or None
