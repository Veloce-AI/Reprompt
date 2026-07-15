"""Importer module boundary — turn real trace-source formats into canonical TraceFile dicts.

Per the plan doc's own stated philosophy (reprompt-parity-engine-plan.md §10.3):

    "Trace format: design your own canonical JSON, treat Langfuse/OTel as
    importers into it — don't marry Langfuse's schema."

``reprompt_core.trace`` (``TraceFile`` / ``parse_trace_file``) *is* that
canonical JSON. Everything under this package is an adapter FROM some real
source shape TO that canonical shape. The canonical schema itself is never
modified to accommodate a source format — that's the whole point of having
one.

Convention every importer follows (a Protocol, not an enforced registry —
see the YAGNI note below):

    def convert(raw: dict[str, Any]) -> dict[str, Any]:
        '''Take ONE parsed raw document in the source's native shape and
        return a dict that validates via reprompt_core.trace.parse_trace_file
        (i.e. shaped like {"schema_version", "pipeline", "traces"}).'''

Each importer lives in its own module (e.g. ``query_log.py``) and exposes a
top-level ``convert`` (plus, by convention, a ``convert_file(path)``
convenience wrapper that reads + json.loads + converts). Adding importer #2
means adding a new module that satisfies :class:`ImporterFn` — it never
requires touching an existing importer's code.

Why no plugin registry: with exactly one importer implemented so far, a
registry/dispatch layer (format auto-detection, importer discovery, etc.)
would be speculative machinery with no second caller to validate its shape
against. YAGNI — add one when a second, genuinely different-shaped source
shows up and the right seam becomes obvious from real requirements instead
of guessed ones.
"""

from __future__ import annotations

from typing import Any, Protocol

__all__ = ["ImporterFn"]


class ImporterFn(Protocol):
    """Shape every importer's ``convert`` function must match."""

    def __call__(self, raw: dict[str, Any]) -> dict[str, Any]: ...
