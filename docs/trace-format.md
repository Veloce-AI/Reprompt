# Trace format

Canonical JSON schema Reprompt uses to ingest a pipeline plus its benchmark
traces. This is Reprompt's own format — Langfuse exports, OTel traces, etc.
are normalized *into* this shape by importers; nothing downstream of ingest
should know about any other trace format.

The schema is implemented as Pydantic v2 models in
[`packages/core/src/reprompt_core/trace.py`](../packages/core/src/reprompt_core/trace.py)
(`TraceFile` is the root model). That module is the source of truth if this
doc and the code ever disagree — but they shouldn't; keep both in sync.

A trace file is a single JSON document with two top-level parts:

1. **`pipeline`** — the DAG definition: stages, their dependencies, the
   model/prompt/params used to *produce* the benchmark traces.
2. **`traces`** — the benchmark set itself: one entry per query, each a full
   record of every stage's execution for that query.

This mirrors reprompt-parity-engine-plan.md §2: `Pipeline → Stage[]`,
`Pipeline → BenchmarkSet → Trace[] → StageRecord`.

## Top level: `TraceFile`

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | string | no (default `"1.1"`) | Bump when the shape changes. |
| `pipeline` | [`Pipeline`](#pipeline) | yes | The DAG that produced these traces. |
| `traces` | array of [`Trace`](#trace) | yes, min 1 | The benchmark set (optimize/holdout split happens later, at ingest time — not encoded in the file). |

Cross-object rule enforced at this level: every `records[].stage_id` in
every trace must match a `pipeline.stages[].id`. Unknown extra top-level
keys are rejected (`extra="forbid"`), to catch typos and format drift early.

### Schema version 1.1 and backward compatibility

`schema_version` bumped `"1.0"` → `"1.1"`. Every 1.1 change is additive or a
relaxation of a previously-required field — **no field that validated under
1.0 stopped validating under 1.1**, so existing `"1.0"` trace files (or files
that omit `schema_version` and pick up the old implicit default) still
validate as-is, no migration needed. What changed:

- `StageRecord.tokens` and `StageRecord.latency_ms` are now optional
  (previously required) — see [`StageRecord`](#stagerecord).
- `StageRecord.documents` was added (default `[]`).
- `metadata` (default `{}`) was added to `Stage`, `Trace`, and `StageRecord`.
- `Stage.system_prompt` was added (default `null`).

`schema_version` itself isn't checked against an enum — it's a plain string
field, purely informational for now (a future importer/version-gate could
branch on it, but nothing in `packages/core/src/reprompt_core/trace.py` does
today).

## `Pipeline`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Unique pipeline identifier. |
| `name` | string | yes | Human-readable name. |
| `stages` | array of [`Stage`](#stage) | yes, min 1 | The DAG's nodes. |

Validated: stage `id`s are unique within the pipeline, and every
`depends_on` entry references a real sibling stage id (no self-dependency
either). **Cycle detection and topological ordering are intentionally not
implemented here** — that's the DAG-builder phase (M1.2), which consumes
this validated schema. This layer only checks referential integrity.

## `Stage`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Unique within the pipeline, e.g. `"extract_entities"`. Used as the join key for `StageRecord.stage_id` and by other stages' `depends_on`. |
| `name` | string | yes | Human-readable stage name. |
| `depends_on` | array of string | no (default `[]`) | Ids of stages that must complete before this one runs. Empty = a root/entry stage. **Parallel branches are represented implicitly**: two stages that both list the same upstream id in `depends_on` (and don't depend on each other) are parallel; a stage that lists multiple ids in `depends_on` is a join/fan-in point. There is no separate "branch" or "parallel group" construct in the JSON — that structure is *derived* from the dependency graph by the DAG builder, not declared. |
| `model` | string | yes | LiteLLM-style model identifier used for the benchmark run, e.g. `"gpt-4o-2024-08-06"`, `"claude-3-5-sonnet-20241022"`, `"gemini-1.5-pro"`. |
| `prompt_template` | string | yes | Prompt template with `{{variable}}` placeholders, resolved per-query from the pipeline query and/or upstream stage outputs. |
| `system_prompt` | string or `null` | no (default `null`) | Optional system prompt for this stage, kept separate from `prompt_template` (the user/task prompt). Null if the stage's source didn't capture one. |
| `params` | [`StageParams`](#stageparams) | no (defaults to all-null) | Model call parameters used for the benchmark run. |
| `metadata` | object | no (default `{}`) | Free-form, product-specific extras. See [Metadata convention](#metadata-convention). |

## `StageParams`

| Field | Type | Required | Notes |
|---|---|---|---|
| `temperature` | float, `0`–`2` | no | |
| `top_p` | float, `0`–`1` | no | |
| `max_tokens` | int, `>0` | no | |
| `format_mode` | one of `"json"`, `"xml"`, `"markdown"`, `"plain"` | no | Output format/wrapping convention the prompt asks for. |

Extra provider-specific keys (e.g. `top_k`, `reasoning_effort`) are allowed
and passed through as-is — the schema doesn't enumerate every provider's
knobs.

## `Trace`

One full DAG execution for one benchmark query.

| Field | Type | Required | Notes |
|---|---|---|---|
| `trace_id` | string | yes | Unique within the file. |
| `query` | object | yes | The original input to the pipeline for this query. An object (not a bare string) because most real pipelines take structured input (e.g. `{"company": "Acme Corp", "filing_year": 2024}`), and this is the same value later drives holdout-split bookkeeping. |
| `records` | array of [`StageRecord`](#stagerecord) | yes, min 1 | One record per stage that executed for this query. |
| `metadata` | object | no (default `{}`) | Free-form, product-specific extras. See [Metadata convention](#metadata-convention). |

Validated: `records[].stage_id` values are unique within a trace (a stage
executes at most once per query in the benchmark run — no retries encoded
in this format; a retry would just be a different trace).

## `StageRecord`

| Field | Type | Required | Notes |
|---|---|---|---|
| `stage_id` | string | yes | Must match a `pipeline.stages[].id`. |
| `input` | object | no (default `{}`) | Resolved input variables fed into this stage's prompt template (post dependency-resolution, pre-rendering). |
| `rendered_prompt` | string | yes | The exact, fully-rendered prompt text sent to the model — this is what optimization mutates. |
| `output` | string | yes | The raw model output/completion text for this stage. |
| `tokens` | [`TokenUsage`](#tokenusage) or `null` | no (default `null`) | Token accounting for this call, if the trace source captured it. Optional as of schema_version 1.1. |
| `latency_ms` | float, `>=0`, or `null` | no (default `null`) | Wall-clock latency of this stage's model call, if known. Optional as of schema_version 1.1. |
| `cost` | float, `>=0`, or `null` | no (default `null`) | Actual $ cost of this stage's model call, if known. |
| `documents` | array of string | no (default `[]`) | Plain-text supporting documents for this stage call (e.g. retrieved passages) — unstructured, no per-document metadata or scoring. |
| `metadata` | object | no (default `{}`) | Free-form, product-specific extras. See [Metadata convention](#metadata-convention). |

## `TokenUsage`

| Field | JSON key | Type | Required | Notes |
|---|---|---|---|---|
| `input` | `in` | int, `>=0` | yes | Prompt tokens consumed. |
| `output` | `out` | int, `>=0` | yes | Completion tokens produced. |
| `thinking` | `thinking` | int, `>=0` or `null` | no | Reasoning/thinking tokens, for models that expose them (e.g. extended-thinking Claude, o-series). Omit or `null` for models without a reasoning budget. |

JSON keys are `in`/`out`/`thinking` per the plan's `tokens{in, out, thinking}`
shape (`in` can't be a Python attribute name, so the Python model aliases
`input`/`output` to `in`/`out`; either the alias or the attribute name works
when constructing the model from Python).

## Validation errors

Don't call `TraceFile.model_validate(...)` directly if you want readable
errors — Pydantic's raw `ValidationError` is a full dump of every failure
with internal type names. Use `reprompt_core.load_trace_file(path)` (from
disk) or `reprompt_core.parse_trace_file(dict)` (already-parsed JSON)
instead. Both raise `reprompt_core.TraceFileError` — a `ValueError` subclass —
with a short, field-level message, e.g.:

```
Trace file failed validation (2 errors):
  - pipeline.stages.1.model: Field required
  - traces.0.records.2.stage_id: stage_id 'summarize_v2' does not match any pipeline stage id
```

## Annotated example

A minimal two-stage pipeline (`extract` → `summarize`) with one trace. See
`packages/core/tests/fixtures/` for full realistic examples (5-stage
sequential, 2-branch parallel, 12-stage mixed-model).

```jsonc
{
  "schema_version": "1.0",
  "pipeline": {
    "id": "support-ticket-triage",
    "name": "Support ticket triage",
    "stages": [
      {
        "id": "extract",
        "name": "Extract ticket facts",
        "depends_on": [],                          // root stage: no upstream dependency
        "model": "gpt-4o-mini-2024-07-18",
        "prompt_template": "Extract the customer's issue as JSON:\n\n{{ticket_text}}",
        "params": { "temperature": 0.1, "format_mode": "json" }
      },
      {
        "id": "summarize",
        "name": "Summarize for agent handoff",
        "depends_on": ["extract"],                  // runs after 'extract'
        "model": "claude-3-5-sonnet-20241022",
        "prompt_template": "Summarize this issue in one sentence:\n\n{{extract.output}}",
        "params": { "temperature": 0.3, "max_tokens": 200 }
      }
    ]
  },
  "traces": [
    {
      "trace_id": "trace-001",
      "query": { "ticket_text": "My invoice #4471 charged me twice this month." },
      "records": [
        {
          "stage_id": "extract",
          "input": { "ticket_text": "My invoice #4471 charged me twice this month." },
          "rendered_prompt": "Extract the customer's issue as JSON:\n\nMy invoice #4471 charged me twice this month.",
          "output": "{\"issue_type\": \"billing\", \"invoice_id\": \"4471\", \"complaint\": \"duplicate_charge\"}",
          "tokens": { "in": 42, "out": 28 },          // no 'thinking' key: this model has no reasoning budget
          "latency_ms": 612.4
        },
        {
          "stage_id": "summarize",
          "input": { "extract.output": "{\"issue_type\": \"billing\", \"invoice_id\": \"4471\", \"complaint\": \"duplicate_charge\"}" },
          "rendered_prompt": "Summarize this issue in one sentence:\n\n{\"issue_type\": \"billing\", \"invoice_id\": \"4471\", \"complaint\": \"duplicate_charge\"}",
          "output": "Customer was double-charged on invoice #4471 and needs a refund.",
          "tokens": { "in": 58, "out": 17, "thinking": 0 },
          "latency_ms": 891.0
        }
      ]
    }
  ]
}
```

## Annotated example: `system_prompt`, `documents`, and `metadata` (schema 1.1)

Same two-stage pipeline, extended to use every field schema_version 1.1
added. The `extract` stage's record also demonstrates the bare-minimum
case — no `tokens`, no `latency_ms`, no `cost` — validating cleanly
alongside a full record.

```jsonc
{
  "schema_version": "1.1",
  "pipeline": {
    "id": "support-ticket-triage",
    "name": "Support ticket triage",
    "stages": [
      {
        "id": "extract",
        "name": "Extract ticket facts",
        "model": "gpt-4o-mini-2024-07-18",
        "system_prompt": "You are a support-ticket triage assistant. Always respond with strict JSON.",
        "prompt_template": "Extract the customer's issue as JSON:\n\n{{ticket_text}}",
        "params": { "temperature": 0.1, "format_mode": "json" },
        "metadata": { "category": "extraction" }        // see Metadata convention below
      }
    ]
  },
  "traces": [
    {
      "trace_id": "trace-001",
      "query": { "ticket_text": "My invoice #4471 charged me twice this month." },
      "metadata": { "category": "billing_disputes", "source": "prod-log-2026-07" },
      "records": [
        {
          "stage_id": "extract",
          "input": { "ticket_text": "My invoice #4471 charged me twice this month." },
          "rendered_prompt": "Extract the customer's issue as JSON:\n\nMy invoice #4471 charged me twice this month.",
          "output": "{\"issue_type\": \"billing\", \"invoice_id\": \"4471\", \"complaint\": \"duplicate_charge\"}",
          // no 'tokens', 'latency_ms', or 'cost': this source didn't capture
          // per-call accounting - all three are optional as of schema 1.1.
          "documents": [
            "Refund policy: duplicate charges are refunded within 3 business days.",
            "Invoice #4471 history: charged 2026-07-08, charged again 2026-07-09."
          ],
          "metadata": { "category": "extraction", "retrieval_strategy": "bm25" }
        }
      ]
    }
  ]
}
```

## Metadata convention

`metadata` is a free-form `dict[str, Any]` on `Stage`, `Trace`, and
`StageRecord` — the sanctioned escape hatch for product-specific extras that
don't warrant widening the canonical schema. It is **not** validated beyond
being a JSON object; anything product-specific belongs here instead of as a
new top-level field.

The one convention worth following: a `metadata.category` string, used for
grouping (e.g. in the UI, or when slicing a benchmark set by category). It's
not schema-enforced — just a recommendation so different products/importers
converge on the same key instead of each inventing `type`, `group`, `tag`,
etc. Set it wherever grouping makes sense for your data: per-stage (what
kind of work this stage does), per-trace (what kind of query this is), or
per-record (rare — only if a single stage's behavior varies per-call in a
way worth grouping on).

## JSON Schema

A generated JSON Schema for `TraceFile` (for external tooling/languages that
aren't Python) is committed at
[`docs/trace-format.schema.json`](trace-format.schema.json) and regenerated
via `packages/core/scripts/export_schema.py`. It's also served live at
`GET /trace-format/schema` on the API for any product's engineering team to
fetch directly. A test in `packages/core/tests/` fails the build if the
committed file drifts from the live Pydantic models — treat
`trace-format.schema.json` as generated, not hand-edited.

## Reference implementation

[`docs/examples/trace_recorder.py`](examples/trace_recorder.py) is a
stdlib-only, copy-paste-into-your-own-codebase `TraceRecorder` that produces
a schema-1.1-shaped trace file, including the minimal (no tokens/latency)
case. No dependency on this repo — see the file's header comment.

## Design decisions

- **Parallel branches are implicit in `depends_on`, not a separate construct.**
  A dedicated "branch" object would need to stay in sync with the dependency
  graph and would just be redundant data. Two stages sharing an upstream
  dependency (and not depending on each other) *are* the parallel branch;
  the DAG builder (next phase) derives parallel groups by graph analysis
  (nodes at the same topological depth with no path between them), not from
  a flag in the JSON.
- **`query` and `input` are objects, not strings**, because real pipelines
  take structured input and because `StageRecord.input` needs to represent
  resolved template variables (which may come from the original query or
  from upstream stage outputs) — a bare string can't express that.
- **Referential integrity (`depends_on` targets exist, `stage_id` matches a
  known stage) is validated at the schema layer; cycle detection and
  topological sort are not.** Those need graph algorithms, not per-field
  validation, and are explicitly scoped to the next phase (DAG builder).
- **Token counts use `in`/`out`/`thinking` JSON keys** (via Pydantic
  aliases) to match the plan's `tokens{in, out, thinking}` wording exactly,
  even though `in` isn't a valid Python identifier.
