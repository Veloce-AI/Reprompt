"""Canonical trace-file schema (Reprompt's ingest format).

This module is the single source of truth for the JSON shape documented in
``docs/trace-format.md``. It has **zero FastAPI imports** — per the M0/M1
working rules, ``packages/core`` must stay runnable headless/CLI, so this
module only depends on the standard library and Pydantic v2.

Object graph (mirrors reprompt-parity-engine-plan.md §2):

    TraceFile                            (schema_version, default "1.1")
     ├── pipeline: Pipeline
     │    └── stages: list[Stage]        (id, name, depends_on[], model,
     │                                     prompt_template, system_prompt?,
     │                                     params, metadata)
     └── traces: list[Trace]             (one per benchmark query, metadata)
          └── records: list[StageRecord] (one per stage execution:
                                           input, rendered_prompt, output,
                                           tokens{in,out,thinking}? (optional),
                                           latency_ms? (optional), documents[],
                                           metadata)

``tokens`` and ``latency_ms`` are optional as of schema_version "1.1" — not
every trace source captures per-call accounting, and requiring it turned out
to exclude real-world traces we still want to ingest. ``metadata`` is a
free-form ``dict[str, Any]`` escape hatch present on ``Stage``, ``Trace``,
and ``StageRecord`` for product-specific extras (see docs/trace-format.md
for the recommended ``metadata.category`` grouping convention) — it exists
so callers don't need to widen this schema for every per-product field.

Use :func:`load_trace_file` / :func:`parse_trace_file` rather than calling
``TraceFile.model_validate`` directly when you want validation failures
reported as a short, field-level message instead of Pydantic's full
``ValidationError`` repr.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

__all__ = [
    "StageParams",
    "Stage",
    "Pipeline",
    "TokenUsage",
    "StageRecord",
    "Trace",
    "TraceFile",
    "TraceFileError",
    "format_pydantic_error",
    "parse_trace_file",
    "load_trace_file",
]

FormatMode = Literal["json", "xml", "markdown", "plain"]


class StageParams(BaseModel):
    """Model call parameters for a stage.

    All fields are optional — a stage need not pin every knob, and the
    optimizer (a later phase) is exactly the thing that searches this space.
    ``extra="allow"`` because target models sometimes expose provider-specific
    knobs (e.g. ``top_k``, ``reasoning_effort``) that we want to pass through
    without widening this schema for every provider.
    """

    model_config = ConfigDict(extra="allow")

    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, gt=0)
    format_mode: FormatMode | None = Field(
        default=None,
        description="Preferred output format/wrapping for this stage's prompt.",
    )


class Stage(BaseModel):
    """One node in a pipeline DAG."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="Unique (within the pipeline) stage id, e.g. 'extract_entities'.")
    name: str = Field(min_length=1, description="Human-readable stage name.")
    depends_on: list[str] = Field(
        default_factory=list,
        description="Ids of stages that must complete before this one runs. Empty for root stages.",
    )
    model: str = Field(
        min_length=1,
        description="LiteLLM-style model identifier for the benchmark run, e.g. 'gpt-4o-2024-08-06'.",
    )
    prompt_template: str = Field(
        min_length=1,
        description="Prompt template with {{variable}} placeholders resolved from upstream stage outputs.",
    )
    system_prompt: str | None = Field(
        default=None,
        description="Optional system prompt for this stage, kept separate from prompt_template "
        "(which is the user/task prompt). Null if the stage's source didn't capture one.",
    )
    params: StageParams = Field(default_factory=StageParams)
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form, product-specific extras. Not validated beyond being a JSON object — "
        "see docs/trace-format.md for the recommended 'category' key convention.",
    )


class Pipeline(BaseModel):
    """A named DAG of stages."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    stages: list[Stage] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_stage_graph(self) -> "Pipeline":
        ids = [s.id for s in self.stages]
        seen: set[str] = set()
        dupes: set[str] = set()
        for stage_id in ids:
            if stage_id in seen:
                dupes.add(stage_id)
            seen.add(stage_id)
        if dupes:
            raise ValueError(f"duplicate stage id(s): {sorted(dupes)}")

        id_set = set(ids)
        for stage in self.stages:
            for dep in stage.depends_on:
                if dep == stage.id:
                    raise ValueError(f"stage '{stage.id}' lists itself in depends_on")
                if dep not in id_set:
                    raise ValueError(
                        f"stage '{stage.id}' has depends_on referencing unknown stage id '{dep}'"
                    )
        # Note: cycle detection and topological ordering are deliberately NOT
        # implemented here — that's the DAG-builder phase, not schema
        # validation. This validator only checks referential integrity.
        return self


class TokenUsage(BaseModel):
    """Token accounting for a single stage call.

    Field names use the ``in``/``out``/``thinking`` JSON keys from the plan
    (``tokens{in, out, thinking}``) via aliases, since ``in`` is a reserved
    word in Python. ``populate_by_name=True`` means either the alias or the
    Python attribute name works when constructing from Python.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    input: int = Field(alias="in", ge=0, description="Input/prompt tokens consumed by this stage call.")
    output: int = Field(alias="out", ge=0, description="Output/completion tokens produced by this stage call.")
    thinking: int | None = Field(
        default=None,
        ge=0,
        description="Reasoning/thinking tokens, if the model exposes them. Omit or null otherwise.",
    )


class StageRecord(BaseModel):
    """One stage's execution within one trace."""

    model_config = ConfigDict(extra="forbid")

    stage_id: str = Field(min_length=1, description="Must match a Stage.id in the pipeline this trace belongs to.")
    input: dict[str, Any] = Field(
        default_factory=dict,
        description="Resolved input variables fed into this stage's prompt template.",
    )
    rendered_prompt: str = Field(min_length=1, description="The exact prompt text sent to the model.")
    output: str = Field(description="The raw model output/completion text for this stage.")
    tokens: TokenUsage | None = Field(
        default=None,
        description="Token accounting for this call, if the trace source captured it. Optional as of "
        "schema_version 1.1 — not every trace source reports per-call token usage.",
    )
    latency_ms: float | None = Field(
        default=None,
        ge=0,
        description="Wall-clock latency of this stage's model call, in milliseconds, if known. Optional "
        "as of schema_version 1.1 — not every trace source reports it.",
    )
    cost: float | None = Field(
        default=None,
        ge=0,
        description="Actual $ cost of this stage's model call, if known. Central to the product's cost-reduction "
        "pitch, but optional since not every trace source reports it (our own synthetic fixtures don't).",
    )
    documents: list[str] = Field(
        default_factory=list,
        description="Plain-text supporting documents for this stage call (e.g. retrieved passages), "
        "unstructured — no per-document metadata/scoring, just the raw text.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form, product-specific extras. Not validated beyond being a JSON object — "
        "see docs/trace-format.md for the recommended 'category' key convention.",
    )


class Trace(BaseModel):
    """One full DAG execution — all stage records for a single benchmark query."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1)
    query: dict[str, Any] = Field(description="The original input to the pipeline for this benchmark query.")
    records: list[StageRecord] = Field(min_length=1)
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form, product-specific extras. Not validated beyond being a JSON object — "
        "see docs/trace-format.md for the recommended 'category' key convention.",
    )

    @model_validator(mode="after")
    def _validate_unique_stage_records(self) -> "Trace":
        seen: set[str] = set()
        dupes: set[str] = set()
        for record in self.records:
            if record.stage_id in seen:
                dupes.add(record.stage_id)
            seen.add(record.stage_id)
        if dupes:
            raise ValueError(f"trace '{self.trace_id}' has duplicate stage_id record(s): {sorted(dupes)}")
        return self


class TraceFile(BaseModel):
    """Top-level ingest document: a pipeline definition plus its benchmark traces."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="1.1",
        description="Trace-format schema version. \"1.0\" files still validate — 1.1 only adds/relaxes "
        "fields (tokens/latency_ms optional, plus documents/metadata/system_prompt).",
    )
    pipeline: Pipeline
    traces: list[Trace] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_records_reference_known_stages(self) -> "TraceFile":
        stage_ids = {s.id for s in self.pipeline.stages}
        errors: list[str] = []
        for trace_idx, trace in enumerate(self.traces):
            for record_idx, record in enumerate(trace.records):
                if record.stage_id not in stage_ids:
                    errors.append(
                        f"traces[{trace_idx}] (trace_id='{trace.trace_id}') "
                        f"records[{record_idx}]: stage_id '{record.stage_id}' "
                        "does not match any pipeline stage id"
                    )
        if errors:
            raise ValueError("; ".join(errors))
        return self


class TraceFileError(ValueError):
    """A trace file failed schema validation.

    Carries a short, human-readable, field-level message (see
    :func:`format_pydantic_error`) instead of Pydantic's full error dump.
    """


def format_pydantic_error(exc: ValidationError) -> str:
    """Render a Pydantic ValidationError as a short list of '<location>: <reason>' lines."""
    lines = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<root>"
        lines.append(f"  - {loc}: {err['msg']}")
    count = len(lines)
    return "Trace file failed validation ({} error{}):\n{}".format(
        count, "" if count == 1 else "s", "\n".join(lines)
    )


def parse_trace_file(data: dict[str, Any]) -> TraceFile:
    """Validate a raw dict (already-parsed JSON) against the TraceFile schema.

    Raises TraceFileError with a concise, field-level message on failure —
    never a raw Pydantic ValidationError.
    """
    try:
        return TraceFile.model_validate(data)
    except ValidationError as exc:
        raise TraceFileError(format_pydantic_error(exc)) from exc


def load_trace_file(path: str | Path) -> TraceFile:
    """Read and validate a trace file from disk."""
    file_path = Path(path)
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TraceFileError(f"Could not read trace file '{file_path}': {exc}") from exc
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise TraceFileError(f"Trace file '{file_path}' is not valid JSON: {exc}") from exc
    return parse_trace_file(data)
