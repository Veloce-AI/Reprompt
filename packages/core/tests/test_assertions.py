"""Phase 8: unit tests for run_assertions and _spec_to_check."""

import pytest

from reprompt_core.contract.mine import AssertionSpec
from reprompt_core.optimizer.assertions import AssertionFailure, AssertionRunResult, run_assertions


def _spec(kind: str, spec: dict, *, assertion_id: int | None = None) -> AssertionSpec:
    return AssertionSpec(kind=kind, spec=spec, id=assertion_id)


# ---------------------------------------------------------------------------
# required_keys
# ---------------------------------------------------------------------------


def test_required_keys_passes():
    output = '{"category": "billing", "priority": "high"}'
    result = run_assertions(output, [_spec("required_keys", {"keys": ["category", "priority"]})])
    assert result.passed
    assert result.failures == []


def test_required_keys_fails_missing_key():
    output = '{"category": "billing"}'
    result = run_assertions(output, [_spec("required_keys", {"keys": ["category", "priority"]}, assertion_id=7)])
    assert not result.passed
    assert len(result.failures) == 1
    assert result.failures[0].assertion_id == 7
    assert result.failures[0].kind == "required_keys"
    assert "priority" in result.failures[0].reason


def test_required_keys_fails_non_json():
    result = run_assertions("not json", [_spec("required_keys", {"keys": ["x"]})])
    assert not result.passed


# ---------------------------------------------------------------------------
# regex
# ---------------------------------------------------------------------------


def test_regex_passes():
    result = run_assertions("APPROVED: ticket resolved", [_spec("regex", {"pattern": "^APPROVED"})])
    assert result.passed


def test_regex_fails():
    result = run_assertions("REJECTED: something", [_spec("regex", {"pattern": "^APPROVED"})])
    assert not result.passed
    assert result.failures[0].kind == "regex"


# ---------------------------------------------------------------------------
# enum_values
# ---------------------------------------------------------------------------


def test_enum_values_passes():
    output = '{"category": "billing"}'
    result = run_assertions(
        output,
        [_spec("enum_values", {"field": "category", "values": ["billing", "technical", "other"]})],
    )
    assert result.passed


def test_enum_values_fails():
    output = '{"category": "unknown_value"}'
    result = run_assertions(
        output,
        [_spec("enum_values", {"field": "category", "values": ["billing", "technical"]})],
    )
    assert not result.passed
    assert "unknown_value" in result.failures[0].reason


# ---------------------------------------------------------------------------
# Unknown / bad spec
# ---------------------------------------------------------------------------


def test_unknown_kind_is_skipped():
    """An unrecognised kind must not fail evaluation — skip silently."""
    result = run_assertions("anything", [_spec("future_kind", {"x": 1})])
    assert result.passed
    assert result.failures == []


def test_empty_spec_list_passes():
    result = run_assertions("anything", [])
    assert result.passed


def test_missing_required_params_skipped():
    """required_keys with empty keys list → no translatable check → skipped."""
    result = run_assertions("anything", [_spec("required_keys", {"keys": []})])
    assert result.passed


# ---------------------------------------------------------------------------
# Multiple specs — partial failure
# ---------------------------------------------------------------------------


def test_multiple_specs_partial_failure():
    output = '{"category": "billing"}'
    specs = [
        _spec("required_keys", {"keys": ["category"]}, assertion_id=1),
        _spec("required_keys", {"keys": ["missing_field"]}, assertion_id=2),
    ]
    result = run_assertions(output, specs)
    assert not result.passed
    assert len(result.failures) == 1
    assert result.failures[0].assertion_id == 2


# ---------------------------------------------------------------------------
# assertion_id pass-through
# ---------------------------------------------------------------------------


def test_assertion_id_threaded_through_on_failure():
    output = '{"x": 1}'
    result = run_assertions(output, [_spec("required_keys", {"keys": ["missing"]}, assertion_id=42)])
    assert result.failures[0].assertion_id == 42


def test_assertion_id_none_when_not_set():
    output = "bad"
    result = run_assertions(output, [_spec("required_keys", {"keys": ["x"]})])
    assert result.failures[0].assertion_id is None
