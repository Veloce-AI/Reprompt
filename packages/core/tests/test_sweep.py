"""Tests for the param/format sweep candidate generator (reprompt_core.sweep).

Uses Optuna's real ``GridSampler`` throughout (no mocking) — grid
enumeration is pure local computation with no network dependency, so
there's nothing to fake. Model capability lookups (``supports_json_mode``)
go through the real ``reprompt_core.llm.registry`` against LiteLLM's bundled
static model metadata (same convention as ``test_llm_registry.py``) —
``"gpt-4o"`` is a real, JSON-mode-supporting model string and
``"totally-not-a-real-model-xyz-123"`` is LiteLLM's own "unrecognized
model" degrade-gracefully case (see ``test_llm_registry.py``), reused here
as a model that does *not* support JSON mode.
"""

from __future__ import annotations

import itertools

from reprompt_core.sweep import (
    DEFAULT_FORMAT_MODES,
    DEFAULT_STRUCTURED_OUTPUT_MODES,
    DEFAULT_TEMPERATURES,
    SweepCandidate,
    generate_param_format_grid,
)

JSON_MODE_MODEL = "gpt-4o"
NO_JSON_MODE_MODEL = "totally-not-a-real-model-xyz-123"


# ---------------------------------------------------------------------------
# grid size / full coverage via the real Optuna GridSampler
# ---------------------------------------------------------------------------


def test_grid_size_matches_search_space_dimensions() -> None:
    temperatures = [0.0, 0.7]
    format_modes = ["json", "xml", "plain"]
    structured_output_modes = [False, True]

    candidates = generate_param_format_grid(
        JSON_MODE_MODEL,
        temperatures=temperatures,
        format_modes=format_modes,
        structured_output_modes=structured_output_modes,
    )

    assert len(candidates) == len(temperatures) * len(format_modes) * len(structured_output_modes)


def test_grid_covers_the_full_cartesian_product_exactly_once() -> None:
    """The real GridSampler must visit every combination exactly once —
    this is the property that justifies using it over itertools.product."""
    temperatures = [0.0, 0.5]
    format_modes = ["json", "xml"]
    structured_output_modes = [False, True]

    candidates = generate_param_format_grid(
        JSON_MODE_MODEL,
        temperatures=temperatures,
        format_modes=format_modes,
        structured_output_modes=structured_output_modes,
    )

    seen = {(c.temperature, c.format_mode, c.structured_output_mode) for c in candidates}
    expected = set(itertools.product(temperatures, format_modes, structured_output_modes))
    assert seen == expected
    assert len(candidates) == len(expected)  # no duplicates


def test_default_search_space_grid_size() -> None:
    candidates = generate_param_format_grid(JSON_MODE_MODEL)
    assert len(candidates) == (
        len(DEFAULT_TEMPERATURES) * len(DEFAULT_FORMAT_MODES) * len(DEFAULT_STRUCTURED_OUTPUT_MODES)
    )


# ---------------------------------------------------------------------------
# deterministic ids
# ---------------------------------------------------------------------------


def test_candidate_ids_are_unique_within_one_grid() -> None:
    candidates = generate_param_format_grid(JSON_MODE_MODEL)
    ids = [c.id for c in candidates]
    assert len(ids) == len(set(ids))


def test_candidate_ids_stable_across_repeated_calls() -> None:
    """Same inputs -> same ids, independent of Optuna's internal enumeration
    order (ids are content hashes, not positional)."""
    first = generate_param_format_grid(JSON_MODE_MODEL)
    second = generate_param_format_grid(JSON_MODE_MODEL)

    first_by_params = {(c.temperature, c.format_mode, c.structured_output_mode): c.id for c in first}
    second_by_params = {(c.temperature, c.format_mode, c.structured_output_mode): c.id for c in second}
    assert first_by_params == second_by_params


def test_candidate_id_depends_on_model() -> None:
    """Same params, different target model -> different id (id scopes to model too)."""
    a = generate_param_format_grid("gpt-4o", temperatures=[0.5], format_modes=["json"])[0]
    b = generate_param_format_grid("claude-sonnet-4-5", temperatures=[0.5], format_modes=["json"])[0]
    assert a.temperature == b.temperature
    assert a.format_mode == b.format_mode
    assert a.id != b.id


def test_returned_order_is_canonical_regardless_of_call() -> None:
    """The public result order is a fixed sort, not Optuna's raw enumeration
    order — repeated calls return candidates in the identical list order."""
    first = generate_param_format_grid(JSON_MODE_MODEL)
    second = generate_param_format_grid(JSON_MODE_MODEL)
    assert [c.id for c in first] == [c.id for c in second]
    # sanity: sorted by (temperature, format_mode, structured_output_mode)
    keys = [(c.temperature, c.format_mode, c.structured_output_mode) for c in first]
    assert keys == sorted(keys, key=lambda k: (k[0], k[1], k[2]))


# ---------------------------------------------------------------------------
# invalid-combination handling
# ---------------------------------------------------------------------------


def test_structured_mode_with_non_json_format_is_marked_invalid() -> None:
    candidates = generate_param_format_grid(
        JSON_MODE_MODEL,
        temperatures=[0.5],
        format_modes=["xml", "plain", "json"],
        structured_output_modes=[True],
    )
    by_format = {c.format_mode: c for c in candidates}

    assert by_format["xml"].is_valid is False
    assert by_format["xml"].invalid_reason is not None
    assert "format_mode" in by_format["xml"].invalid_reason

    assert by_format["plain"].is_valid is False
    assert by_format["plain"].invalid_reason is not None

    # json + structured=True is coherent, and gpt-4o supports JSON mode.
    assert by_format["json"].is_valid is True
    assert by_format["json"].invalid_reason is None


def test_structured_mode_on_model_without_json_support_is_marked_invalid() -> None:
    candidates = generate_param_format_grid(
        NO_JSON_MODE_MODEL,
        temperatures=[0.5],
        format_modes=["json"],
        structured_output_modes=[True],
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.is_valid is False
    assert candidate.invalid_reason is not None
    assert "does not support" in candidate.invalid_reason


def test_structured_mode_off_is_always_valid_regardless_of_format_or_model() -> None:
    for model in (JSON_MODE_MODEL, NO_JSON_MODE_MODEL):
        candidates = generate_param_format_grid(
            model,
            temperatures=[0.5],
            format_modes=["json", "xml", "plain"],
            structured_output_modes=[False],
        )
        assert all(c.is_valid for c in candidates), model
        assert all(c.invalid_reason is None for c in candidates), model


def test_invalid_combinations_are_generated_not_filtered_out() -> None:
    """Per the module's documented design choice: invalid combinations still
    appear in the returned list (annotated), the grid size is not reduced."""
    candidates = generate_param_format_grid(
        NO_JSON_MODE_MODEL,
        temperatures=[0.5],
        format_modes=["json", "xml"],
        structured_output_modes=[False, True],
    )
    assert len(candidates) == 4
    assert any(not c.is_valid for c in candidates)
    assert any(c.is_valid for c in candidates)


# ---------------------------------------------------------------------------
# candidate shape / misc
# ---------------------------------------------------------------------------


def test_candidate_carries_param_values_and_model() -> None:
    candidates = generate_param_format_grid(
        JSON_MODE_MODEL, temperatures=[0.3], format_modes=["xml"], structured_output_modes=[False]
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert isinstance(candidate, SweepCandidate)
    assert candidate.model == JSON_MODE_MODEL
    assert candidate.temperature == 0.3
    assert candidate.format_mode == "xml"
    assert candidate.structured_output_mode is False
    assert candidate.label  # non-empty human-readable label


def test_empty_temperatures_raises_value_error() -> None:
    import pytest

    with pytest.raises(ValueError, match="temperatures"):
        generate_param_format_grid(JSON_MODE_MODEL, temperatures=[])


def test_empty_format_modes_raises_value_error() -> None:
    import pytest

    with pytest.raises(ValueError, match="format_modes"):
        generate_param_format_grid(JSON_MODE_MODEL, format_modes=[])


def test_empty_structured_output_modes_raises_value_error() -> None:
    import pytest

    with pytest.raises(ValueError, match="structured_output_modes"):
        generate_param_format_grid(JSON_MODE_MODEL, structured_output_modes=[])
