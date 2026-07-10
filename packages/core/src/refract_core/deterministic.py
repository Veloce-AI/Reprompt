"""Deterministic checks — the free, fast half of the evaluation engine.

Per ``refract-parity-engine-plan.md`` §2 (``Rubric.deterministic_checks``)
and §3 (Evaluation Engine: "Score = w1*deterministic + w2*LLM-judge +
w3*embedding-sim ... Deterministic checks are free - run first, gate before
spending judge tokens.") this module owns:

  * the check *specs* a rubric can carry (``json_schema``, ``required_keys``,
    ``regex``, ``length_bounds``, ``enum_values``, ``no_hallucinated_ids``),
    modeled as discriminated-union Pydantic models, and
  * :func:`evaluate_deterministic_checks`, pure-Python evaluation logic with
    zero LLM calls and zero network access.

Like ``trace.py``, this module has **zero FastAPI imports** and only depends
on the standard library and Pydantic v2, so it stays runnable headless/CLI.

Failure reasons are written to be shown directly to a non-technical user in
the rubric checklist UI (screen 4: "plain-English checklist... each
editable/deletable") — e.g. "Missing required key 'currency'", never a raw
exception repr.

Note on ``json_schema``: this is intentionally a small, dependency-free
subset of JSON Schema (``type``, ``properties``, ``required``, ``items``,
``enum``, recursively) rather than a pull of the ``jsonschema`` package —
that subset covers the shapes rubric-generated checks need in practice.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

__all__ = [
    "JsonSchemaCheck",
    "RequiredKeysCheck",
    "RegexCheck",
    "LengthBoundsCheck",
    "EnumValuesCheck",
    "NoHallucinatedIdsCheck",
    "DeterministicCheck",
    "CheckResult",
    "EvaluationResult",
    "evaluate_deterministic_checks",
    "parse_deterministic_checks",
    "DEFAULT_ID_PATTERN",
]

RegexFlagName = Literal["IGNORECASE", "MULTILINE", "DOTALL"]


class _CheckBase(BaseModel):
    """Fields shared by every deterministic check type."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(
        default=None,
        description="Stable id for this check within a rubric, e.g. for UI edit/delete.",
    )
    label: str | None = Field(
        default=None,
        description=(
            "Human-readable label shown in the rubric checklist UI "
            "(e.g. 'Returns valid JSON with 4 keys'). Auto-generated from "
            "the check's fields if omitted."
        ),
    )


class JsonSchemaCheck(_CheckBase):
    """Output must parse as JSON and match a small JSON-Schema-like spec.

    Supported schema keywords (recursive via ``properties``/``items``):
    ``type`` (object/array/string/number/integer/boolean/null),
    ``required`` (list of keys, for ``type: object``), ``properties``
    (dict of nested schemas), ``items`` (schema applied to every array
    element), ``enum`` (list of allowed literal values).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["json_schema"] = "json_schema"
    schema_: dict[str, Any] = Field(
        alias="schema", description="The (subset) JSON Schema the parsed output must satisfy."
    )


class RequiredKeysCheck(_CheckBase):
    """Parsed JSON output must contain every listed key.

    Keys may be dot-paths into nested objects/arrays, e.g. ``meta.currency``
    or ``items.0.sku``.
    """

    type: Literal["required_keys"] = "required_keys"
    keys: list[str] = Field(min_length=1, description="Top-level or dot-path keys that must be present.")


class RegexCheck(_CheckBase):
    """Output (or a specific field within it) must/must not match a pattern."""

    type: Literal["regex"] = "regex"
    pattern: str = Field(description="Python `re` pattern.")
    must_match: bool = Field(
        default=True,
        description="True: the text must match. False: the text must NOT match.",
    )
    field: str | None = Field(
        default=None,
        description="Optional dot-path into parsed JSON output to check instead of the raw output text.",
    )
    flags: list[RegexFlagName] = Field(default_factory=list, description="`re` flags to apply, by name.")


class LengthBoundsCheck(_CheckBase):
    """Output (or a specific field) length must fall within [min, max]."""

    type: Literal["length_bounds"] = "length_bounds"
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    unit: Literal["chars", "words"] = "chars"
    field: str | None = Field(
        default=None,
        description="Optional dot-path into parsed JSON output to measure instead of the raw output text.",
    )


class EnumValuesCheck(_CheckBase):
    """A field's value in the parsed JSON output must be one of a fixed set."""

    type: Literal["enum_values"] = "enum_values"
    field: str = Field(min_length=1, description="Dot-path into parsed JSON output.")
    allowed_values: list[Any] = Field(min_length=1)


# A reasonably generic default for extracting "id-like" tokens from free
# text: UUIDs, prefixed ids ("ORD-4821", "cust_9981"), or bare 4+ digit
# numeric ids. Concrete pipelines almost always have a more specific id
# shape (SKUs, ticket numbers, ...) — override `id_pattern` per rubric for
# a tighter, less noisy check.
DEFAULT_ID_PATTERN = (
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    r"|\b[A-Za-z]{2,10}[-_][A-Za-z0-9]{2,}\b"
    r"|\b\d{4,}\b"
)


class NoHallucinatedIdsCheck(_CheckBase):
    """Ids/entities referenced in the output must appear somewhere in the input.

    Concrete implementation: extract candidate id tokens from the output
    (either via ``id_pattern`` over the raw output text, or, if ``fields``
    is set, by reading those dot-path values directly out of parsed JSON
    output), then verify each one appears as a substring of the stringified
    input. This is a heuristic, not a semantic entity-linker — it catches
    the common case (a model inventing an order/customer/product id that
    was never in the input) cheaply and deterministically.
    """

    type: Literal["no_hallucinated_ids"] = "no_hallucinated_ids"
    id_pattern: str = Field(
        default=DEFAULT_ID_PATTERN,
        description="Regex used to extract candidate id tokens from the raw output text. Ignored if `fields` is set.",
    )
    fields: list[str] | None = Field(
        default=None,
        description="Optional dot-paths into parsed JSON output; if set, only these field values are checked (instead of regex-scanning the raw text).",
    )
    ignore_case: bool = Field(default=True)


DeterministicCheck = Annotated[
    Union[
        JsonSchemaCheck,
        RequiredKeysCheck,
        RegexCheck,
        LengthBoundsCheck,
        EnumValuesCheck,
        NoHallucinatedIdsCheck,
    ],
    Field(discriminator="type"),
]

_CHECKS_ADAPTER: TypeAdapter[list[Any]] = TypeAdapter(list[DeterministicCheck])


def parse_deterministic_checks(raw: list[dict[str, Any]]) -> list[DeterministicCheck]:
    """Validate a raw list of check dicts (e.g. ``Rubric.deterministic_checks`` JSON) into typed checks."""
    return _CHECKS_ADAPTER.validate_python(raw)


class CheckResult(BaseModel):
    """The outcome of running one deterministic check against one output."""

    model_config = ConfigDict(extra="forbid")

    id: str | None
    type: str
    label: str
    passed: bool
    reason: str = Field(description="Human-readable explanation, safe to show a non-technical user as-is.")


class EvaluationResult(BaseModel):
    """The outcome of running a full list of deterministic checks against one output."""

    model_config = ConfigDict(extra="forbid")

    results: list[CheckResult]

    @property
    def passed(self) -> bool:
        """True if every check passed (vacuously True for an empty check list)."""
        return all(result.passed for result in self.results)

    @property
    def failures(self) -> list[CheckResult]:
        return [result for result in self.results if not result.passed]


# ---------------------------------------------------------------------------
# Path / type helpers
# ---------------------------------------------------------------------------


def _get_path(data: Any, path: str) -> tuple[bool, Any]:
    """Resolve a dot-path (e.g. ``meta.items.0.sku``) into ``data``.

    Returns ``(found, value)``. ``found`` is False if any segment of the
    path doesn't exist — never raises.
    """
    if data is None:
        return False, None
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
        elif isinstance(current, list):
            if not re.fullmatch(r"-?\d+", part):
                return False, None
            index = int(part)
            if index < 0 or index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True  # unrecognized type keyword: be lenient, don't fail on it


def _validate_json_schema(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Recursively validate ``value`` against the small ``json_schema`` subset. Returns error strings."""
    errors: list[str] = []

    expected_type = schema.get("type")
    if expected_type is not None:
        if not _type_matches(value, expected_type):
            errors.append(f"{path}: expected type '{expected_type}', got '{_json_type_name(value)}'")
            return errors  # nested checks are meaningless once the type itself is wrong

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} is not one of the allowed values {schema['enum']!r}")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required key '{key}'")
        for key, sub_schema in schema.get("properties", {}).items():
            if key in value:
                errors.extend(_validate_json_schema(value[key], sub_schema, f"{path}.{key}"))

    if isinstance(value, list) and "items" in schema:
        item_schema = schema["items"]
        for index, item in enumerate(value):
            errors.extend(_validate_json_schema(item, item_schema, f"{path}[{index}]"))

    return errors


# ---------------------------------------------------------------------------
# Per-check-type evaluation
#
# Every function below shares the signature
#   (check, raw_text, parsed, parse_error, input_) -> (passed, reason)
# even when a given check type ignores some of those inputs, so they can sit
# in one dispatch table.
# ---------------------------------------------------------------------------


def _check_json_schema(
    check: JsonSchemaCheck, raw_text: str, parsed: Any, parse_error: str | None, input_: Any
) -> tuple[bool, str]:
    if parse_error is not None:
        return False, f"Output is not valid JSON: {parse_error}"
    errors = _validate_json_schema(parsed, check.schema_)
    if errors:
        return False, "; ".join(errors)
    return True, "Output is valid JSON matching the expected schema."


def _check_required_keys(
    check: RequiredKeysCheck, raw_text: str, parsed: Any, parse_error: str | None, input_: Any
) -> tuple[bool, str]:
    if parse_error is not None:
        return False, f"Cannot check required keys: output is not valid JSON ({parse_error})."
    if not isinstance(parsed, (dict, list)):
        return False, f"Cannot check required keys: output is a JSON {_json_type_name(parsed)}, not an object."
    missing = [key for key in check.keys if not _get_path(parsed, key)[0]]
    if missing:
        noun = "key" if len(missing) == 1 else "keys"
        quoted = ", ".join(f"'{key}'" for key in missing)
        return False, f"Missing required {noun}: {quoted}"
    return True, "All required keys are present."


def _check_regex(
    check: RegexCheck, raw_text: str, parsed: Any, parse_error: str | None, input_: Any
) -> tuple[bool, str]:
    if check.field is not None:
        found, value = _get_path(parsed, check.field)
        if not found:
            return False, f"Cannot check pattern: field '{check.field}' was not found in the output."
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    else:
        text = raw_text

    flags = 0
    for flag_name in check.flags:
        flags |= getattr(re, flag_name)
    try:
        matched = re.search(check.pattern, text, flags) is not None
    except re.error as exc:
        return False, f"Invalid regex pattern '{check.pattern}': {exc}"

    if check.must_match and not matched:
        return False, f"Output does not match the required pattern /{check.pattern}/."
    if not check.must_match and matched:
        return False, f"Output matches a disallowed pattern /{check.pattern}/."
    return True, "Pattern check passed."


def _check_length_bounds(
    check: LengthBoundsCheck, raw_text: str, parsed: Any, parse_error: str | None, input_: Any
) -> tuple[bool, str]:
    if check.field is not None:
        found, value = _get_path(parsed, check.field)
        if not found:
            return False, f"Cannot check length: field '{check.field}' was not found in the output."
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    else:
        text = raw_text

    length = len(text) if check.unit == "chars" else len(text.split())
    unit_word = "character" if check.unit == "chars" else "word"
    plural = "" if length == 1 else "s"

    if check.min_length is not None and length < check.min_length:
        return False, f"Output is too short: {length} {unit_word}{plural} (minimum {check.min_length})."
    if check.max_length is not None and length > check.max_length:
        return False, f"Output is too long: {length} {unit_word}{plural} (maximum {check.max_length})."
    return True, f"Length is within bounds ({length} {unit_word}{plural})."


def _check_enum_values(
    check: EnumValuesCheck, raw_text: str, parsed: Any, parse_error: str | None, input_: Any
) -> tuple[bool, str]:
    if parse_error is not None:
        return False, f"Cannot check field '{check.field}': output is not valid JSON ({parse_error})."
    found, value = _get_path(parsed, check.field)
    if not found:
        return False, f"Field '{check.field}' was not found in the output."
    if value not in check.allowed_values:
        return False, (
            f"Field '{check.field}' has value {value!r}, which is not one of the "
            f"allowed values {check.allowed_values!r}."
        )
    return True, f"Field '{check.field}' has an allowed value."


def _check_no_hallucinated_ids(
    check: NoHallucinatedIdsCheck, raw_text: str, parsed: Any, parse_error: str | None, input_: Any
) -> tuple[bool, str]:
    if input_ is None:
        return False, "Cannot check for hallucinated ids: no input was provided to compare the output against."

    input_text = input_ if isinstance(input_, str) else json.dumps(input_, ensure_ascii=False, default=str)

    candidates: list[str] = []
    if check.fields:
        for field in check.fields:
            found, value = _get_path(parsed, field)
            if not found:
                continue
            if isinstance(value, list):
                candidates.extend(str(item) for item in value)
            else:
                candidates.append(str(value))
    else:
        try:
            candidates = re.findall(check.id_pattern, raw_text)
        except re.error as exc:
            return False, f"Invalid id_pattern regex '{check.id_pattern}': {exc}"

    seen: set[str] = set()
    unique_candidates: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique_candidates.append(candidate)

    haystack = input_text.lower() if check.ignore_case else input_text
    missing = [
        candidate
        for candidate in unique_candidates
        if (candidate.lower() if check.ignore_case else candidate) not in haystack
    ]
    if missing:
        quoted = ", ".join(f"'{item}'" for item in missing)
        return False, f"Output references id(s) that don't appear anywhere in the input: {quoted}."
    if not unique_candidates:
        return True, "No candidate ids found in the output to check."
    return True, "All ids referenced in the output appear in the input."


_DISPATCH = {
    "json_schema": _check_json_schema,
    "required_keys": _check_required_keys,
    "regex": _check_regex,
    "length_bounds": _check_length_bounds,
    "enum_values": _check_enum_values,
    "no_hallucinated_ids": _check_no_hallucinated_ids,
}


def _default_label(check: DeterministicCheck) -> str:
    if isinstance(check, JsonSchemaCheck):
        return "Output is valid JSON matching the expected schema"
    if isinstance(check, RequiredKeysCheck):
        return f"Output includes key(s): {', '.join(check.keys)}"
    if isinstance(check, RegexCheck):
        verb = "matches" if check.must_match else "does not match"
        target = f"field '{check.field}'" if check.field else "output"
        return f"{target.capitalize()} {verb} pattern /{check.pattern}/"
    if isinstance(check, LengthBoundsCheck):
        bounds = []
        if check.min_length is not None:
            bounds.append(f"at least {check.min_length}")
        if check.max_length is not None:
            bounds.append(f"at most {check.max_length}")
        target = f"field '{check.field}'" if check.field else "Output"
        return f"{target} length is {' and '.join(bounds)} {check.unit}"
    if isinstance(check, EnumValuesCheck):
        return f"Field '{check.field}' is one of {check.allowed_values}"
    if isinstance(check, NoHallucinatedIdsCheck):
        return "Output does not reference ids/entities absent from the input"
    return check.type  # pragma: no cover - exhaustive over the union above


def evaluate_deterministic_checks(
    output: str | dict[str, Any] | list[Any],
    checks: Sequence[DeterministicCheck],
    *,
    input: dict[str, Any] | str | None = None,  # noqa: A002 - mirrors StageRecord.input naming
) -> EvaluationResult:
    """Run every deterministic check against one stage output.

    ``output`` mirrors ``StageRecord.output`` (usually a raw string, since
    not every stage's output is JSON) but a pre-parsed ``dict``/``list`` is
    also accepted. ``input`` is only consulted by ``no_hallucinated_ids``
    checks (it mirrors ``StageRecord.input``); other check types ignore it.

    Never raises: a check whose preconditions aren't met (output isn't JSON,
    a field is missing, a regex is invalid, ...) is reported as a failed
    :class:`CheckResult` with a clear reason, not an exception. An empty
    ``checks`` list trivially returns an :class:`EvaluationResult` with no
    results (and ``.passed is True``).
    """
    if isinstance(output, (dict, list)):
        parsed: Any = output
        parse_error: str | None = None
        raw_text = json.dumps(output, ensure_ascii=False)
    elif isinstance(output, str):
        raw_text = output
        try:
            parsed = json.loads(output)
            parse_error = None
        except json.JSONDecodeError as exc:
            parsed = None
            parse_error = str(exc)
    else:
        raw_text = str(output)
        parsed = None
        parse_error = "output is neither a string nor a parsed JSON value"

    results: list[CheckResult] = []
    for check in checks:
        try:
            handler = _DISPATCH[check.type]
            passed, reason = handler(check, raw_text, parsed, parse_error, input)
        except Exception as exc:  # belt-and-braces: a check must never crash evaluation
            passed, reason = False, f"Check could not be evaluated: {exc}"
        results.append(
            CheckResult(
                id=check.id,
                type=check.type,
                label=check.label or _default_label(check),
                passed=passed,
                reason=reason,
            )
        )
    return EvaluationResult(results=results)
