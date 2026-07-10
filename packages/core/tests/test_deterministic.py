import pytest

from refract_core.deterministic import (
    EnumValuesCheck,
    JsonSchemaCheck,
    LengthBoundsCheck,
    NoHallucinatedIdsCheck,
    RegexCheck,
    RequiredKeysCheck,
    evaluate_deterministic_checks,
    parse_deterministic_checks,
)

# ---------------------------------------------------------------------------
# json_schema
# ---------------------------------------------------------------------------


def test_json_schema_passes_when_output_matches() -> None:
    check = JsonSchemaCheck(
        schema={
            "type": "object",
            "required": ["currency", "amount"],
            "properties": {
                "currency": {"type": "string", "enum": ["USD", "EUR"]},
                "amount": {"type": "number"},
            },
        }
    )
    output = '{"currency": "USD", "amount": 42.5}'
    result = evaluate_deterministic_checks(output, [check])
    assert result.passed
    assert result.results[0].passed
    assert "valid JSON" in result.results[0].reason


def test_json_schema_fails_with_clear_reason_for_missing_key() -> None:
    check = JsonSchemaCheck(
        schema={
            "type": "object",
            "required": ["currency", "amount"],
        }
    )
    output = '{"amount": 42.5}'
    result = evaluate_deterministic_checks(output, [check])
    assert not result.passed
    assert not result.results[0].passed
    assert "missing required key 'currency'" in result.results[0].reason


def test_json_schema_fails_gracefully_on_non_json_output() -> None:
    # Malformed-output case: must fail with a clear reason, never raise.
    check = JsonSchemaCheck(schema={"type": "object"})
    result = evaluate_deterministic_checks("this is not json at all", [check])
    assert not result.passed
    assert result.results[0].passed is False
    assert "not valid JSON" in result.results[0].reason


# ---------------------------------------------------------------------------
# required_keys
# ---------------------------------------------------------------------------


def test_required_keys_passes_when_all_present() -> None:
    check = RequiredKeysCheck(keys=["revenue", "currency"])
    output = {"revenue": 4_200_000, "currency": "USD"}
    result = evaluate_deterministic_checks(output, [check])
    assert result.passed
    assert "present" in result.results[0].reason


def test_required_keys_fails_with_missing_key_named_in_reason() -> None:
    check = RequiredKeysCheck(keys=["revenue", "currency"])
    output = {"revenue": 4_200_000}
    result = evaluate_deterministic_checks(output, [check])
    assert not result.passed
    assert "Missing required key: 'currency'" == result.results[0].reason


# ---------------------------------------------------------------------------
# regex
# ---------------------------------------------------------------------------


def test_regex_must_match_passes() -> None:
    check = RegexCheck(pattern=r"^\d{3}-\d{2}-\d{4}$")
    result = evaluate_deterministic_checks("123-45-6789", [check])
    assert result.passed


def test_regex_must_match_fails_with_clear_reason() -> None:
    check = RegexCheck(pattern=r"^\d{3}-\d{2}-\d{4}$")
    result = evaluate_deterministic_checks("not-an-ssn", [check])
    assert not result.passed
    assert "does not match the required pattern" in result.results[0].reason


def test_regex_must_not_match_fails_when_disallowed_pattern_present() -> None:
    check = RegexCheck(pattern="error", must_match=False)
    result = evaluate_deterministic_checks("An error occurred while processing.", [check])
    assert not result.passed
    assert "matches a disallowed pattern" in result.results[0].reason


# ---------------------------------------------------------------------------
# length_bounds
# ---------------------------------------------------------------------------


def test_length_bounds_passes_within_range() -> None:
    check = LengthBoundsCheck(min_length=5, max_length=50)
    result = evaluate_deterministic_checks("A reasonably sized summary.", [check])
    assert result.passed


def test_length_bounds_fails_when_too_short() -> None:
    check = LengthBoundsCheck(min_length=10, max_length=100)
    result = evaluate_deterministic_checks("hi", [check])
    assert not result.passed
    assert "too short" in result.results[0].reason
    assert "minimum 10" in result.results[0].reason


def test_length_bounds_fails_when_too_long() -> None:
    check = LengthBoundsCheck(max_length=5)
    result = evaluate_deterministic_checks("this output is way too long", [check])
    assert not result.passed
    assert "too long" in result.results[0].reason


# ---------------------------------------------------------------------------
# enum_values
# ---------------------------------------------------------------------------


def test_enum_values_passes_for_allowed_value() -> None:
    check = EnumValuesCheck(field="status", allowed_values=["approved", "rejected", "pending"])
    result = evaluate_deterministic_checks({"status": "approved"}, [check])
    assert result.passed


def test_enum_values_fails_with_clear_reason_for_disallowed_value() -> None:
    check = EnumValuesCheck(field="status", allowed_values=["approved", "rejected", "pending"])
    result = evaluate_deterministic_checks({"status": "unknown"}, [check])
    assert not result.passed
    assert "not one of the allowed values" in result.results[0].reason
    assert "'status'" in result.results[0].reason


# ---------------------------------------------------------------------------
# no_hallucinated_ids
# ---------------------------------------------------------------------------


def test_no_hallucinated_ids_passes_when_all_referenced_ids_are_in_input() -> None:
    check = NoHallucinatedIdsCheck(id_pattern=r"[A-Z]+-\d+")
    input_payload = {"customer_id": "CUST-1029", "order_id": "ORD-4821"}
    output = "Order ORD-4821 shipped to CUST-1029."
    result = evaluate_deterministic_checks(output, [check], input=input_payload)
    assert result.passed
    assert "appear in the input" in result.results[0].reason


def test_no_hallucinated_ids_fails_and_names_the_invented_id() -> None:
    check = NoHallucinatedIdsCheck(id_pattern=r"[A-Z]+-\d+")
    input_payload = {"customer_id": "CUST-1029", "order_id": "ORD-4821"}
    output = "Order ORD-9999 shipped to CUST-1029."
    result = evaluate_deterministic_checks(output, [check], input=input_payload)
    assert not result.passed
    assert "'ORD-9999'" in result.results[0].reason
    assert "ORD-4821" not in result.results[0].reason.split("input:")[1]  # only the missing id is named


def test_no_hallucinated_ids_fails_gracefully_when_no_input_supplied() -> None:
    check = NoHallucinatedIdsCheck()
    result = evaluate_deterministic_checks("Order ORD-4821 shipped.", [check])
    assert not result.passed
    assert "no input was provided" in result.results[0].reason


def test_no_hallucinated_ids_can_check_specific_fields_instead_of_scanning_text() -> None:
    check = NoHallucinatedIdsCheck(fields=["order_id"])
    input_payload = {"known_orders": ["ORD-1", "ORD-2"]}
    passing_output = {"order_id": "ORD-1"}
    failing_output = {"order_id": "ORD-99"}
    assert evaluate_deterministic_checks(passing_output, [check], input=input_payload).passed
    failing = evaluate_deterministic_checks(failing_output, [check], input=input_payload)
    assert not failing.passed
    assert "'ORD-99'" in failing.results[0].reason


# ---------------------------------------------------------------------------
# Cross-cutting: mixed results, empty list, labels
# ---------------------------------------------------------------------------


def test_mixed_pass_and_fail_checks_report_each_independently() -> None:
    checks = [
        RequiredKeysCheck(keys=["currency"]),
        RegexCheck(pattern=r"^\d+$"),
    ]
    output = {"currency": "USD"}
    # RequiredKeysCheck operates on the parsed dict; RegexCheck falls back to
    # the raw (JSON-stringified) text, which won't match `^\d+$`.
    result = evaluate_deterministic_checks(output, checks)
    assert len(result.results) == 2
    assert result.results[0].passed is True
    assert result.results[1].passed is False
    assert result.passed is False
    assert len(result.failures) == 1
    assert result.failures[0].type == "regex"


def test_empty_check_list_trivially_passes() -> None:
    result = evaluate_deterministic_checks("anything at all", [])
    assert result.results == []
    assert result.passed is True
    assert result.failures == []


def test_auto_generated_label_when_none_provided() -> None:
    check = RequiredKeysCheck(keys=["a", "b"])
    result = evaluate_deterministic_checks({"a": 1, "b": 2}, [check])
    assert "a" in result.results[0].label and "b" in result.results[0].label


def test_explicit_label_is_preserved() -> None:
    check = RequiredKeysCheck(keys=["a"], label="Has the required 'a' field")
    result = evaluate_deterministic_checks({"a": 1}, [check])
    assert result.results[0].label == "Has the required 'a' field"


# ---------------------------------------------------------------------------
# parse_deterministic_checks — round-trip from raw JSON (as stored in
# Rubric.deterministic_checks) into typed check objects.
# ---------------------------------------------------------------------------


def test_parse_deterministic_checks_round_trips_from_raw_dicts() -> None:
    raw = [
        {"type": "required_keys", "keys": ["revenue", "currency"]},
        {"type": "enum_values", "field": "currency", "allowed_values": ["USD", "EUR"]},
    ]
    checks = parse_deterministic_checks(raw)
    assert isinstance(checks[0], RequiredKeysCheck)
    assert isinstance(checks[1], EnumValuesCheck)
    result = evaluate_deterministic_checks({"revenue": 100, "currency": "USD"}, checks)
    assert result.passed


def test_parse_deterministic_checks_rejects_unknown_type() -> None:
    with pytest.raises(Exception):
        parse_deterministic_checks([{"type": "not_a_real_check"}])
