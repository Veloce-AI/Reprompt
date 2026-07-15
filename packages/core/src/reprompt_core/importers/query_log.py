"""Importer for the "query log" trace format.

Source shape (see real samples in ``Sample Queries/*.txt`` — despite the
extension, each file is one JSON document produced by a real multi-stage
legal/tax research-assistant pipeline)::

    {
      "query_id": "<uuid>",
      "query": "<plain string>",
      "timestamp": "...",
      "totals": {"total_cost": ..., "total_input_tokens": ..., ...},
      "stages": [
        {
          "index": 0,
          "stage": "<stage name, may repeat>",
          "stats": {"input_tokken": ..., "output_tokken": ..., "thinking_tokken": ...,
                     "llm_type": "...", "response_time": <ms>, "stage_cost": ...,
                     "isFallback": bool, "retry_attempts": [...], ...},
          "io": {"system_prompt": "...", "user_query": "...", "context": ...,
                 "context_marker": ..., "response": "..." | {...}}
        },
        ...
      ]
    }

Two things make this meaningfully different from our own synthetic fixtures
and from ``reprompt_core.trace``'s shape, and both are handled here rather
than by touching the canonical schema:

1. Stages are a FLAT ORDERED LIST, not an explicit DAG (no ``depends_on``
   anywhere) — dependencies must be *inferred*.
2. The same ``stage`` name can appear multiple times CONSECUTIVELY (verified
   against the real samples: e.g. ``..._relevancy_practice_parallel`` occurs
   3x in a row with near-identical token counts). This is parallel fan-out —
   N concurrent calls of the same logical stage type over different inputs —
   not a retry (retries are marked separately via ``isFallback`` /
   ``retry_attempts``, both empty/false across every sampled record).

--------------------------------------------------------------------------
1. Dependency-inference rule
--------------------------------------------------------------------------

Walk the ``stages`` list in ``index`` order and group consecutive entries
with an identical ``stage`` name into a "step":

    - a step of size 1 is an ordinary sequential stage
    - a step of size N>1 is N parallel siblings (same logical stage,
      concurrent invocations)

Then, uniformly for both cases: every stage in step K depends on ALL
stages in step K-1 (its immediate predecessor step). Step 0's stages have
empty ``depends_on``. Siblings within the same step do NOT depend on each
other — they depend on the same predecessors and can run concurrently.

This one rule produces a straight chain for pure-sequential regions and a
fan-out/fan-in diamond for parallel regions, with no special-casing needed
between the two.

Verified against the real files: in ``0f586e25-...txt``, stage entries at
index 1-3 all share the name
``query_calssification_and_rephrasing_research_using_system_prompt_relevancy_practice_parallel``
(3 near-identical token counts) — one step of 3 siblings. Entry at index 4
(``..._relevancy_practice``, no ``_parallel`` suffix, size-1 step) depends
on all 3 of them; none of the 3 siblings depends on each other.

--------------------------------------------------------------------------
2. Stage-id disambiguation
--------------------------------------------------------------------------

The canonical ``Trace`` model rejects two ``StageRecord``s sharing a
``stage_id`` within one trace, and ``Pipeline`` rejects duplicate ``Stage``
ids — so every one of the flat list's entries (even repeats of the same
name) needs a distinct, deterministic id. Two disambiguation rules apply,
composed in order:

  a. Within a parallel step (size N>1), siblings get a 1-based ordinal
     suffix: ``"<name>#1"``, ``"<name>#2"``, ``"<name>#3"``.
  b. The SAME stage name can also recur as separate, non-adjacent
     single-entry steps — verified in the real data: in
     ``0f586e25-...txt``,
     ``get_relevant_parent_ids_system_prompt_relevantParentId`` appears as
     its own step at index 8 AND again, unrelated steps later, at index 11
     (and similarly ``generate_final_response_cnn_iterative_retrieval_dt``
     at index 10 and 16). Rule (a) alone doesn't disambiguate this — both
     are size-1 steps, so both would naively produce the same candidate id.
     So: candidate ids (post rule-a) are tracked globally per file; the
     first occurrence keeps the clean candidate id, every later collision
     gets an ``__2``, ``__3``, ... occurrence suffix appended.

This keeps the common case (a stage name used once, or used only as a
tidy parallel group) readable, and only adds a suffix in the rarer case
where it's structurally required for uniqueness.

--------------------------------------------------------------------------
3. Pipeline-identity decision
--------------------------------------------------------------------------

Each source file becomes its OWN single-trace Pipeline (one ``TraceFile``
per file), NOT merged into one shared Pipeline across files, even though
all three sample files are executions of "the same" underlying legal/tax
assistant. Reasoning, backed by evidence from the actual samples:

    - File ``7ec0b148-...txt`` has 3 stages. Files ``0f586e25-...txt`` and
      ``7eb538d9-...txt`` have 32 and 35 stages respectively — this source
      pipeline branches at runtime based on query classification (a "quick"
      query takes a 3-stage path; a full research query takes a 30+ stage
      path).
    - Even between the two long traces, the stage SETS differ:
      ``case_law_correction`` and ``reviewer_ita_2025`` appear only in
      ``7eb538d9-...txt``; and shared stage names don't sit at matching
      NAME+POSITION-IN-SEQUENCE across the two files either (e.g.
      ``get_relevant_parent_ids_system_prompt_relevantParentId`` is at
      index 8 in one file and effectively shifted in the other because
      ``inference_git_books_chunks_...`` and it swap relative order).

Given that, deriving stage identity from name+position and merging traces
into one shared Pipeline would either (a) silently misalign unrelated
stages that happen to share a name, or (b) require inventing a union
"superset" DAG that no single query actually executes — neither is
something this importer should paper over. Proper cross-trace pipeline
mining (clustering executions by which conditional branch they took, then
building one DAG per branch/variant) is a real feature, just not this one:
it needs an explicit "which variant is this trace" signal this source
doesn't provide. So: for now, ``convert()`` returns one complete
``TraceFile`` (one pipeline, one trace) per input document, and callers
wanting a multi-trace ``BenchmarkSet`` later should group files by
matching pipeline *shape* (e.g. identical ordered stage-id list) rather
than assuming all query logs share one pipeline.

--------------------------------------------------------------------------
4. Field mapping
--------------------------------------------------------------------------

    query_id                         -> Trace.trace_id
    query (plain str)                -> Trace.query = {"text": query}   [*]
    stages[i]                        -> one Stage + one StageRecord
    stats.llm_type                   -> Stage.model                    (passthrough, no LiteLLM-slug normalization yet)
    stats.input_tokken                -> TokenUsage.input               (source's own "tokken" typo, mapped as-is)
    stats.output_tokken               -> TokenUsage.output
    stats.thinking_tokken             -> TokenUsage.thinking
    stats.response_time              -> StageRecord.latency_ms
    stats.stage_cost                 -> StageRecord.cost
    io.system_prompt                 -> StageRecord.rendered_prompt AND Stage.prompt_template  [**]
    io.user_query / context / context_marker -> folded into StageRecord.input (free-form dict)
    io.response                      -> StageRecord.output              (json-dumped if not already a string — see [***])

[*] The canonical schema types ``Trace.query`` as ``dict[str, Any]``; this
    source's query is a plain string, so it's wrapped rather than the
    canonical schema being loosened to accept a bare string.

[**] Known limitation: this source doesn't separate a reusable "template"
    (with ``{{variable}}`` placeholders) from the as-rendered prompt text —
    ``io.system_prompt`` already IS the full rendered instruction. Since
    ``Stage.prompt_template`` is required and non-empty, imported stages use
    the rendered text itself as a literal, variable-free "template". This
    means an imported ``Stage.prompt_template`` isn't actually reusable
    across different inputs the way a hand-authored one is — it's a
    snapshot of one execution, not a parameterized template. Downstream
    consumers that expect ``{{variable}}`` substitution should not assume
    imported stages have any.

[***] Verified against the real data: ``io.response`` is a JSON string for
    some stages and an already-parsed dict/list for others (both occur in
    the samples). ``StageRecord.output`` is typed ``str``, so non-string
    responses are serialized with ``json.dumps`` to stay lossless.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["convert", "convert_file"]


def _group_into_steps(stages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group index-ordered raw stage entries into steps of consecutive same-name runs.

    A run of consecutive entries sharing ``stage`` collapses into one step
    (see module docstring §1). Non-consecutive repeats of the same name
    become separate steps, each handled independently.
    """
    steps: list[list[dict[str, Any]]] = []
    for entry in stages:
        if steps and steps[-1][-1]["stage"] == entry["stage"]:
            steps[-1].append(entry)
        else:
            steps.append([entry])
    return steps


def _assign_stage_ids(steps: list[list[dict[str, Any]]]) -> list[list[str]]:
    """Assign a globally-unique, deterministic stage id to every raw stage entry.

    See module docstring §2 for the two-rule scheme (sibling ordinal suffix
    within a parallel step, then an occurrence suffix for non-adjacent
    name repeats).
    """
    occurrence_counts: dict[str, int] = {}
    ids_by_step: list[list[str]] = []
    for step in steps:
        if len(step) == 1:
            candidates = [step[0]["stage"]]
        else:
            candidates = [f"{entry['stage']}#{i}" for i, entry in enumerate(step, start=1)]

        ids_for_step: list[str] = []
        for candidate in candidates:
            occurrence_counts[candidate] = occurrence_counts.get(candidate, 0) + 1
            n = occurrence_counts[candidate]
            ids_for_step.append(candidate if n == 1 else f"{candidate}__{n}")
        ids_by_step.append(ids_for_step)
    return ids_by_step


def _stage_output_text(response: Any) -> str:
    """Coerce io.response to str for StageRecord.output (see docstring [***])."""
    if isinstance(response, str):
        return response
    return json.dumps(response, ensure_ascii=False)


def convert(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert one parsed query-log document into a TraceFile-shaped dict.

    Matches the :class:`reprompt_core.importers.ImporterFn` convention: takes
    one raw dict, returns a dict validate-able via
    :func:`reprompt_core.trace.parse_trace_file`. Does not validate itself —
    callers that want validation call ``parse_trace_file(convert(raw))``.
    """
    query_id = raw["query_id"]
    raw_stages = sorted(raw["stages"], key=lambda entry: entry["index"])

    steps = _group_into_steps(raw_stages)
    ids_by_step = _assign_stage_ids(steps)

    stages: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    prev_step_ids: list[str] = []

    for step, step_ids in zip(steps, ids_by_step):
        for entry, stage_id in zip(step, step_ids):
            stats = entry.get("stats") or {}
            io = entry.get("io") or {}

            # Stage.prompt_template / StageRecord.rendered_prompt both
            # require a non-empty string. The real samples always populate
            # system_prompt, but fall back defensively rather than crash on
            # a source record that omits it.
            rendered_prompt = io.get("system_prompt") or "(no system prompt captured for this stage)"

            stages.append(
                {
                    "id": stage_id,
                    "name": entry["stage"],
                    "depends_on": list(prev_step_ids),
                    "model": stats.get("llm_type") or "unknown",
                    "prompt_template": rendered_prompt,
                }
            )

            records.append(
                {
                    "stage_id": stage_id,
                    "input": {
                        "user_query": io.get("user_query"),
                        "context": io.get("context"),
                        "context_marker": io.get("context_marker"),
                    },
                    "rendered_prompt": rendered_prompt,
                    "output": _stage_output_text(io.get("response")),
                    "tokens": {
                        "in": stats.get("input_tokken") or 0,
                        "out": stats.get("output_tokken") or 0,
                        "thinking": stats.get("thinking_tokken"),
                    },
                    "latency_ms": stats.get("response_time") or 0,
                    "cost": stats.get("stage_cost"),
                }
            )

        prev_step_ids = step_ids

    pipeline = {
        "id": f"query-log-{query_id}",
        "name": f"Query log pipeline ({query_id})",
        "stages": stages,
    }

    trace = {
        "trace_id": query_id,
        # Trace.query is dict[str, Any]; this source's query is a plain
        # string, so it's wrapped rather than loosening the canonical type.
        "query": {"text": raw["query"]},
        "records": records,
    }

    return {
        "schema_version": "1.0",
        "pipeline": pipeline,
        "traces": [trace],
    }


def convert_file(path: str | Path) -> dict[str, Any]:
    """Read one query-log file from disk (JSON despite the .txt extension) and convert it."""
    file_path = Path(path)
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    return convert(raw)
