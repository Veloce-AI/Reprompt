"""Minimal, stdlib-only trace recorder for Reprompt's trace-format (schema
version "1.1" - see ../trace-format.md).

Copy this file into your own codebase and adapt it - no dependency on
Reprompt itself. Only stdlib (json, dataclasses, typing) is used, so it
drops into any Python 3.9+ project without adding reprompt-core/Pydantic as
a dependency. It does not validate its own output against the schema - run
the result through reprompt_core.parse_trace_file, or check it against
../trace-format.schema.json (also served at GET /trace-format/schema), if
you want that.

Usage sketch:

    rec = TraceRecorder(pipeline_id="support-triage", pipeline_name="Support triage")
    rec.start_trace("t-001", query={"ticket_text": "..."})
    rec.record_stage("extract", rendered_prompt="...", output="...")
    trace_file = rec.dump()  # dict, ready for json.dump()
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _StageRecord:
    stage_id: str
    rendered_prompt: str
    output: str
    input: dict[str, Any] = field(default_factory=dict)
    tokens: dict[str, int] | None = None
    latency_ms: float | None = None
    documents: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "stage_id": self.stage_id,
            "input": self.input,    
            "rendered_prompt": self.rendered_prompt,
            "output": self.output,
            "documents": self.documents,
            "metadata": self.metadata,
        }
        if self.tokens is not None:
            record["tokens"] = self.tokens
        if self.latency_ms is not None:
            record["latency_ms"] = self.latency_ms
        return record


class TraceRecorder:
    """Accumulates one pipeline's stages plus its traces, then dumps a
    schema-1.1-shaped trace file. One recorder per pipeline; call
    start_trace() again to begin a new query/trace within it.
    """

    def __init__(self, pipeline_id: str, pipeline_name: str) -> None:
        self.pipeline_id = pipeline_id
        self.pipeline_name = pipeline_name
        self._stage_order: list[str] = []  # first-record-wins stage definitions
        self._stages: dict[str, dict[str, Any]] = {}
        self._traces: list[dict[str, Any]] = []
        self._current_records: list[_StageRecord] | None = None

    def start_trace(self, trace_id: str, query: dict[str, Any], metadata: dict[str, Any] | None = None) -> None:
        """Begin a new trace (one full pipeline execution for one query)."""
        self._current_records = []
        self._traces.append(
            {"trace_id": trace_id, "query": query, "metadata": metadata or {}, "records": self._current_records}
        )

    def record_stage(
        self,
        stage_id: str,
        rendered_prompt: str,
        output: str,
        *,
        stage_name: str | None = None,
        model: str = "unknown",
        depends_on: list[str] | None = None,
        input: dict[str, Any] | None = None,  # noqa: A002 - mirrors trace-format's StageRecord.input naming
        tokens: dict[str, int] | None = None,
        latency_ms: float | None = None,
        documents: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record one stage's execution within the current trace.

        `tokens` and `latency_ms` are optional (schema 1.1) - leave them
        None if your pipeline doesn't capture per-call accounting; the
        resulting trace file still validates.
        """
        if self._current_records is None:
            raise RuntimeError("call start_trace() before record_stage()")

        if stage_id not in self._stages:
            self._stage_order.append(stage_id)
            self._stages[stage_id] = {
                "id": stage_id,
                "name": stage_name or stage_id,
                "depends_on": depends_on or [],
                "model": model,
                "prompt_template": rendered_prompt,
            }

        self._current_records.append(
            _StageRecord(
                stage_id=stage_id,
                rendered_prompt=rendered_prompt,
                output=output,
                input=input or {},
                tokens=tokens,
                latency_ms=latency_ms,
                documents=documents or [],
                metadata=metadata or {},
            )
        )

    def dump(self) -> dict[str, Any]:
        """Return the accumulated pipeline + traces as a TraceFile-shaped dict."""
        return {
            "schema_version": "1.1",
            "pipeline": {
                "id": self.pipeline_id,
                "name": self.pipeline_name,
                "stages": [self._stages[stage_id] for stage_id in self._stage_order],
            },
            "traces": [
                {**t, "records": [r.to_dict() for r in t["records"]]} for t in self._traces
            ],
        }


if __name__ == "__main__":
    # Demo: a two-stage pipeline, one trace, NO tokens/latency on either
    # record - proving the schema-1.1 minimal case works end to end.
    rec = TraceRecorder(pipeline_id="support-triage", pipeline_name="Support ticket triage")
    rec.start_trace("trace-001", query={"ticket_text": "My invoice #4471 charged me twice this month."})
    rec.record_stage(
        "extract",
        stage_name="Extract ticket facts",
        model="gpt-4o-mini",
        input={"ticket_text": "My invoice #4471 charged me twice this month."},
        rendered_prompt="Extract the customer's issue as JSON:\n\nMy invoice #4471 charged me twice this month.",
        output='{"issue_type": "billing", "invoice_id": "4471", "complaint": "duplicate_charge"}',
    )
    rec.record_stage(
        "summarize",
        stage_name="Summarize for agent handoff",
        model="claude-sonnet-4-5",
        depends_on=["extract"],
        input={"extract.output": '{"issue_type": "billing", "invoice_id": "4471"}'},
        rendered_prompt='Summarize this issue in one sentence:\n\n{"issue_type": "billing", "invoice_id": "4471"}',
        output="Customer was double-charged on invoice #4471 and needs a refund.",
    )
    print(json.dumps(rec.dump(), indent=2))
