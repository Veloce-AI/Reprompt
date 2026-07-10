from pathlib import Path

import pytest

from refract_core.dag import CycleError, build_dag, format_dag, topological_layers
from refract_core.trace import Pipeline, Stage, load_trace_file

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def make_stage(id: str, depends_on: list[str] | None = None) -> Stage:
    return Stage(
        id=id,
        name=id,
        depends_on=depends_on or [],
        model="gpt-4o",
        prompt_template="{{input}}",
    )


def test_sequential_fixture_has_one_stage_per_layer() -> None:
    trace_file = load_trace_file(FIXTURES_DIR / "sequential_5stage.json")
    layers = topological_layers(trace_file.pipeline)
    assert [len(layer) for layer in layers] == [1, 1, 1, 1, 1]
    # Flattened order must respect every depends_on edge.
    order = [stage_id for layer in layers for stage_id in layer]
    stages_by_id = {s.id: s for s in trace_file.pipeline.stages}
    for stage_id in order:
        for dep in stages_by_id[stage_id].depends_on:
            assert order.index(dep) < order.index(stage_id)


def test_parallel_fixture_groups_the_two_branches_into_one_layer() -> None:
    trace_file = load_trace_file(FIXTURES_DIR / "parallel_2branch.json")
    layers = topological_layers(trace_file.pipeline)
    # Diamond: root -> {branch A, branch B} -> join. Exactly one layer must
    # contain 2+ stages (the parallel branches running concurrently).
    parallel_layers = [layer for layer in layers if len(layer) >= 2]
    assert len(parallel_layers) == 1
    assert len(parallel_layers[0]) == 2


def test_mixed_12stage_fixture_layers_respect_all_dependencies() -> None:
    trace_file = load_trace_file(FIXTURES_DIR / "mixed_12stage.json")
    layers = topological_layers(trace_file.pipeline)
    order = [stage_id for layer in layers for stage_id in layer]
    assert len(order) == 12
    assert len(set(order)) == 12  # every stage appears exactly once

    stages_by_id = {s.id: s for s in trace_file.pipeline.stages}
    layer_of = {
        stage_id: idx for idx, layer in enumerate(layers) for stage_id in layer
    }
    for stage in trace_file.pipeline.stages:
        for dep in stage.depends_on:
            assert layer_of[dep] < layer_of[stage.id]


def test_diamond_dependency() -> None:
    # A -> {B, C} -> D
    pipeline = Pipeline(
        id="p",
        name="diamond",
        stages=[
            make_stage("a"),
            make_stage("b", ["a"]),
            make_stage("c", ["a"]),
            make_stage("d", ["b", "c"]),
        ],
    )
    layers = topological_layers(pipeline)
    assert layers[0] == ["a"]
    assert set(layers[1]) == {"b", "c"}
    assert layers[2] == ["d"]


def test_orphan_stage_gets_its_own_layer_zero_slot() -> None:
    # "orphan" = no dependents and no dependencies; unrelated to the rest
    # of the graph, but still a perfectly valid single-node pipeline stage.
    pipeline = Pipeline(
        id="p",
        name="with-orphan",
        stages=[
            make_stage("a"),
            make_stage("b", ["a"]),
            make_stage("standalone"),
        ],
    )
    dag = build_dag(pipeline)
    assert dag.layer_of("standalone") == 0
    assert dag.layer_of("a") == 0
    assert dag.layer_of("b") == 1
    assert dag.stage_order.count("standalone") == 1


def test_two_stage_cycle_is_rejected_with_a_clear_error() -> None:
    # Each individual depends_on reference is valid (no self-reference, no
    # unknown id), so Pipeline's own schema validator lets this construct
    # cleanly — it takes actual graph traversal to see the loop.
    pipeline = Pipeline(
        id="p",
        name="cyclic",
        stages=[
            make_stage("a", ["b"]),
            make_stage("b", ["a"]),
        ],
    )
    with pytest.raises(CycleError) as exc_info:
        topological_layers(pipeline)
    assert set(exc_info.value.stage_ids) == {"a", "b"}
    assert "cycle" in str(exc_info.value)


def test_longer_cycle_is_rejected() -> None:
    # a -> b -> c -> a
    pipeline = Pipeline(
        id="p",
        name="cyclic-3",
        stages=[
            make_stage("a", ["c"]),
            make_stage("b", ["a"]),
            make_stage("c", ["b"]),
        ],
    )
    with pytest.raises(CycleError) as exc_info:
        topological_layers(pipeline)
    assert set(exc_info.value.stage_ids) == {"a", "b", "c"}


def test_cycle_error_only_names_the_unresolved_stages_not_the_whole_graph() -> None:
    # d depends on the (cyclic) a/b pair but is not itself part of the
    # cycle-error should still surface it as unresolved, since it can
    # never become ready either.
    pipeline = Pipeline(
        id="p",
        name="cyclic-plus-downstream",
        stages=[
            make_stage("a", ["b"]),
            make_stage("b", ["a"]),
            make_stage("d", ["b"]),
        ],
    )
    with pytest.raises(CycleError) as exc_info:
        topological_layers(pipeline)
    assert set(exc_info.value.stage_ids) == {"a", "b", "d"}


def test_format_dag_renders_readable_layers() -> None:
    trace_file = load_trace_file(FIXTURES_DIR / "mixed_12stage.json")
    text = format_dag(trace_file.pipeline)
    lines = text.splitlines()
    assert lines[0].startswith("Layer 0:")
    assert len(lines) == len(topological_layers(trace_file.pipeline))


def test_build_dag_stage_lookup() -> None:
    trace_file = load_trace_file(FIXTURES_DIR / "sequential_5stage.json")
    dag = build_dag(trace_file.pipeline)
    first_id = trace_file.pipeline.stages[0].id
    assert dag.stages[first_id] is trace_file.pipeline.stages[0]
    with pytest.raises(KeyError):
        dag.layer_of("does-not-exist")
