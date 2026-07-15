"""DAG builder for pipeline stage graphs.

Turns a validated :class:`~reprompt_core.trace.Pipeline` into a topologically
ordered set of layers, where every stage in a layer only depends on stages in
earlier layers — i.e. all stages within one layer can execute in parallel.

``Pipeline`` already guarantees referential integrity (no unknown
``depends_on`` ids, no stage depending on itself) via its own schema
validator in ``trace.py``. What that validator does *not* catch is a cycle
spanning two or more stages (e.g. A depends on B, B depends on A) — each
individual edge is valid on its own, so schema validation alone can't see
the loop. That is exactly what this module checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from reprompt_core.trace import Pipeline, Stage

__all__ = ["CycleError", "DAG", "build_dag", "topological_layers", "format_dag"]


class CycleError(ValueError):
    """Raised when the stage graph contains a cycle.

    ``stage_ids`` lists the stages involved in (or downstream of) the cycle —
    every stage that Kahn's algorithm could not resolve because its
    dependencies never all reached zero.
    """

    def __init__(self, stage_ids: list[str]):
        self.stage_ids = stage_ids
        super().__init__(
            f"pipeline stage graph has a cycle involving stage(s): {sorted(stage_ids)}"
        )


@dataclass
class DAG:
    """A pipeline's stages, topologically layered for execution."""

    stages: dict[str, Stage]
    layers: list[list[str]] = field(default_factory=list)

    def layer_of(self, stage_id: str) -> int:
        """Index of the layer containing ``stage_id`` (0-based)."""
        for index, layer in enumerate(self.layers):
            if stage_id in layer:
                return index
        raise KeyError(f"unknown stage id: {stage_id!r}")

    @property
    def stage_order(self) -> list[str]:
        """A single flat topological ordering (layers concatenated)."""
        return [stage_id for layer in self.layers for stage_id in layer]


def topological_layers(pipeline: Pipeline) -> list[list[str]]:
    """Kahn's algorithm, grouped into parallel-execution layers.

    Layer 0 = every stage with no dependencies. Layer N = every stage whose
    dependencies were all satisfied by layers 0..N-1. Within a layer, stage
    order is deterministic (pipeline definition order) so output is stable
    across runs, which matters for test assertions and UI rendering.

    Raises :class:`CycleError` if any stages remain unresolved once no more
    zero-in-degree stages can be found.
    """
    stages_by_id = {stage.id: stage for stage in pipeline.stages}
    in_degree = {stage.id: len(stage.depends_on) for stage in pipeline.stages}
    dependents: dict[str, list[str]] = {stage.id: [] for stage in pipeline.stages}
    for stage in pipeline.stages:
        for dep in stage.depends_on:
            dependents[dep].append(stage.id)

    remaining = set(stages_by_id)
    layers: list[list[str]] = []

    while remaining:
        # Deterministic order: iterate stages in original definition order,
        # not set/dict iteration order.
        ready = [
            stage.id
            for stage in pipeline.stages
            if stage.id in remaining and in_degree[stage.id] == 0
        ]
        if not ready:
            raise CycleError(sorted(remaining))

        layers.append(ready)
        for stage_id in ready:
            remaining.discard(stage_id)
            for dependent_id in dependents[stage_id]:
                in_degree[dependent_id] -= 1

    return layers


def build_dag(pipeline: Pipeline) -> DAG:
    """Validate and build a full :class:`DAG` for a pipeline."""
    layers = topological_layers(pipeline)
    stages_by_id = {stage.id: stage for stage in pipeline.stages}
    return DAG(stages=stages_by_id, layers=layers)


def format_dag(pipeline: Pipeline) -> str:
    """Render a pipeline's layered DAG as a human-readable string.

    Example::

        Layer 0: ingest
        Layer 1: extract_entities, extract_topics
        Layer 2: summarize
    """
    dag = build_dag(pipeline)
    lines = [
        f"Layer {index}: {', '.join(layer)}" for index, layer in enumerate(dag.layers)
    ]
    return "\n".join(lines)
