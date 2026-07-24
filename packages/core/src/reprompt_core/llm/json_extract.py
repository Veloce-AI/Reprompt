"""Best-effort JSON extraction from an LLM response body.

Why this exists
---------------
Models with native JSON mode (``response_format``) return a clean, bare JSON
value. But models *without* it — the prompted-JSON fallback path taken for
any model :func:`reprompt_core.llm.registry.supports_json_mode` reports False
for (e.g. NVIDIA NIM's Nemotron) — routinely decorate their JSON even when the
prompt says "respond with JSON only". Observed in practice against Nemotron:

* **Markdown code fences**: ```` ```json\n{...}\n``` ````.
* **A preamble** before the JSON: ``"Given the constraints ... {\"variants\": [...]}"``.
* **A stray trailing character** after otherwise-valid JSON: ``{...}]}}`` (one
  extra ``}``), or trailing prose after the closing brace.

Pydantic's ``model_validate_json`` requires the *entire* string to be one JSON
value, so any of the above makes it fail with ``json_invalid`` even though a
perfectly good JSON object is sitting right there. :func:`extract_json` pulls
that object out so the caller's normal ``model_validate_json`` succeeds.

Design
------
Pure function, no I/O, never raises. For a response that is *already* clean
JSON (the native-JSON-mode case) it returns an equivalent string — the whole
input is the first balanced span — so it is safe to run unconditionally at
every parse site, not just in the fallback path. If nothing JSON-looking is
found it returns the stripped input unchanged, so the caller's existing
parse-error handling still fires exactly as before.

Zero FastAPI imports, per the working rules for ``packages/core``.
"""

from __future__ import annotations

import re

__all__ = ["extract_json"]

# A leading markdown fence line: ``` or ```json (optionally with other info
# string), consumed with its trailing newline. Closing fences are handled by
# the balanced-span scan below (they fall after the final brace), so only the
# opening fence needs stripping here.
_OPENING_FENCE_RE = re.compile(r"^```[^\n]*\n", re.IGNORECASE)


def extract_json(content: str | None) -> str:
    """Return the first balanced JSON object/array found in ``content``.

    Strips a leading markdown code fence, then returns the substring from the
    first ``{`` or ``[`` to its matching balanced close, ignoring any preamble
    before it or trailing characters after it. String contents (including
    braces inside string values) are respected so they never throw off the
    brace matching.

    Falls back to the stripped input if no JSON opener is present or the value
    is unbalanced — the caller's ``model_validate_json`` then surfaces the same
    error it would have without this helper.
    """
    if not content:
        return ""

    text = content.strip()
    text = _OPENING_FENCE_RE.sub("", text).strip()

    start = _first_opener(text)
    if start is None:
        return text

    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    # Unbalanced (truncated output, etc.) — best effort: hand back from the
    # opener so a lenient downstream parser at least sees the start of it.
    return text[start:]


def _first_opener(text: str) -> int | None:
    """Index of the first ``{`` or ``[`` in ``text``, or None if neither."""
    candidates = [i for i in (text.find("{"), text.find("[")) if i != -1]
    return min(candidates) if candidates else None
