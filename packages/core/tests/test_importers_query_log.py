"""Tests for the query-log importer, run against the REAL sample trace files.

These are not synthetic fixtures — ``Sample Queries/*.txt`` (despite the
extension, plain JSON) are actual production traces from a legal/tax
research-assistant pipeline. The point of testing against them directly is
that they exercise real irregularities (parallel fan-out via repeated stage
names, non-adjacent name repeats, dict-typed responses) that a hand-rolled
synthetic fixture would be tempted to smooth over.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from refract_core.dag import build_dag, topological_layers
from refract_core.importers.query_log import convert, convert_file
from refract_core.trace import parse_trace_file

# Sample Queries/ lives at the repo root: packages/core/tests/../../../Sample Queries
SAMPLE_QUERIES_DIR = Path(__file__).resolve().parents[3] / "Sample Queries"

SHORT_FILE = SAMPLE_QUERIES_DIR / "7ec0b148-b4dd-4211-bbd7-700009708660.txt"
LONG_FILE_A = SAMPLE_QUERIES_DIR / "0f586e25-0f0e-4ab8-911f-ec3fafed9232.txt"
LONG_FILE_B = SAMPLE_QUERIES_DIR / "7eb538d9-e759-4e89-86a5-5a6363887275.txt"

pytestmark = pytest.mark.skipif(
    not SAMPLE_QUERIES_DIR.is_dir(),
    reason="real 'Sample Queries' fixtures are not present in this checkout",
)


def _load_raw(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", [SHORT_FILE, LONG_FILE_A, LONG_FILE_B])
def test_real_file_converts_to_a_valid_trace_file(path: Path) -> None:
    """End-to-end: convert a real file, validate it, and prove the inferred
    dependency graph is a genuine DAG (no cycles) via build_dag()."""
    raw = _load_raw(path)
    trace_file = parse_trace_file(convert(raw))

    assert trace_file.pipeline.stages
    assert len(trace_file.traces) == 1
    assert trace_file.traces[0].records

    # Proves the dependency-inference rule produces a *valid* DAG, not just
    # plausible-looking depends_on lists: build_dag() runs Kahn's algorithm
    # and raises CycleError on any loop.
    dag = build_dag(trace_file.pipeline)
    assert len(dag.stage_order) == len(trace_file.pipeline.stages)


@pytest.mark.parametrize("path", [SHORT_FILE, LONG_FILE_A, LONG_FILE_B])
def test_no_stage_is_collapsed_or_dropped(path: Path) -> None:
    """Every raw stages[] entry — including repeated-name ones — becomes its
    own distinct Stage and StageRecord. This is the exact scenario the
    canonical schema's duplicate-stage_id validator would reject if the
    importer collapsed repeats instead of disambiguating them."""
    raw = _load_raw(path)
    trace_file = parse_trace_file(convert(raw))

    assert len(trace_file.pipeline.stages) == len(raw["stages"])
    assert len(trace_file.traces[0].records) == len(raw["stages"])


def test_query_text_is_wrapped_and_preserved() -> None:
    raw = _load_raw(SHORT_FILE)
    trace_file = parse_trace_file(convert(raw))

    assert trace_file.traces[0].query == {"text": raw["query"]}
    assert raw["query"] == "section 37 of 1961 vs relevant section of 2025"


def test_trace_id_comes_from_query_id() -> None:
    raw = _load_raw(SHORT_FILE)
    trace_file = parse_trace_file(convert(raw))
    assert trace_file.traces[0].trace_id == raw["query_id"]


def test_short_file_is_a_straight_three_stage_chain() -> None:
    """The 3-stage file has no repeated stage names, so every step is size 1:
    a plain sequential chain, each stage depending only on its immediate
    predecessor, first stage a root."""
    raw = _load_raw(SHORT_FILE)
    trace_file = parse_trace_file(convert(raw))
    stages = trace_file.pipeline.stages

    assert [s.name for s in stages] == [
        "determine_query_type_system_prompt_query_type",
        "ita_system_prompt_extract_sections",
        "ita_response_generation",
    ]
    assert stages[0].depends_on == []
    assert stages[1].depends_on == [stages[0].id]
    assert stages[2].depends_on == [stages[1].id]


def test_first_stage_fields_match_the_source_exactly() -> None:
    """Hand-verified against the raw file: stages[0] of the short sample."""
    raw = _load_raw(SHORT_FILE)
    trace_file = parse_trace_file(convert(raw))

    stage = trace_file.pipeline.stages[0]
    record = trace_file.traces[0].records[0]
    raw_stage = raw["stages"][0]
    raw_stats = raw_stage["stats"]
    raw_io = raw_stage["io"]

    assert raw_stage["stage"] == "determine_query_type_system_prompt_query_type"
    assert raw_stats["input_tokken"] == 9714
    assert raw_stats["output_tokken"] == 171
    assert raw_stats["thinking_tokken"] == 238
    assert raw_stats["llm_type"] == "Gemini 2.5 flash"
    assert raw_stats["response_time"] == 4352
    assert raw_stats["stage_cost"] == 0.003937

    assert stage.model == "Gemini 2.5 flash"
    assert stage.prompt_template == raw_io["system_prompt"]

    assert record.stage_id == stage.id
    assert record.tokens.input == 9714
    assert record.tokens.output == 171
    assert record.tokens.thinking == 238
    assert record.latency_ms == 4352
    assert record.cost == 0.003937
    assert record.rendered_prompt == raw_io["system_prompt"]


def test_parallel_group_siblings_share_predecessors_but_not_each_other() -> None:
    """Verified in the raw file: stages[1..3] of LONG_FILE_A are three
    consecutive entries named
    'query_calssification_and_rephrasing_research_using_system_prompt_relevancy_practice_parallel'
    with near-identical token counts — a parallel fan-out group. Per the
    dependency-inference rule, all three must depend on exactly the single
    predecessor step (stage 0) and NOT on each other; the next sequential
    stage (index 4) must depend on all three of them."""
    raw = _load_raw(LONG_FILE_A)
    raw_stages = sorted(raw["stages"], key=lambda s: s["index"])
    assert raw_stages[1]["stage"] == raw_stages[2]["stage"] == raw_stages[3]["stage"]
    parallel_name = raw_stages[1]["stage"]
    assert raw_stages[4]["stage"] != parallel_name

    trace_file = parse_trace_file(convert(raw))
    stages = trace_file.pipeline.stages
    stages_by_name = {}
    for s in stages:
        stages_by_name.setdefault(s.name, []).append(s)

    siblings = stages_by_name[parallel_name]
    assert len(siblings) == 3
    assert {s.id for s in siblings} == {f"{parallel_name}#1", f"{parallel_name}#2", f"{parallel_name}#3"}

    root_id = stages[0].id
    for sib in siblings:
        assert sib.depends_on == [root_id]

    sibling_ids = {s.id for s in siblings}
    next_stage = stages_by_name[raw_stages[4]["stage"]][0]
    assert set(next_stage.depends_on) == sibling_ids


def test_non_adjacent_repeated_stage_name_gets_an_occurrence_suffix() -> None:
    """Verified in the raw file: 'get_relevant_parent_ids_system_prompt_relevantParentId'
    appears as two SEPARATE, non-adjacent single-entry steps (indices 8 and
    11 in LONG_FILE_A) — not a parallel group. The importer must still give
    each a distinct id (occurrence-suffix rule), and they must not end up
    depending on each other just because they share a name."""
    raw = _load_raw(LONG_FILE_A)
    name = "get_relevant_parent_ids_system_prompt_relevantParentId"
    occurrences = [s for s in raw["stages"] if s["stage"] == name]
    assert len(occurrences) == 2
    assert occurrences[1]["index"] - occurrences[0]["index"] > 1  # non-adjacent

    trace_file = parse_trace_file(convert(raw))
    matches = [s for s in trace_file.pipeline.stages if s.name == name]
    assert len(matches) == 2
    assert matches[0].id == name
    assert matches[1].id == f"{name}__2"
    assert matches[0].id not in matches[1].depends_on
    assert matches[1].id not in matches[0].depends_on


@pytest.mark.parametrize("path", [LONG_FILE_A, LONG_FILE_B])
def test_totals_reconcile_with_per_stage_sums(path: Path) -> None:
    """Cross-check against the source's own reported totals block — not
    part of the canonical schema, but a good sanity signal that token/cost
    mapping didn't drop or double-count anything."""
    raw = _load_raw(path)
    trace_file = parse_trace_file(convert(raw))
    records = trace_file.traces[0].records

    assert sum(r.tokens.input for r in records) == raw["totals"]["total_input_tokens"]
    assert sum(r.tokens.output for r in records) == raw["totals"]["total_output_tokens"]
    # abs=1e-5: the source's own "totals" block is itself a rounded
    # re-aggregation (visible in path1: sum of the 35 raw stage_cost values
    # is 0.900415, "totals.total_cost" reports 0.900416) — a float
    # accumulation artifact in the SOURCE data, not something this importer
    # introduces. A tight relative tolerance would fail on that pre-existing
    # rounding; this still catches any real mapping bug (missed/duplicated
    # stage) which would be off by orders of magnitude more.
    assert sum(r.cost or 0 for r in records) == pytest.approx(raw["totals"]["total_cost"], abs=1e-5)


def test_dict_typed_response_is_serialized_losslessly() -> None:
    """Verified in the raw file: some io.response values are already-parsed
    dicts (not strings). StageRecord.output is typed str, so these must be
    JSON-serialized, not stringified via repr() or dropped."""
    raw = _load_raw(LONG_FILE_A)
    dict_response_indices = [s["index"] for s in raw["stages"] if isinstance(s["io"]["response"], dict)]
    assert dict_response_indices  # sanity: the real file does have at least one

    trace_file = parse_trace_file(convert(raw))
    idx = dict_response_indices[0]
    raw_response = raw["stages"][idx]["io"]["response"]
    record = trace_file.traces[0].records[idx]

    assert json.loads(record.output) == raw_response


def test_convert_file_matches_convert_on_parsed_json() -> None:
    direct = parse_trace_file(convert(_load_raw(SHORT_FILE)))
    via_file = parse_trace_file(convert_file(SHORT_FILE))
    assert direct.model_dump() == via_file.model_dump()


@pytest.mark.parametrize("path", [SHORT_FILE, LONG_FILE_A, LONG_FILE_B])
def test_topological_layers_respect_every_inferred_dependency(path: Path) -> None:
    raw = _load_raw(path)
    trace_file = parse_trace_file(convert(raw))
    layers = topological_layers(trace_file.pipeline)

    layer_of = {sid: i for i, layer in enumerate(layers) for sid in layer}
    for stage in trace_file.pipeline.stages:
        for dep in stage.depends_on:
            assert layer_of[dep] < layer_of[stage.id]
