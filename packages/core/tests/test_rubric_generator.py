"""Tests for the LLM-powered rubric generator (reprompt_core.rubric_generator).

No real network calls / no live key needed
---------------------------------------------
Every test here supplies a fake ``call`` callable directly (the module's own
dependency-injection point — see its docstring), same spirit as
``test_judge.py`` monkeypatching ``reprompt_core.llm.client.complete``. The
one genuine live call lives in ``test_rubric_generator_live.py``.
"""

from __future__ import annotations

import json

import pytest

from reprompt_core.deterministic import parse_deterministic_checks
from reprompt_core.llm.client import LLMResponse
from reprompt_core.rubric_generator import (
    DEFAULT_MAX_SAMPLES,
    RubricGenerationError,
    RubricGenerationResult,
    StageOutputSample,
    generate_rubric,
)
from reprompt_core.trace import TokenUsage

STAGE_NAME = "Extract financials"
STAGE_MODEL = "gpt-4o-2024-08-06"
PROMPT_TEMPLATE = "Extract the currency and revenue figure from: {{document}}"

SAMPLES = [
    StageOutputSample(input={"document": "Q1 revenue was $4.2M USD."}, output='{"currency": "USD", "revenue": 4200000}'),
    StageOutputSample(input={"document": "Q2 revenue was €3.1M."}, output='{"currency": "EUR", "revenue": 3100000}'),
    StageOutputSample(input={"document": "Q3 revenue was £900K."}, output='{"currency": "GBP", "revenue": 900000}'),
]

VALID_RUBRIC_CONTENT = json.dumps(
    {
        "deterministic_checks": [
            {"type": "required_keys", "keys": ["currency", "revenue"]},
            {"type": "enum_values", "field": "currency", "allowed_values": ["USD", "EUR", "GBP"]},
        ],
        "judge_criteria": [
            {"name": "Correct currency code", "weight": 0.6, "description": "Uses the ISO currency code implied by the input."},
            {"name": "Correct revenue figure", "weight": 0.4, "description": "Revenue matches the figure stated in the input."},
        ],
        "downstream_contract": ["currency", "revenue"],
    }
)


def _fake_response(
    content: str, *, model: str = "claude-sonnet-4-5", cost_usd: float | None = 0.001, latency_ms: float = 250.0
) -> LLMResponse:
    return LLMResponse(
        content=content,
        model=model,
        provider="anthropic",
        usage=TokenUsage(input=200, output=120, thinking=None),
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        finish_reason="stop",
    )


def _make_call(responses: list[LLMResponse]):
    """Returns (call, captured_calls) — `call` yields each response in
    `responses` in order (one per invocation); captures (model, messages, kwargs)."""
    captured: list[dict] = []
    iterator = iter(responses)

    def call(model, messages, **kwargs):
        captured.append({"model": model, "messages": messages, "kwargs": kwargs})
        return next(iterator)

    return call, captured


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_empty_samples_raises_value_error_without_calling_the_model() -> None:
    def should_not_be_called(model, messages, **kwargs):
        raise AssertionError("call must not be invoked with zero samples")

    with pytest.raises(ValueError, match="at least one output sample"):
        generate_rubric(
            STAGE_NAME, STAGE_MODEL, PROMPT_TEMPLATE, [], call=should_not_be_called, generator_model="claude-sonnet-4-5"
        )


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def test_prompt_includes_stage_identity_and_all_sample_inputs_outputs() -> None:
    call, captured = _make_call([_fake_response(VALID_RUBRIC_CONTENT)])

    generate_rubric(STAGE_NAME, STAGE_MODEL, PROMPT_TEMPLATE, SAMPLES, call=call, generator_model="claude-sonnet-4-5")

    assert len(captured) == 1
    user_content = captured[0]["messages"][1]["content"]
    assert STAGE_NAME in user_content
    assert STAGE_MODEL in user_content
    assert PROMPT_TEMPLATE in user_content
    for sample in SAMPLES:
        assert sample.output in user_content
        assert json.dumps(sample.input, ensure_ascii=False, indent=2) in user_content


def test_response_format_is_requested() -> None:
    call, captured = _make_call([_fake_response(VALID_RUBRIC_CONTENT)])

    generate_rubric(STAGE_NAME, STAGE_MODEL, PROMPT_TEMPLATE, SAMPLES, call=call, generator_model="claude-sonnet-4-5")

    assert "response_format" in captured[0]["kwargs"]


def test_max_samples_caps_how_many_examples_reach_the_prompt() -> None:
    many_samples = [
        StageOutputSample(input={"document": f"doc {i}"}, output=f"UNIQUE_OUTPUT_MARKER_{i}") for i in range(DEFAULT_MAX_SAMPLES + 5)
    ]
    call, captured = _make_call([_fake_response(VALID_RUBRIC_CONTENT)])

    generate_rubric(STAGE_NAME, STAGE_MODEL, PROMPT_TEMPLATE, many_samples, call=call, generator_model="claude-sonnet-4-5")

    user_content = captured[0]["messages"][1]["content"]
    included = sum(1 for s in many_samples if s.output in user_content)
    assert included == DEFAULT_MAX_SAMPLES
    # The first N (not some arbitrary subset) are the ones included.
    assert all(f"UNIQUE_OUTPUT_MARKER_{i}" in user_content for i in range(DEFAULT_MAX_SAMPLES))


def test_accepts_plain_dict_samples() -> None:
    raw_samples = [{"input": {"document": "doc"}, "output": '{"currency": "USD", "revenue": 100}'}]
    call, captured = _make_call([_fake_response(VALID_RUBRIC_CONTENT)])

    result = generate_rubric(
        STAGE_NAME, STAGE_MODEL, PROMPT_TEMPLATE, raw_samples, call=call, generator_model="claude-sonnet-4-5"
    )

    assert isinstance(result, RubricGenerationResult)
    assert '{"currency": "USD", "revenue": 100}' in captured[0]["messages"][1]["content"]


# ---------------------------------------------------------------------------
# Valid output -> real deterministic.py types
# ---------------------------------------------------------------------------


def test_valid_output_produces_checks_that_validate_against_real_check_types() -> None:
    call, _ = _make_call([_fake_response(VALID_RUBRIC_CONTENT)])

    result = generate_rubric(STAGE_NAME, STAGE_MODEL, PROMPT_TEMPLATE, SAMPLES, call=call, generator_model="claude-sonnet-4-5")

    # The whole point: deterministic_checks round-trips through the REAL
    # strict discriminated-union parser without error.
    parsed = parse_deterministic_checks(result.deterministic_checks)
    assert len(parsed) == 2
    assert {c.type for c in parsed} == {"required_keys", "enum_values"}
    assert result.dropped_checks == []


def test_judge_criteria_and_downstream_contract_shapes_match_the_api_convention() -> None:
    call, _ = _make_call([_fake_response(VALID_RUBRIC_CONTENT)])

    result = generate_rubric(STAGE_NAME, STAGE_MODEL, PROMPT_TEMPLATE, SAMPLES, call=call, generator_model="claude-sonnet-4-5")

    assert result.judge_criteria == [
        {"name": "Correct currency code", "weight": 0.6, "description": "Uses the ISO currency code implied by the input."},
        {"name": "Correct revenue figure", "weight": 0.4, "description": "Revenue matches the figure stated in the input."},
    ]
    assert result.downstream_contract == ["currency", "revenue"]
    assert result.model == "claude-sonnet-4-5"
    assert result.cost_usd == pytest.approx(0.001)
    assert result.latency_ms == pytest.approx(250.0)


def test_model_legitimately_proposing_zero_deterministic_checks_is_accepted_without_retry() -> None:
    content = json.dumps(
        {
            "deterministic_checks": [],
            "judge_criteria": [{"name": "Tone matches", "weight": 1.0, "description": "..."}],
            "downstream_contract": [],
        }
    )
    call, captured = _make_call([_fake_response(content)])

    result = generate_rubric(STAGE_NAME, STAGE_MODEL, PROMPT_TEMPLATE, SAMPLES, call=call, generator_model="claude-sonnet-4-5")

    assert len(captured) == 1  # no retry
    assert result.deterministic_checks == []
    assert result.dropped_checks == []


# ---------------------------------------------------------------------------
# Partial-invalid: dropped, no retry
# ---------------------------------------------------------------------------


def test_partial_invalid_checks_are_dropped_without_a_retry() -> None:
    content = json.dumps(
        {
            "deterministic_checks": [
                {"type": "required_keys", "keys": ["currency", "revenue"]},  # valid
                {"type": "required_keys"},  # invalid: missing required `keys`
            ],
            "judge_criteria": [{"name": "x", "weight": 1.0, "description": "y"}],
            "downstream_contract": ["currency"],
        }
    )
    call, captured = _make_call([_fake_response(content)])

    result = generate_rubric(STAGE_NAME, STAGE_MODEL, PROMPT_TEMPLATE, SAMPLES, call=call, generator_model="claude-sonnet-4-5")

    assert len(captured) == 1  # exactly one call: no retry for a partial failure
    assert len(result.deterministic_checks) == 1
    assert result.deterministic_checks[0]["keys"] == ["currency", "revenue"]
    assert len(result.dropped_checks) == 1
    assert "required_keys" in result.dropped_checks[0]


# ---------------------------------------------------------------------------
# Total-invalid / unparseable -> exactly one retry
# ---------------------------------------------------------------------------


def test_all_invalid_checks_trigger_one_retry_that_succeeds() -> None:
    bad_content = json.dumps(
        {
            "deterministic_checks": [{"type": "required_keys"}],  # missing required `keys` -> invalid
            "judge_criteria": [{"name": "x", "weight": 1.0, "description": "y"}],
            "downstream_contract": [],
        }
    )
    call, captured = _make_call(
        [_fake_response(bad_content, cost_usd=0.001, latency_ms=200.0), _fake_response(VALID_RUBRIC_CONTENT, cost_usd=0.002, latency_ms=300.0)]
    )

    result = generate_rubric(STAGE_NAME, STAGE_MODEL, PROMPT_TEMPLATE, SAMPLES, call=call, generator_model="claude-sonnet-4-5")

    assert len(captured) == 2
    # The retry's user message includes a corrective note referencing the failure.
    retry_user_content = captured[1]["messages"][1]["content"]
    assert "previous response could not be used" in retry_user_content
    assert len(result.deterministic_checks) == 2  # from the successful retry
    assert result.cost_usd == pytest.approx(0.003)
    assert result.latency_ms == pytest.approx(500.0)


def test_unparseable_json_triggers_one_retry_that_succeeds() -> None:
    call, captured = _make_call([_fake_response("not json at all"), _fake_response(VALID_RUBRIC_CONTENT)])

    result = generate_rubric(STAGE_NAME, STAGE_MODEL, PROMPT_TEMPLATE, SAMPLES, call=call, generator_model="claude-sonnet-4-5")

    assert len(captured) == 2
    assert len(result.deterministic_checks) == 2


def test_retry_still_invalid_raises_rubric_generation_error() -> None:
    bad_content = json.dumps(
        {
            "deterministic_checks": [{"type": "required_keys"}],
            "judge_criteria": [{"name": "x", "weight": 1.0, "description": "y"}],
            "downstream_contract": [],
        }
    )
    call, captured = _make_call([_fake_response(bad_content), _fake_response(bad_content)])

    with pytest.raises(RubricGenerationError, match="both the initial attempt and one corrective retry"):
        generate_rubric(STAGE_NAME, STAGE_MODEL, PROMPT_TEMPLATE, SAMPLES, call=call, generator_model="claude-sonnet-4-5")

    assert len(captured) == 2  # exactly one retry, not an infinite/unbounded loop


def test_retry_still_unparseable_raises_rubric_generation_error() -> None:
    call, captured = _make_call([_fake_response("not json"), _fake_response("still not json")])

    with pytest.raises(RubricGenerationError, match="both the initial attempt and one corrective retry"):
        generate_rubric(STAGE_NAME, STAGE_MODEL, PROMPT_TEMPLATE, SAMPLES, call=call, generator_model="claude-sonnet-4-5")

    assert len(captured) == 2
