# Reprompt — Dev Tracker

Single source of truth for what's built across the whole project (M0-M5)
and, in detail, what's in progress and what's next on the M3 optimizer
specifically. Update this in the same commit as any change to the phases
below — mark `[x]` as you complete an item, and keep "Current state"
accurate so anyone (human or AI) can pick this up cold without
re-deriving context. Read `START_HERE.md` first if you haven't — it
points here plus the rest of the docs in reading order.

Last updated: 2026-07-16.

## Current state (one paragraph)

Two optimizer strategies exist in `packages/core/src/reprompt_core/optimizer/`:
**simple** (one-shot: mutate the prompt once via one LLM call, then run
the param/format sweep) and **Prism** (multi-round: mutate → cheap-score →
critique the weak ones (now with real judge signal — see the dated Phase 1
quality-fixes section below) → refine → sweep again → full-score → select,
plus optional few-shot example selection). Both are 100% in-house code — no
vendored source, no new dependencies, both call the engine's own
`llm/client.py` so both work with any provider (OpenAI/Anthropic/Gemini/
self-hosted) uniformly. `run_optimizer(..., strategy="simple"|"prism")`
selects between them; `apps/api` reads this from `OPTIMIZER_STRATEGY`
(see `apps/api/.env.example`).

**Done and test-verified**: Phase 0 (cleanup), the DB/credential
groundwork, the original Phase 1 (`mutator.py`'s `critique_and_refine`/
`select_few_shot_examples`), Phase 2 (`loop.py`'s strategy dispatch and
`_optimize_stage_prism`), Phase 3 (`packages/core` tests), **Phase 4 +
4b** (`apps/api` wiring — merged via PR #3/#4 from an external
contributor, `shreychechani`, reviewed and tested before merge — see
"PR #3/#4 review notes" below for what changed vs. this file's original
Phase 4 spec and one real gap found), **Phase 2 — Live DAG/run status view
[DONE — 2026-07-15]**, a dated **"Phase 1 — Prism optimizer quality
fixes [DONE — 2026-07-15]"** section (below) — a separate audit's 6
findings against the already-shipped Prism engine (most notably: the
critique loop was judge-blind, and `max_refine_rounds=1` made the plateau
early-stopping logic dead code), `packages/core` only, `264 passed,
21 skipped` after. **Phase D(a) — Model-card info in wizard [DONE —
2026-07-15]**: new read-only endpoint `GET /model-cards/{model}` returns
family classification and applicable transform rules as JSON; migration
wizard model picker now fetches and displays these rules human-readable
next to each model option (backend 122 passed, frontend 70 passed, clean
typecheck). **Phase A — Live optimizer sub-step signal [DONE —
2026-07-15]**: an `on_phase` callback threaded through the engine so the
live DAG view (Phase 2) shows *which* internal phase a running stage is in
(e.g. "critiquing weakest candidates"), not just that it's running.
**`target_model` tracking fix [DONE — 2026-07-15]**: `Candidate` rows now
record which target model produced them (Alembic migration
`8c4f6d1a3e9b`), closing the gap noted in "PR #3/#4 review notes" below.
**Phase 2 — Project/multi-run ingestion [DONE — 2026-07-16]**: a second
(third, ...) trace file can now be attached to an *existing* pipeline as a
new run (`BenchmarkSet`) instead of always minting a brand-new pipeline —
see the dated section below for the full design (stage reuse/grow/drift
rule, new endpoints, "Import new run" drawer). `apps/api` 137 passed (131 +
6 new), `apps/web` 86 passed (85 + 1 new) + clean typecheck,
`packages/core` untouched.
**Phase B — Live reasoning feed + activity log [DONE — 2026-07-16]**: the
LLM's own critique text (Prism's `critique_and_refine`) and a chronological
activity log across the whole run are now surfaced in the UI instead of
being generated then discarded — see the dated section below for the full
design. `packages/core` 290 passed, 2 skipped (286 + 4 new, additive only),
`apps/api` 147 passed (143 + 4 new), `apps/web` 93 passed (90 + 3 new) +
clean typecheck.
**Model auto-selection for rubric generation [DONE — 2026-07-16]**: rubric
generation no longer requires a caller-supplied model up front — see the
dated section below for the full design (new `llm/model_select.py`, wired
into `apps/api/src/reprompt_api/rubrics.py`, optional model field in the
Rubrics tab). This is rubric-generation-only, not the optimizer's own
judge-model selection (out of scope, untouched). Built in this worktree
against a local baseline of `packages/core` 271 passed/21 skipped,
`apps/api` 147 passed, `apps/web` 93 passed (this worktree's checkout
predates Phase B/Project-ingestion's code landing here, even though their
DEV_TRACKER entries above are already present from the shared doc — those
two phases' actual code is only in their own worktrees pending hand-merge,
not evaluated by this session). After this phase: `packages/core` 286
passed/21 skipped (271 + 15 new), `apps/api` 151 passed (147 + 4 new, one
existing test extended with two new assertions), `apps/web` 97 passed (93
+ 4 new) + clean typecheck.
**Not started**: Phase 6 (final end-to-end manual verification).

**Note for future sessions/developers**: each phase above updates
`DEV_TRACKER.md` itself as part of "done" — same discipline applies to
`docs/TESTING.md` for anything screen/behavior-facing. Don't create a
separate status doc; just flag completion inline in whichever `.md` file
the change actually touches.

## Model auto-selection for rubric generation [DONE — 2026-07-16]

The gap: `packages/core/src/reprompt_core/rubric_generator.py`'s
`generate_rubric` takes a required `generator_model` with no default (by
design — same reasoning as `judge.judge_pairwise`'s `model` param), which
meant `apps/api`'s rubric-generation endpoint and the Rubrics tab's
"Generate all rubrics" button both required a human to type a model name
before generating anything, every time, with no suggested default. Scope:
rubric generation only — the optimizer loop
(`packages/core/src/reprompt_core/optimizer/`) and its own judge-model
selection are untouched, per the task brief.

**`packages/core`**:
- New `packages/core/src/reprompt_core/llm/model_select.py`:
  `select_model(purpose: Literal["rubric_generation", "judge", "mutator"],
  available_models: list[str], *, explicit: str | None = None) -> str`.
  Deliberately simple, per the task's own "not a complex heuristic"
  instruction: a hand-curated capability-tier table
  (`_CAPABILITY_TIERS`/`_GENERAL_ANALYSIS_TIERS`, best tier first) ∩
  `available_models`, cost as the tiebreak *within* a tier (ascending,
  via `reprompt_core.llm.registry.get_model_capabilities` — never a second
  hand-curated cost table), falling back to the cheapest available model
  if nothing curated matches at all. `explicit` (when given) wins
  immediately, before any of that runs, and is never checked against
  `available_models` — "if the caller already chose a model, don't
  second-guess it." Raises `NoAvailableModelError` (a `ValueError`
  subclass) only when `explicit` is absent *and* `available_models` is
  empty. Checked `llm/registry.py` first for existing capability-tier
  metadata to build on (per the task brief) — it deliberately only exposes
  cost/context-window/JSON-mode/tool-use facts pulled from LiteLLM (see its
  own docstring), nothing resembling "how good is this model at analysis,"
  so the tier table here is new, hand-curated data, not derived from
  anything already in the registry.
  All three declared purposes (`rubric_generation`/`judge`/`mutator`) share
  one tier table today — same underlying question (strong reasoning +
  strict instruction-following) — but the lookup is per-purpose so a future
  split is a one-line addition, not a signature change. Only
  `rubric_generation` is actually wired into a caller in this phase; the
  other two purposes exist in the type/table but nothing calls
  `select_model("judge"/"mutator", ...)` yet (that's the optimizer's own,
  explicitly out-of-scope, existing model-selection path).
- New `packages/core/tests/test_model_select.py` (15 new): explicit
  override wins even against an empty/mismatched `available_models`,
  best-available-tier selection, falling through to a lower tier when the
  top tier isn't available, cost tiebreak within a tier (against real
  registry pricing data, same convention as `test_llm_registry.py` — no
  mocking), unknown-price-treated-as-free, no-tier-match cheapest-available
  fallback, empty-available-and-no-explicit raises `NoAvailableModelError`,
  and all three purposes select successfully end-to-end.
  `packages/core`: **286 passed, 21 skipped** (271 + 15 new).

**`apps/api`**:
- `apps/api/src/reprompt_api/migrations.py`: extracted
  `get_available_models(db, workspace) -> list[ModelOption]` out of
  `reprompt_api.settings.list_configured_models` (the exact "curated
  models ∩ this workspace's BYOK providers, plus every no-key-required
  model unconditionally" logic already built for Settings' "Configured
  models" section, per the task brief — reused, not duplicated).
  `settings.py`'s `list_configured_models` now just calls this and no
  longer computes the intersection inline; behavior is byte-for-byte
  identical (same existing `test_settings.py` tests pass unchanged).
- `apps/api/src/reprompt_api/rubrics.py`: `GenerateRubricIn.model` is now
  `str | None = None` (was a required field). In
  `generate_rubric_for_stage`, when `body.model` is falsy, the endpoint
  calls `get_available_models(db, workspace)` (the workspace's real,
  BYOK-filtered model list — never empty even with zero keys configured,
  since local `ollama/...` models need none) then
  `select_model("rubric_generation", available)`; `NoAvailableModelError`
  maps to the same 422-pointing-at-`/settings` shape the missing-key path
  already used, for the (currently unreachable given today's always-has-
  local-models `CURATED_MODELS`, but still handled) case of a truly empty
  list. An explicit `body.model` bypasses all of this exactly as before —
  no behavior change for existing callers that already pass a model.
  `RubricOut` gained `generated_with_model: str | None = None` — populated
  only on the generate/regenerate endpoint's response (from
  `RubricGenerationResult.model`, the model that actually produced the
  accepted content), left `None` on every other response (list/patch/
  approve) since it isn't persisted on the `Rubric` row — this is
  deliberately a transient "what just happened" detail for the UI caption,
  not new schema/migration surface, keeping the change additive-only.
- `apps/api/tests/test_rubrics_generate.py` (4 new + 2 new assertions on
  the existing success-path test): omitting `model` entirely auto-selects
  and reports it back in `generated_with_model`; an explicit JSON `null`
  behaves the same as omitting the key; an explicit model is never
  second-guessed even when a cheaper/higher-tier option is configured;
  auto-select still succeeds (falls back to a no-key local model) with
  zero BYOK keys configured at all, rather than 422ing.
  `apps/api`: **151 passed** (147 + 4 new).

**Frontend**:
- `apps/web/src/lib/api.ts`: `generateRubric(pipelineId, stageId, model?:
  string)` — `model` is now optional; omits the `model` key from the
  request body entirely (rather than sending `""`) so the server's
  auto-select path fires. `RubricOut.generated_with_model?: string | null`
  added, mirroring the backend field.
- `apps/web/src/components/rubric-review-panel.tsx`: the model `Input` at
  the top of the Rubrics tab is now genuinely optional — "Generate all
  rubrics" no longer blocks with an error when it's blank (removed the
  `"Enter a model name first..."` validation), and per-stage "Regenerate"
  is no longer `disabled` on an empty field either (its tooltip now reads
  "No model entered — one will be auto-selected" instead of demanding
  input first). Each stage card's header now shows a small "— generated
  using `<model>`" caption next to the stage id whenever
  `rubric.generated_with_model` is set (i.e. right after that stage was
  generated/regenerated in the current session) — exactly the "shown after
  the fact, not required upfront" shape the task asked for. Empty-state
  copy updated to describe auto-selection as the default path.
- `apps/web/src/components/rubric-review-panel.test.tsx` (4 new): generates
  successfully with a blank model field, asserting `generateRubric` is
  called with `undefined` (not `""`) for the model; the "generated using
  ..." caption renders when `generated_with_model` is set and is absent
  when it isn't; the Regenerate button is enabled with a blank model field.
  `apps/web`: **97 passed** (93 + 4 new) + clean `tsc --noEmit`.

**Where this leaves things**: rubric generation now has a sensible default
model choice end-to-end (core → API → UI), matching the pattern the task
asked for without touching the optimizer's separate judge/mutator model
selection. If a future phase wants `select_model("judge", ...)` or
`select_model("mutator", ...)` actually wired into the optimizer, the
function is already purpose-parameterized for that — no `model_select.py`
changes needed, just a new call site (deliberately not built here, out of
scope per the task brief).

## Phase 2 — Project/multi-run ingestion [DONE — 2026-07-16]

The gap: every trace upload previously created a brand-new `Pipeline` +
brand-new `Stage` rows + one `BenchmarkSet`, unconditionally
(`persist_trace_file`) — no way to attach a second run to an existing
pipeline. `BenchmarkSet.pipeline_id` was already a plain FK (the schema
already supported many `BenchmarkSet`s per `Pipeline`), just nothing used
it. Built in a parallel worktree alongside unrelated Phase 3 work on
`pipelines.py`/`pipeline-workspace.tsx` — kept changes additive/narrow in
both shared files for an easier hand-merge (only added new endpoints/a new
route param and a new header button + drawer; no existing function bodies
restructured).

**Backend**:
- `apps/api/src/reprompt_api/ingest.py`: `persist_trace_file(db,
  trace_file, *, pipeline: models.Pipeline | None = None) ->
  models.Pipeline`. `pipeline=None` (default) behaves exactly as before.
  When `pipeline` is given: no new `Pipeline`/`Stage` set is created by
  default — for each stage in the incoming file, looked up by
  `(pipeline_id, source_id)`: if an existing `Stage` row matches
  (`model`/`prompt_template`/`system_prompt`/`params` all equal), it's
  reused as-is; if not found, a new `Stage` row is created (a pipeline can
  grow new stages across runs); if found but any of those four fields
  differ, every such conflict is collected and raised as one new
  `StageDriftError` (defined locally in `ingest.py`) naming every
  conflicting stage — checked across *all* incoming stages before any
  mutation happens, so a rejected import never leaves the session
  half-modified (no partial `Stage`/`BenchmarkSet` rows to roll back).
  Chose reject-with-422 over accept-and-flag or versioning per the task's
  own settled decision: an in-place stage change would silently invalidate
  an already-approved `Rubric` with no way to detect it, and `Rubric`/
  `Candidate` both already assume a stable `stage_id` — keeping `Stage`
  rows immutable once created is the smaller, more honest contract than
  either alternative. A `BenchmarkSet` is always created for the run;
  named `f"{pipeline_name} benchmark"` for the original import (unchanged)
  or `f"Run {n}"` (n = existing `BenchmarkSet` count + 1) for an attached
  run, so repeat runs don't all share one indistinguishable name.
  Dependency-edge wiring guards against re-appending an edge a reused
  `Stage` row already has (the `stage_dependencies` association table's
  composite PK would otherwise raise on a duplicate insert).
- `apps/api/src/reprompt_api/pipelines.py`: extracted
  `_parse_upload_to_trace_file()` out of the existing `POST /import`
  handler (validate-UTF8 → validate-JSON → `parse_trace_file`) so the new
  endpoint below shares the exact same validation path rather than
  duplicating it. New `POST /pipelines/{pipeline_id}/import` — 404s if the
  pipeline doesn't exist, otherwise identical upload/validation flow,
  passes the loaded `Pipeline` to `persist_trace_file`, and catches the new
  `StageDriftError` → 422 (alongside the pre-existing `CycleError` → 422
  pattern already used by `POST /import`). New `GET
  /pipelines/{pipeline_id}/runs` → `RunOut[]` (`{id, name, created_at,
  trace_count}`), one row per `BenchmarkSet` for that pipeline, oldest
  first, `trace_count` via a `LEFT JOIN` + `COUNT`/`GROUP BY` on `Trace`
  (not N+1 queries per `BenchmarkSet`); 404s the same way every other
  `/{pipeline_id}/...` route here does for an unknown pipeline.
- Tests: new `apps/api/tests/test_pipelines_runs.py` (6 new) — reusing a
  matching stage set (`Stage` row count unchanged, exactly 2
  `BenchmarkSet`s), a genuinely new stage added (5th `Stage` row, wired
  to its `depends_on`), a drifted stage rejected with 422 naming it and
  nothing persisted (`BenchmarkSet`/`Stage` counts unchanged, the
  original `prompt_template` intact), 404 for an unknown pipeline on
  import, `GET .../runs`'s exact shape/`trace_count` across two runs with
  different trace counts, 404 for an unknown pipeline on `/runs`.
  `apps/api`: **137 passed** (131 baseline + 6 new).

**Frontend**:
- `apps/web/src/lib/api.ts`: `RunOut` interface,
  `importIntoExistingPipeline(pipelineId, file)` (same
  `FormData`-with-one-file shape as the existing `importPipeline`, just
  posted to `/pipelines/{id}/import`), `getRuns(pipelineId)`.
- `apps/web/src/routes/pipeline-workspace.tsx`: new "Import new run"
  button in the header, next to the pipeline name (not a separate route —
  the task brief called for an action in the header area, and this
  workspace is already the single unified screen per Phase 1's "Unified
  pipeline workspace"). Opens an `ImportRunDrawer` built on the same
  `DrawerRoot`/`DrawerContent` primitives the existing stage-rubric drawer
  already uses, reusing `components/dropzone.tsx` wholesale for the actual
  upload UI (the same component `routes/pipelines-import.tsx`'s wizard
  uses) rather than rebuilding drag-and-drop. On a successful import,
  invalidates the `["pipelines"]`, `["pipeline-dag", pipelineId]`,
  `["rubrics", pipelineId]`, and `["runs", pipelineId]` query keys so the
  Canvas/Rubrics tabs and stage/trace counts reflect the new run without a
  manual refresh. A `StageDriftError`'s 422 detail (naming the conflicting
  stage) surfaces verbatim in the drawer's error panel, with a "Try a
  different file" button that resets the mutation without closing the
  drawer.
- Tests: `pipeline-workspace.test.tsx` gained 1 new test (`imports a new
  run into the pipeline via the 'Import new run' action`) — clicks the
  button, drives the drawer's file input directly (queried off
  `document.body`, not the RTL render root, since the drawer portals
  outside it — see the test's own comment), asserts
  `importIntoExistingPipeline` was called with the right pipeline id/File
  and the drawer shows the success message. `apps/web`: **86 passed** (85
  baseline + 1 new), clean `tsc --noEmit`.

**What a user actually sees**: on any pipeline's workspace, "Import new
run" next to the pipeline name opens a drop-zone drawer; dropping a
compatible trace file (same stage definitions, or new stages appended)
succeeds silently into the pipeline's existing DAG — no duplicate pipeline
appears in the Pipelines-home list. Dropping a file where an existing
stage's model/prompt/params changed is rejected with a clear inline error
naming the conflicting stage, instead of silently corrupting an
already-reviewed rubric.

**Explicitly out of scope, not built this phase**: no UI list of past runs
(the `GET .../runs` endpoint exists and is tested, but nothing in the
workspace renders it yet — `docs/TESTING.md`'s new §3.1c walkthrough
verifies it via curl/devtools instead); "Pipeline"→"Project" stays a
UI-label naming question for a future pass, not touched here per the
task's own instruction to leave `pipeline_id`/route params/backend names
alone. `packages/core` and the optimizer loop untouched (confirmed via
`git status` before commit).

## Phase B — Live reasoning feed + activity log [DONE — 2026-07-16]

The gap: two real LLM outputs were already being paid for and then thrown
away. `_optimize_stage_prism`'s `critique_and_refine()` (`mutator.py`)
generates a `critique: str` explaining why a candidate underperformed and
what changed — parsed out of the model's JSON response, then discarded;
only `refined_prompt` survived into `PromptMutationResult`. Separately,
Phase A's `on_phase` callback only ever carried a bare phase name (e.g.
`"refining"`), never the reasoning text produced *during* that phase. This
phase plumbs both through to the UI — purely additive, no optimizer
decision logic (mutation/critique/refine/sweep/select) touched.

**`packages/core`**:
- `optimizer/mutator.py`: `PromptMutationResult` gained `critique: str |
  None = None`. `critique_and_refine` now sets it from the parsed
  response's `critique` field (empty/whitespace-only normalized to `None`,
  same convention as every other optional text field in this module).
  `generate_prompt_mutations` leaves it `None` (no code change needed — it
  never had a critique to report; a dedicated test
  (`test_generate_prompt_mutations_critique_is_always_none`) pins this).
- `optimizer/loop.py`: `StagePhaseEvent` gained `detail: str | None = None`
  (trailing field, existing `StagePhaseEvent(stage_id=..., phase=...)`
  call sites everywhere are unaffected). New `_judge_reasoning_summary()`
  helper builds a short summary from a `JudgeResult` for the case the
  critique text itself came back empty. In `_optimize_stage_prism`, the
  `"refining"` phase event is now fired *after* a successful
  `critique_and_refine()` call (previously fired just before it, since
  that's the only point in the round where the real critique text actually
  exists) — `detail=refinement.critique or _judge_reasoning_summary(judge_result)`.
  Still fires at most once per round (same `refining_phase_fired` guard as
  before); if every candidate's refinement call in a round fails, that
  round simply has no `"refining"` event instead of one with `detail=None`
  — nothing to plumb in that case anyway, and no existing test depends on
  the old always-fires-even-on-failure timing. `"critiquing"` and every
  other phase/strategy deliberately keep `detail=None` — nothing real is
  available to attach at those transition points without moving decision
  logic around, which was explicitly out of scope.
- Tests (4 new): `test_optimizer_mutator.py` —
  `test_critique_and_refine_critique_is_none_when_model_returns_empty_critique_text`,
  `test_generate_prompt_mutations_critique_is_always_none`, plus the two
  existing `critique_and_refine` tests extended to assert `.critique`.
  `test_optimizer_loop.py` — `test_prism_refining_phase_event_carries_the_critique_text`
  (asserts the `"refining"` event's `.detail` equals the critique text, and
  that every other phase in the same run keeps `detail=None`),
  `test_stage_phase_event_detail_defaults_to_none` (backward-compat pin).
  `packages/core`: **290 passed, 2 skipped** (286 baseline + 4 new, same 2
  environment-only skips as baseline — confirmed additive).

**`apps/api`**:
- `models.py`: `Migration.activity_log: list[dict] | None` — new nullable
  `JSON` column. Alembic migration
  `apps/api/alembic/versions/d3f7a2c1e5b6_add_migration_activity_log.py`
  (`450ae8aefaa7` → `d3f7a2c1e5b6`, single head confirmed via `alembic
  heads` both before and after — see the root-cause section above for why
  that check matters every time). Verified a full upgrade chain applies
  cleanly on a fresh SQLite DB.
- `optimizer_runner.py`: the existing `on_phase` closure (which already
  writes `Migration.progress_substep`) now also appends
  `{"stage_id", "phase", "detail", "timestamp"}` to `Migration.activity_log`
  on every call, capped at the most recent `MAX_ACTIVITY_LOG_ENTRIES = 100`
  entries (oldest dropped from the front). Reassigns the whole list rather
  than mutating in place — in-place mutation of a JSON-mapped column is a
  well-known SQLAlchemy footgun that silently no-ops on commit (nothing to
  detect the change against).
- `migrations.py`: `MigrationOut.activity_log: list[dict] | None` exposed
  in `GET .../status`, same polling pattern as `progress_substep`/
  `stage_states` — no computation, just what `optimizer_runner.py` last
  wrote.
- Tests (4 new): `test_migrations.py` —
  `test_status_activity_log_defaults_to_none_before_a_run_starts`,
  `test_status_exposes_activity_log_entries`. New
  `test_optimizer_runner.py` (no such file existed before this phase) —
  monkeypatches `reprompt_core.optimizer.loop.run_optimizer` (imported into
  `optimizer_runner`'s own namespace) with a fake that fires a
  caller-controlled `StagePhaseEvent` sequence through the real `on_phase`
  closure, so these tests exercise the actual DB-writing logic without a
  real LLM call:
  `test_on_phase_appends_events_to_activity_log`,
  `test_activity_log_is_capped_at_max_entries_keeping_the_most_recent`
  (150 events fired, asserts exactly the most recent 100 survive, oldest
  20 dropped from the front). `apps/api`: **147 passed** (143 baseline + 4
  new).

**`apps/web`**:
- `lib/api.ts`: `ActivityLogEntry` interface (mirrors what
  `optimizer_runner.py` appends) and `MigrationOut.activity_log:
  ActivityLogEntry[] | null`.
- `components/stage-node.tsx`: `SUBSTEP_LABEL` (the `StagePhase` →
  human-readable label map, previously module-private) now exported for
  reuse by the activity log list — same "never render the raw enum value"
  rule applies there too.
- `components/migration-success-screen.tsx`:
  - New `stageId` click handling on the live `<PipelineCanvas>`: clicking a
    node only opens the new reasoning drawer when
    `status.stage_states[stageId] === "running"` — a done/idle/failed node
    click is a no-op here (unlike the Canvas tab's rubric drawer, which
    opens for any node).
  - New `StageReasoningDrawer` — reuses the existing `DrawerRoot`/
    `DrawerContent`/`DrawerHeader`/`DrawerBody` primitives
    (`components/ui/drawer.tsx`) `pipeline-workspace.tsx`'s
    `StageRubricDrawer` already established for stage-scoped side panels,
    rather than a new panel component. Shows the latest activity log entry
    for the clicked stage (its human-readable phase label + real detail
    text if any) plus a collapsed "earlier this run" list of that stage's
    prior entries.
  - New `ActivityLogList` — the whole run's activity log below the canvas,
    one line per entry ("Stage {name}: {detail or phase label}"), newest
    at the bottom, auto-scrolling via a `scrollTop = scrollHeight` effect
    keyed on the entries array (same polling cadence as everything else on
    this screen — no new poll interval introduced). Stage names resolved
    via a `useQuery` on the same `["pipeline-dag", pid]` key
    `<PipelineCanvas>` itself already uses, so it reads from the shared
    React Query cache rather than issuing a second fetch.
- Tests: new `components/migration-success-screen.test.tsx` (no test file
  existed for this component before this phase) — 3 tests: the activity
  log renders stage names + detail/phase-label lines in the right order,
  clicking a running node opens the drawer with the real critique text,
  clicking a non-running node is a no-op (drawer never opens). One real
  gotcha hit and worth recording: Testing Library's default `getByText`
  only matches an element's *direct* text-node children (not full
  recursive `textContent`), so it can never match a string split across
  `<span>{name}</span>: {detail}` markup as one query — waits in these
  tests use the real DOM `.textContent` (via `waitFor` + `.toContain`)
  instead of `findByText` on the combined string. Two pre-existing test
  fixtures (`new-migration-wizard.test.tsx`, `pipeline-workspace.test.tsx`)
  needed `activity_log: null` added to satisfy `MigrationOut`'s now-required
  field, same pattern as Phase A's `progress_substep` fixture fix.
  `apps/web`: **93 passed** (90 baseline + 3 new), clean `tsc --noEmit`.

**What a user actually sees**: on the live migration run screen, clicking
the currently-pulsing (running) stage node opens a drawer showing the
optimizer's actual critique of its weakest candidate this round — not just
"refining prompt" but *why* the candidate scored the way it did and what's
being changed. Below the DAG, a scrolling activity log shows every phase
transition across every stage in the run so far, in plain English,
updating live as the run progresses.

**Explicitly out of scope, not built this phase**: `"critiquing"`/every
other phase besides `"refining"` still fire with `detail=None` — no
reasoning text exists at those transition points without restructuring
where in the round loop they fire, which risked behavior drift for little
product value (the critique text is the one piece of real, previously-
discarded reasoning this phase was scoped to surface). No SSE/websocket —
this still rides the existing ~2s polling `GET .../status` pattern, per
the codebase's established "poll a status endpoint" convention.

## Root-cause investigation — "the flow is broken, nothing is working" [FIXED — 2026-07-15]

Product owner reported the app broken after several rounds of merged work
(Prism fixes, live DAG view, model-card info, live sub-step signal,
`target_model` fix). Actually started both servers and drove the real
golden path (import → DAG → rubrics → migration wizard → start → live
status, via curl against the API directly — no browser-driving tool
available in this environment) instead of assuming it was a UX opinion.
Found one genuine, concrete regression:

**Root cause: two divergent Alembic heads, silently broken migrations.**
`8c4f6d1a3e9b` (`add_target_model_to_candidates`, from this file's own
"`target_model` tracking fix") and `b8e1c4a7f209` (`add_migration_progress_substep`,
from "Phase A — Live optimizer sub-step signal") were both built in
parallel worktrees against the same parent revision (`f3a7b1c9d2e4`) and
never rebased onto each other before merging — `down_revision =
'f3a7b1c9d2e4'` on both. Confirmed via `uv run alembic heads`: two heads,
not one. `uv run alembic upgrade head` failed outright with "Multiple head
revisions are present" — meaning nobody could migrate a fresh dev DB past
`f3a7b1c9d2e4` since whichever of those two phases merged second. This
repo's own dev DB (`apps/api/test.db`) was confirmed stuck exactly there
(`select version_num from alembic_version` → `f3a7b1c9d2e4`) — neither
`Candidate.target_model` nor `Migration.progress_substep` existed as real
columns despite both being "done" per this file, so any code path touching
either (which is most of the live-status/candidate-tracking work from the
last two rounds) would throw a real `sqlite3.OperationalError: no such
column` at runtime. This is concretely "nothing is working," not a vague
complaint.

**Fix**: `uv run alembic merge -m "merge target_model and progress_substep
heads" 8c4f6d1a3e9b b8e1c4a7f209` — the standard Alembic resolution, a new
no-op revision (`450ae8aefaa7`) whose `down_revision` is the tuple of both
former heads. Verified against both a fresh SQLite DB (full chain applies
cleanly start to finish, single resulting head) and this repo's actual dev
DB (`apps/api/test.db`, upgraded from the stuck `f3a7b1c9d2e4` all the way
to `450ae8aefaa7` with no errors). **Lesson for next time two people build
migrations in parallel worktrees**: `alembic heads` should be run (not just
`alembic upgrade head`, which silently "works" for whoever merged first and
only fails for the second) as part of every merge's own verification step,
same discipline as re-running the test suites — a green test suite in each
worktree individually said nothing about this, since neither worktree's
own tests exercised a migration chain the other worktree also touched.

**Also verified, not bugs**: `apps/api/src/reprompt_api/migrations.py`'s
`CURATED_MODELS` list looked like it had a `"ollama\qwen2.5:14b"` backslash
typo when read via a grep tool — checked against the actual file content
and a live `GET /pipelines/{id}/models` response, both confirm it's really
`"ollama/qwen2.5:14b"` (forward slash, correct); the backslash was an
artifact of how one tool's output got escaped in transcript, not real file
content. Full three-suite baseline reconfirmed clean after the alembic fix
alone, before any other change: `packages/core` 286 passed/2 skipped,
`apps/api` 124 passed, `apps/web` 74 passed + clean `tsc --noEmit`.

**Golden path, actually driven end-to-end (curl, no BYOK key available in
this environment so the optimizer's real LLM calls couldn't be exercised
for real — verified instead that the no-key path degrades correctly
rather than crashing, see below)**: imported a converted `Sample Queries/`
trace file → `GET /pipelines/{id}/dag` → seeded rubrics → approved all →
`GET /pipelines/{id}/models` (curated model list) → created a migration
(`POST .../migrations`) → started it (`POST .../migrations/{id}/start`) →
polled `GET .../status`, confirmed `stage_states` and `progress_substep`
both populate correctly. Without a workspace BYOK key, each stage's
optimizer call raises `ProviderKeyNotConfigured` — caught per-stage by
`optimizer_runner.py` (logged, stage marked failed, migration still
reaches a terminal `"completed"` state rather than crashing the whole
request) — this is the correct, already-built graceful-degradation
behavior, not a bug. **One pre-existing gap, not a regression**: dropping
a raw `Sample Queries/*.txt` file straight into the import wizard fails
validation — `reprompt_api`'s `/pipelines/import` expects the universal
trace schema already, and nothing wires
`reprompt_core.importers.query_log.convert_file` into an API endpoint;
`docs/TESTING.md` already documented this as a manual offline-conversion
step before this session, so it's a known, standing gap worth closing
later, not something the recent merges broke.

## Settings page — real model-configuration content [DONE — 2026-07-15]

Per `START_HERE.md`/this file's own standing note, Settings was BYOK-key
CRUD + workspace rename only, flagged as needing real content from the
first planning round and deferred every round since. Built the missing
piece, reusing existing infrastructure wholesale — no new model registry,
no new provider-onboarding flow:

- **`apps/api/src/reprompt_api/model_cards.py`**: extracted
  `build_family_card(model) -> FamilyCardOut` out of the `GET
  /model-cards/{model}` route handler (which now just calls it) so another
  router can reuse the exact same family/rule resolution without an
  internal HTTP round-trip.
- **`apps/api/src/reprompt_api/settings.py`**: new `GET /settings/models`
  (auth-required, workspace-scoped) → `ConfiguredModelOut` — every model
  from `migrations.py`'s existing `CURATED_MODELS` list that either needs
  no key (local/self-hosted, e.g. `ollama/...`) or whose provider has a
  BYOK key configured for this workspace, each with its `model_card` info
  attached via `build_family_card`. Reuses `migrations.py`'s
  `CURATED_MODELS`/`ModelOption`/`_to_option` directly (imported, not
  duplicated) — confirmed no import-cycle risk (`migrations.py` doesn't
  import `settings.py`).
- **`apps/web`**: `lib/api.ts` gained `ConfiguredModel` +
  `listConfiguredModels()`. `routes/settings.tsx` gained a new
  `ConfiguredModelsCard`, rendered below the existing workspace-name and
  API-keys cards — models grouped by provider, each showing input/output
  cost per 1M tokens (or "Free (local)"), resolved prompt family, and a
  pill per model-card transform rule that will actually apply to it (only
  `will_apply: true` rules shown, never the full inapplicable set).
- **What a user actually sees**: Settings now has a third section,
  "Configured models" — before adding any BYOK key it shows just the
  no-key-required local models; adding a key for a provider immediately
  surfaces that provider's curated models with real cost and prompt-style
  info, the same data previously only visible by opening a specific
  pipeline's migration wizard.
- **Tests**: `apps/api/tests/test_settings.py` — 5 new (`test_list_configured_models_*`):
  no-key-models-only before any BYOK key, provider's models appear after a
  key is added, model-card info present, workspace isolation (one user's
  key never leaks another's model list), unauthenticated rejection folded
  into the existing all-endpoints test. `apps/web/src/routes/settings.test.tsx`
  — 3 new: grouped-by-provider rendering with model-card info, only
  no-key models shown before any key, empty state. Final: `apps/api`
  **128 passed**, `apps/web` **77 passed** + clean `tsc --noEmit`,
  `packages/core` untouched (**286 passed, 2 skipped**, unaffected).

Full **Refract → Reprompt** rename completed 2026-07-14: both Python
packages (`refract_core`→`reprompt_core`, `refract_api`→`reprompt_api`,
every import), both `pyproject.toml` names, all docs (including renaming
`docs/refract-master-build-prompt.md`/`docs/refract-parity-engine-plan.md`
to their `reprompt-*` names), all env var prefixes
(`REFRACT_*`→`REPROMPT_*` — update any local `.env` files by hand, they're
gitignored so this rename doesn't touch them automatically), UI text,
`infra/` Postgres config. All 3 test suites re-verified green after
(`packages/core` 273/2 skipped, `apps/api` 104, `apps/web` 65 + clean
typecheck). **Caution for next time**: a blanket `sed 's/refract/reprompt/g'`
run without excluding `.venv`/`node_modules` corrupted third-party library
source (`sympy`, `pygments`) inside the venvs, and separately mangled the
physics term "refracted"→"reprompted" in two docs (the logo's visual
metaphor is still literally light refracting through a prism — that word
must stay "refract*" regardless of the product's name). Both fixed (venvs
deleted + reinstalled from lockfile; docs hand-corrected). Always exclude
`.venv`/`node_modules`/`.git` explicitly and grep for the *product name*
specifically, not indiscriminate substring matches, before a repo-wide
rename sed.

A real bug was found and fixed while writing Phase 3's plateau test (see
Phase 2's own note below): the early-stopping-on-plateau check was
originally keyed by candidate *text*, which never matches across rounds
since refined candidates always have new text — fixed via a
parent-score "baseline" tracked at refinement time instead. Worth reading
if you're touching `_optimize_stage_prism` again — the same mistake is
easy to reintroduce if the lineage-tracking reasoning isn't kept in mind.

**Logo — deferred, not forgotten.** Kept the beam/lens mark (`Logo` in
`apps/web/src/components/logo.tsx`, `docs/logo.svg`) for now — it reads
fine in light mode but hasn't been checked/tuned for dark mode yet. A
more distinctive monogram direction was explored and parked (not lost —
worth revisiting, just not now).

## Phase 1 — Prism optimizer quality fixes [DONE — 2026-07-15]

A separate audit pass (not one of the phases 0-6 above — a later, independent
review of the already-shipped Prism engine) found six real quality issues in
`packages/core/src/reprompt_core/optimizer/` and the modules it leans on
(`judge.py`, `scoring.py`, `embedding.py`). All six addressed in this pass,
`packages/core` only (no `apps/api`/`apps/web` changes — those were
explicitly out of scope, being worked in parallel on a different worktree).
Ran against this worktree's own clean baseline first (`254 passed, 21
skipped` — the 21 skips are environment-only: no `Sample Queries` fixtures,
no `NVIDIA_NIM_API_KEY`, no local Ollama server in this checkout; this
worktree's baseline is *not* the `273 passed, 2 skipped` figure quoted
elsewhere in this file for a fuller dev environment — same code, different
local environment, worth knowing if you hit this again). Final:
**264 passed, 21 skipped** (254 + the 10 new tests below, same 21
environment-only skips, unrelated to this work).

1. **Critique loop was judge-blind.** `_optimize_stage_prism`'s ranking
   pass (`_cheap_score_candidate`) deliberately never runs the judge (by
   design — it's the *cheap* pass), but `critique_and_refine` was then
   always told "AI judge was not run for this candidate" — even though the
   judge is `DEFAULT_WEIGHTS.judge=0.45`, the *largest* weight in the real
   composite score (`scoring.py`), bigger than deterministic (0.25) and
   embedding (0.30) combined with neither. The critique loop was optimizing
   against a signal that structurally excluded the dominant one. Fixed by
   adding `judge.judge_single_pass()` — one real judge call, no
   position-swap (the swap's bias-cancelling value is reserved for the
   *persisted* score from the final full sweep's `judge_pairwise` call) —
   run on each of a round's weakest 1-2 candidates right before critiquing
   them, with its per-criterion `reasoning` text threaded into
   `critique_and_refine` (new optional `judge_result: JudgeResult | None`
   param) and rendered by `_format_score_feedback` in `mutator.py`. Chose
   "pass `JudgeResult` alongside `CompositeScore`" over "extend
   `CompositeScore` with a reasoning field" — keeps `CompositeScore`'s shape
   (used broadly, including by `apps/api`'s `Candidate.scores`) untouched.
   Follows the same harness discipline as every other call site: retry-once
   on malformed JSON (new, since `judge_pairwise`/`_run_judge_call` didn't
   already have a retry policy — added `JudgeResponseError.response`, the
   raw failed `LLMResponse`, so a caller can still recover its cost for
   `budget.record_spend()` even on a failed attempt), a typed exception,
   and a `try/except` in `loop.py` that degrades to "critique without judge
   reasoning" rather than aborting the stage. Cost is bounded: at most one
   extra judge call per weakest candidate per round (≤2 per round) — ranking
   itself is unchanged and still judge-free.
   Files: `packages/core/src/reprompt_core/judge.py` (new
   `judge_single_pass()`, `JudgeResponseError.response`),
   `packages/core/src/reprompt_core/optimizer/mutator.py`
   (`_format_score_feedback`/`_build_critique_messages`/`critique_and_refine`
   all gained an optional `judge_result` parameter),
   `packages/core/src/reprompt_core/optimizer/loop.py`
   (`_optimize_stage_prism`'s critique/refine block, ~line 686-731).

2. **`max_refine_rounds=1` made plateau early-stopping dead code.** The
   plateau check (`candidate_baseline`/`PLATEAU_EPSILON`, see this file's
   own "Loop & harness engineering discipline" section above) needs a
   *second* round to compare a refined candidate's new score against — at
   the old default of 1, `_optimize_stage_prism`'s round loop
   (`for _round_num in range(max_refine_rounds)`) could only ever execute
   once, so the comparison could never happen. Fixed by raising
   `DEFAULT_MAX_REFINE_ROUNDS` from 1 to 3
   (`packages/core/src/reprompt_core/optimizer/loop.py`). The existing
   plateau check plus `budget.is_exhausted` already bound the cost of
   unhelpful further rounds, so no new cost-control mechanism was needed.
   `test_prism_plateau_early_stop` (pre-existing) already passed
   `max_refine_rounds=3` explicitly, so it wasn't relying on the old
   default and needed no changes — confirmed it still passes. Added two new
   tests: `test_prism_default_max_refine_rounds_is_three` (the constant
   itself) and `test_prism_default_rounds_engages_all_three_rounds_when_improving`
   (an end-to-end demonstration, using the default with no
   `max_refine_rounds` override, that all 3 rounds actually execute when
   each round's cheap_score clears `PLATEAU_EPSILON` over its parent's
   baseline — 6 critique calls total, 2 per round × 3 rounds).

3. **"Weakest-2 gets refined" heuristic — confirmed correct, no code
   change.** The heuristic itself (`ranked[:2]`) was never the bug; Fix 1
   above (the judge-blind ranking feeding *into* it) was. No action needed
   here beyond this note.

4. **Judge disagreement/low_confidence computed then discarded.**
   `judge.py`'s position-swap design (`judge_pairwise`) already computed
   `JudgeResult.disagreement`/`low_confidence` to flag an unreliable
   judgment, but `run_sweep_for_stage` only ever read
   `judge_result.overall_score` — the disagreement signal never survived
   onto anything persisted. Fixed by adding two keys,
   `"judge_disagreement"` and `"judge_low_confidence"`, to the `scores`
   dict `run_sweep_for_stage` builds for each `StageAttempt` (only set —
   non-`None` — when a real judge call actually ran and succeeded). Pure
   plumbing, no new LLM calls. `StageAttempt.scores`'s type widened from
   `dict[str, float | None]` to `dict[str, float | bool | None]` to fit the
   new boolean value — a `packages/core`-only type change; `apps/api`
   persists this dict as an opaque JSON blob, so this doesn't require any
   change on that side to keep working at runtime.
   File: `packages/core/src/reprompt_core/optimizer/loop.py`,
   `run_sweep_for_stage` (~line 366-419) and the `StageAttempt` model
   definition (~line 178-196).

5. **`num_prompt_variants=3` — confirmed as the wrong lever, left
   unchanged.** Raising it would scale the expensive full-sweep stage
   linearly; Fix 2 (more refine rounds) was the correct lever for more
   exploration. No code change.

6. **No near-duplicate filtering on mutations.** Dedup was exact-string-
   match only (`if variant not in prompt_candidates`) — two near-identical
   mutation/refinement variants (differing by a sentence) would each still
   consume a full, real sweep slot. Fixed by adding `_is_near_duplicate()`
   in `loop.py`, using `embedding.embedding_similarity` (already local/free,
   no API key — bge-m3) to compare a candidate variant against every
   already-kept candidate before it's added; dropped if similarity exceeds
   the new named constant `NEAR_DUPLICATE_SIMILARITY_THRESHOLD = 0.97`
   (deliberately high — must only catch genuinely near-identical rewrites,
   not merely similar-topic variants, since real diversity across variants
   is the mutator's whole point). Applied at all three places a new
   variant/refinement gets added to a candidate set: `_optimize_stage_simple`'s
   mutation loop, `_optimize_stage_prism`'s round-1 mutation loop, and
   `_optimize_stage_prism`'s refined-variant loop.

**Tests added** (10 total, all passing; see file:line above for where each
fix landed):
- `packages/core/tests/test_judge.py`: 3 new tests for `judge_single_pass`
  (one call not two, retry-once-on-malformed-JSON, raises with recoverable
  cost after retry also fails).
- `packages/core/tests/test_optimizer_mutator.py`: 2 new tests for
  `critique_and_refine`'s `judge_result` parameter (reasoning text reaches
  the prompt when supplied; falls back to the prior "judge was not run"
  framing when not).
- `packages/core/tests/test_optimizer_loop.py`: 5 new tests — real judge
  call in the critique-ranking pass with reasoning reaching the prompt
  (Fix 1), the new `DEFAULT_MAX_REFINE_ROUNDS=3` constant and an end-to-end
  3-round demonstration (Fix 2), `judge_disagreement`/`judge_low_confidence`
  appearing in `StageAttempt.scores` (Fix 4), near-duplicate mutation
  filtering (Fix 6).

**One spec/reality drift worth recording**: the audit that produced this
Phase's spec suggested `run_sweep_for_stage`'s judge call site (~line 373)
was "around line 377" and `_format_score_feedback` "around line 218-243" —
both were off by a handful of lines from actual file state at the time this
work started (harmless; line numbers drift as a file is edited, not a sign
of a deeper mismatch — the described *behavior* at each site matched
exactly). No other assumption in the spec (`CompositeScore`'s shape,
`StageAttempt`'s definition, the plateau test's existing
`max_refine_rounds=3`, etc.) needed correcting.

## Phase 2 — Live DAG/run status view [DONE — 2026-07-15]

Built on top of Phase 4/4b's polling `GET .../status` endpoint — no new
concurrency, no new DB columns, `packages/core` untouched throughout (a
separate agent was working there in a parallel worktree at the same time).

**Backend** — `apps/api/src/reprompt_api/migrations.py`:
- `MigrationOut.stage_states: dict[str, str]` (new field, `_compute_stage_states`
  helper just above `_to_out`) — a derived `{stage_id (as string) ->
  "idle"|"running"|"done"|"failed"}` map, computed fresh on every read from
  the same `status`/`progress_stage_name` fields `optimizer_runner.py` already
  writes sequentially. Stage order reused as-is from `optimizer_runner._run`'s
  own query (`Stage` filtered by `pipeline_id`, ordered by `id`) — no second
  ordering invented. Rule: stages before the current `progress_stage_name` =
  `"done"`, the matching stage = `"running"` (`"failed"` if
  `status == "failed"`, `"done"` if `status == "stopped_early"` since that
  stage had already gotten at least one attempt before the budget hard-stop),
  stages after = `"idle"`; `status == "completed"` short-circuits to all
  `"done"`; before anything starts (`progress_stage_name` still `None`), all
  `"idle"`. `_to_out` now takes `db` (needs it to query stage order) — every
  call site updated.
- Keys are the stage's DB id as a string (`str(stage.id)`), matching the DAG
  canvas's React Flow node ids (`String(stageId)` in the frontend) so the
  frontend can index `stage_states` directly by node id with no translation.
- Tests: `apps/api/tests/test_migrations.py` — 5 new cases (`test_stage_states_*`):
  all-idle before a run starts, mid-run done/running/idle split, terminal
  `failed` (current stage marked `"failed"`), terminal `stopped_early`
  (current stage marked `"done"`), terminal `completed` (all `"done"`).

**Frontend**:
- `apps/web/src/components/pipeline-canvas.tsx` (new) — extracted the React
  Flow DAG-building logic (nodes/edges from `getPipelineDag`) out of
  `pipeline-detail.tsx` into a shared `PipelineCanvas` component taking an
  optional `stageStates` prop, so both the static pipeline-canvas screen and
  the live migration-run view render the exact same DAG component rather than
  two divergent copies. `apps/web/src/routes/pipeline-detail.tsx` now just
  wraps it (unchanged behavior, confirmed via the same `pnpm test` pass).
- `apps/web/src/components/stage-node.tsx` — `StageNodeData` gained an
  optional `runState?: StageRunState`. Renders a small state dot + a
  `border-2` card color: idle = hairline (`border-line`), running =
  `border-beam` + a `bg-beam animate-pulse` dot (same pulsing-dot vocabulary
  already used for the "Optimizing…" indicator in `new-migration.tsx`, not a
  new animation), done = `border-parity-pass`/`bg-parity-pass`, failed =
  `border-parity-fail`/`bg-parity-fail` — reusing `tokens.css`'s existing
  parity semantic colors and `--beam` accent, no new tokens added. No
  `@keyframes` needed — Tailwind's built-in `animate-pulse` utility (already
  in use elsewhere) covers the "running" pulse.
- `apps/web/src/components/migration-run-bar.tsx` (new) — slim status strip:
  a status dot + label (pulsing while running), "N / M stages" + a progress
  bar while running, `total_cost_usd` ("Cost so far") whenever the backend
  has set it, and the `stop_reason` in `--parity-fail` text for a
  `failed`/`stopped_early` terminal state.
- `apps/web/src/routes/new-migration.tsx`'s `MigrationSuccessScreen` — the
  existing 2s `refetchInterval` poll (`useQuery` on `getMigrationStatus`,
  stops once `status !== "running"`) is unchanged; its old inline
  numeric-only progress block was replaced with `<MigrationRunBar
  status={status} .../>` followed by `<PipelineCanvas pipelineId={pid}
  stageStates={status?.stage_states} />` once the run is `running` or
  terminal — starting a migration now shows the live-colored DAG, not just a
  "3 of 7" counter.
- `apps/web/src/lib/api.ts` — `MigrationOut.stage_states` and the new
  `StageRunState` type added to match the backend response.

**What a user actually sees**: after clicking "Start migration," the wizard's
success screen now shows a slim status bar (pulsing dot + which stage is
optimizing + stage count + cost-so-far once available) directly above the
pipeline's DAG canvas, with each stage node's border/dot live-updating every
~2s as the run progresses — indigo pulsing while a stage is being optimized,
green once done, red if that stage's the one a failure or budget hard-stop
landed on. On completion every node turns green; on a budget/error stop, the
run-bar surfaces the plain-English `stop_reason` in red beneath the bar.

**Verified**: `cd apps/api && uv run pytest -q` → 109 passed (104 baseline +
5 new `stage_states` tests). `cd apps/web && npx tsc --noEmit` → clean.
`cd apps/web && pnpm test` → 69 passed (65 baseline + 4 new `StageNode`
runState tests). `packages/core` not touched (confirmed via `git status`
before commit — only `apps/api`/`apps/web` files changed).

**Explicitly out of scope, not built**: rubric generation still has no live
view (it's a synchronous blocking call with no run object to poll — needs
its own deferred async-rubric-gen phase first, per the task brief). No new
concurrency was introduced — stages still run strictly sequentially
server-side, this phase only makes that existing sequential progress
*visible* in real time.

## Phase A — Live optimizer sub-step signal [DONE — 2026-07-15]

The gap Phase 2's live DAG view (above) left open: `on_attempt` only fires
once per finished, scored sweep attempt, so a "running" stage's node had no
signal for what was actually happening *inside* it — no distinction between
"generating variants" and "waiting on a full sweep." Built on top of Phase
2's `stage_states`/DAG-coloring work, no changes to that mechanism, only
additive: a new, finer-grained `on_phase` callback alongside the existing
`on_attempt`.

**Actual phase sequence found in `loop.py`** (confirms the task brief's
assumption, with one correction — critiquing and refining are two separate
calls per candidate within the same round, not one merged step): both
strategies share `run_sweep_for_stage`, which now fires `"sweeping"` once on
entry and `"scoring"` once the grid is done, right before selection — so
every strategy ends `sweeping → scoring`. **"simple"**: `mutating` (one
`generate_prompt_mutations` call) → `sweeping` → `scoring`. **"prism"**:
`mutating` (round-1 variants) → per round (bounded by `max_refine_rounds`,
plateau-stopped early per candidate — see the "Loop & harness engineering
discipline" section above, unchanged by this phase): `cheap_scoring` (the
judge-free ranking pass) → `critiquing` (the new-in-Phase-1
`judge_single_pass` call feeding reasoning into critique) → `refining` (the
`critique_and_refine` call itself) — then, after all rounds, `sweeping` →
`scoring` → optional few-shot selection (no phase event; it's a single
targeted call on the already-selected winner, not a distinct stage-wide
phase).

**`packages/core`** (`packages/core/src/reprompt_core/optimizer/loop.py`):
- `StagePhase` (`Literal["mutating","cheap_scoring","critiquing","refining","sweeping","scoring"]`)
  and `StagePhaseEvent` (plain `NamedTuple`: `stage_id: int`, `phase:
  StagePhase`) — no DB/FastAPI imports, same headless convention as
  `StageAttempt`.
- `on_phase: Callable[[StagePhaseEvent], None] | None = None` threaded
  through `run_optimizer()` → `_optimize_stage_simple`/
  `_optimize_stage_prism` → `run_sweep_for_stage` — every new parameter
  defaults to `None` and is a true no-op when omitted, confirmed by
  `test_on_phase_is_optional_and_defaults_to_no_op`.
- `run_sweep_for_stage` fires `sweeping`/`scoring` (shared by both
  strategies, so they can never drift on these two). `_optimize_stage_simple`
  fires `mutating`. `_optimize_stage_prism` fires `mutating` once (round 1),
  then `cheap_scoring`/`critiquing`/`refining` once each per round —
  `refining` specifically only fires for a candidate that actually reaches
  the `critique_and_refine` call (not for one skipped by the plateau check
  or a budget hard-stop that lands between `critiquing` and `refining`),
  via a per-round `refining_phase_fired` flag so it's one event per round,
  not one per candidate.
- Tests (3 new, `test_optimizer_loop.py`): the exact phase sequence for
  "simple" and for "prism" (asserting the full ordered list, not just
  membership), plus the no-op-safe default. `packages/core`:
  **267 passed, 21 skipped** (264 + 3 new, same 21 environment-only skips
  as the Phase 1 quality-fixes baseline).

**`apps/api`**:
- `models.py`: `Migration.progress_substep: str | None` — new column, right
  next to `progress_stage_name`. Alembic migration
  `apps/api/alembic/versions/b8e1c4a7f209_add_migration_progress_substep.py`
  (new head, `f3a7b1c9d2e4` → `b8e1c4a7f209`), mirroring
  `f3a7b1c9d2e4_add_base_url_and_migration_progress.py`'s precedent for a
  single nullable `String` column add via `batch_alter_table`.
- `optimizer_runner.py`: a new `on_phase` closure alongside the existing
  `on_attempt`, writing `migration.progress_substep = event.phase` and
  `db.commit()` at the same cadence as `on_attempt` (every call, not
  batched) — threaded into the `run_optimizer(...)` call as `on_phase=on_phase`.
  Deliberately additive/narrow here and in `models.py`/`migrations.py`: a
  separate agent is working on `target_model` tracking in these same two
  files in a parallel worktree (see "Real gap, not yet fixed" under "PR
  #3/#4 review notes" below) — nothing in this phase restructures an
  existing function, only new fields/params/closures.
- `migrations.py`: `MigrationOut.progress_substep: str | None` — chosen
  over folding it into `stage_states`'s values because `progress_substep`
  is a single migration-level field (only one stage is ever "running" at a
  time in this sequential engine), so a top-level field is the smaller,
  more honest diff than making every `stage_states` entry a richer object
  for a value that's only ever non-null for one of them.
- Test: `test_status_reflects_progress_fields` extended to assert
  `progress_substep` round-trips through `GET .../status`, plus a new
  `test_status_progress_substep_defaults_to_none_before_a_run_starts`.
  `apps/api`: **110 passed** (109 baseline + 1 new test file-level count;
  the extended existing test doesn't add a count but the new one does).

**`apps/web`**:
- `lib/api.ts`: `StagePhase` type (mirrors `packages/core`'s exactly) and
  `MigrationOut.progress_substep: StagePhase | null`.
- `components/pipeline-canvas.tsx`: new `runningSubstep?: StagePhase | null`
  prop — attached only to the one DAG node whose derived `runState` is
  `"running"` (`progress_substep` is a migration-level field, not
  per-stage, so it would be misleading to attach it to every node).
- `components/stage-node.tsx`: `StageNodeData` gained `substep?: StagePhase
  | null`; a new small `text-beam` line renders under the existing pulsing
  dot only when `runState === "running" && substep` — human-readable via a
  new `SUBSTEP_LABEL` map (`mutating` → "Generating prompt variants",
  `cheap_scoring` → "Ranking candidates", `critiquing` → "Critiquing
  weakest candidates", `refining` → "Refining prompt", `sweeping` →
  "Running parameter sweep", `scoring` → "Scoring candidates") — never the
  raw enum value.
- `routes/new-migration.tsx`: `<PipelineCanvas runningSubstep={status?.progress_substep} />`
  added alongside the existing `stageStates` prop.
- Tests: 4 new in `stage-node.test.tsx` (the label renders while running,
  every `StagePhase` maps to its human label, no label when not running,
  no label when running with no substep known yet). Fixed one pre-existing
  test fixture (`new-migration.test.tsx`) that needed `progress_substep:
  null` added to satisfy `MigrationOut`'s now-required field.
  `npx tsc --noEmit` clean. `apps/web`: **73 passed** (69 baseline + 4 new),
  9 test files.

**What a user actually sees**: while a stage's node is pulsing indigo
("running") on the live migration screen, a small indigo sub-line now
appears under the stage name reading e.g. "Running — critiquing weakest
candidates" or "Running — running parameter sweep," updating roughly every
poll interval (~2s, same `refetchInterval` Phase 2 already set up) as the
optimizer moves through mutation, critique/refine rounds (Prism only), and
the final sweep/score pass for whichever stage is currently active.

**Explicitly out of scope, not touched**: `Candidate`'s schema/`target_model`
(a different agent's parallel work — see "PR #3/#4 review notes" below);
the migration wizard's model picker.

## PR #3/#4 review notes — Phase 4 landed differently than originally spec'd

An external contributor (`shreychechani`) built Phase 4 + 4b independently
(PR #3, then extended in PR #4) — reviewed end-to-end (diff read, all 3
test suites actually run in an isolated `git worktree`, not just read)
before merging. Real differences from this file's original Phase 4 spec,
worth knowing before touching `optimizer_runner.py`/`migrations.py` again:

- **`target_model_config` shape changed**: was `{"default": "<model>",
  "stages": {<per-stage override>}}` (this file's original spec) → now
  `{"models": ["<model1>", "<model2>", ...]}` — a list of candidate models
  tried against *every* stage, budget shared across all of them via one
  `BudgetTracker`, best kept per stage. Bigger scope than originally
  planned (compare multiple models in one migration run, not just target
  one). `optimizer_runner._get_target_models()` reads both shapes for
  backward compatibility with any migration rows created under the old
  schema — but note it only reads the old shape's `default`, silently
  dropping any old per-stage `stages` overrides (acceptable: no real
  migrations existed under the old schema yet at merge time).
- **Real gap, now FIXED (2026-07-15)**: `Candidate` (apps/api) now records
  *which* target model produced a given attempt. Added non-nullable
  `Candidate.target_model: str` field, Alembic migration
  `8c4f6d1a3e9b_add_target_model_to_candidates.py`, and wiring in
  `optimizer_runner.py`'s `on_attempt` callback to pass the current
  target_model from the loop context. Test: `test_candidate_rows_populated_with_target_model`
  verifies candidates get correct target_model when migration tries
  multiple models. Once a migration tries multiple models, each `Candidate`
  row now explicitly records which model it was tuned for. Enables future
  scorecard/cross-model comparison logic.
- Two trivial issues found and fixed directly (not worth a follow-up PR):
  an unused `ModelOption` import in `new-migration.tsx` (real `tsc
  --noEmit` error), and a missing `db.rollback()` in
  `optimizer_runner.py`'s failure-recovery path (narrow edge case — only
  matters if the exception that triggered it was itself a DB-level error,
  which would otherwise leave a migration stuck at `"running"` forever).
- Full review detail (process used, every finding) kept in
  `.local/pr-reviews/PR_REVIEW.md` — gitignored, local-only, per standing
  instruction not to commit review working files to the repo.

## Working in parallel (more than one developer/AI at once)

- **2026-07-16**: "Phase 2 — Project/multi-run ingestion" (this file's own
  dated section above) was built in `.worktrees/phase2`
  (`phase2-project-multirun` branch) while a second agent worked in
  `.worktrees/phase3` on unrelated work also touching
  `apps/api/src/reprompt_api/pipelines.py` and
  `apps/web/src/routes/pipeline-workspace.tsx`. Phase 2's changes to both
  files are additive only (new endpoints/route in `pipelines.py`; a new
  header button + a new drawer component in `pipeline-workspace.tsx`, no
  existing function bodies restructured) specifically to keep the eventual
  hand-merge low-risk — check `git log`/the diff on both files at merge
  time for what phase3 added before assuming a conflict is real vs. two
  clean additive diffs that just happen to touch the same file.
- **Check "Current state" above before claiming a phase.** It says what's
  actually done vs. not — if two people start Phase 4 without checking
  here first, that's wasted work for one of them. If you start a phase,
  say so in this paragraph (e.g. "Phase 4 — in progress, started by
  <name/session>, currently on the `optimizer_runner.py` query plan") so
  a second person opening this file sees it's claimed, not just "not
  started."
- **The phases have a real dependency order** — Phase 4b needs Phase 4's
  actual functions to exist (it tests them), Phase 6 needs 4+4b done. But
  **Phase 5 (docs) has no code dependency** and can be picked up by a
  second person in parallel with someone else doing Phase 4/4b — they
  don't touch the same files.
- **This file is a merge-conflict hotspot precisely because everyone is
  told to update it.** If two people finish work around the same time,
  expect a conflict in the "Current state" paragraph and whichever phase
  headers both touched. Resolve by keeping *both* people's `[x]`/`[DONE]`
  marks (they're additive — nothing here should ever get un-marked done
  by a merge) and hand-merging the "Current state" prose into one
  accurate paragraph, not by picking one side and discarding the other's
  update.
- **Work on separate branches per phase where possible**, merge
  sequentially, and re-verify both test suites after each merge (a clean
  merge of code doesn't guarantee the combined behavior is still
  correct — this project's own standing rule, not unique to parallel
  work).
- **Never push directly to `master` without the human's go-ahead** — this
  applies per-session/per-AI-instance the same way it applies to a single
  developer; two AI sessions both assuming "someone else will ask
  permission" is how an unreviewed push happens.

## Why two strategies, and why the name "Prism"

**Prism** is our own implementation of PromptWizard's published technique
(mutate → score → critique → refine, iterate; plus synthetic few-shot
example generation) — the essence of the approach, extracted and
rebuilt in-house rather than depending on their package. Built entirely
on the engine's own already-universal `llm/client.py`, so it works with
any provider (OpenAI, Anthropic, Gemini, self-hosted Ollama/vLLM/etc.)
uniformly, with no proxy and no extra dependency. Named to match the
existing brand — the logo and `ParityBeam` UI component already use a
beam-splitting-into-spectrum visual; Prism is exactly that: one prompt
refracted into multiple analyzed, refined variants, vs. **simple** (the
existing one-shot mutation strategy) being a beam that passes straight
through once. Both strategies stay available, selected via
`OPTIMIZER_STRATEGY`.

## Project status — M0 through M5

**M0 — Design system: done.** Design tokens (`tokens.css`), `ParityBeam`
component (animated match indicator), `Logo` component + standalone
`docs/logo.svg`, persistent `AppShell` nav rail wired into all 7 pages,
`/dev/kit` design-system showcase screen.

**M1 — Core data + import: done.** Universal trace schema v1.1
(provider/product-agnostic — `Pipeline`→`Stage[]`, `Trace[]`→`StageRecord[]`),
DAG builder (Kahn's algorithm, topological layering, cycle detection),
SQLAlchemy models + Alembic migrations, import/upload API + validation
report endpoint, real-data "query log" importer (dependency inference,
stage-id disambiguation). Screens: Pipelines home, Import wizard, Pipeline
canvas (DAG visualization with model/token/latency badges).

**M2 — Evaluators + rubric engine: done.** Deterministic-checks evaluator
(6 rule types), embedding-similarity evaluator (bge-m3, local, no API
key), pairwise LLM judge (position-swap bias control), composite scorer
(weighted formula, hard-gate on schema failures), LLM-powered rubric
generator (one call per stage, retry-once-on-failure policy). Rubric
review screen built. **Known gap:** rubric generation works via API but
has no trigger button in the UI yet (manual seeding only) — tracked as
the first item in `docs/DEVELOPMENT.md`'s remaining plan.

**Auth + Settings + BYOK: done.** Magic-link auth (dev-mode links since no
email provider yet), HMAC-signed session tokens, per-workspace encrypted
API key storage (Fernet), self-hosted endpoint support
(`WorkspaceApiKey.base_url`), Settings screen, JSON Schema export of the
trace format (`GET /trace-format/schema`) with a drift test.

**M3 — Optimizer loop: in active development.** Non-LLM groundwork (model-
card per-family prompt transforms, param/format sweep generator, budget
tracker, selection rule) done earlier. The actual loop (mutation →
execution → scoring → selection, in two strategies) is being built now —
see the phase-by-phase breakdown below for exact status.

**M4 — Full migration run: not started.** Depends on M3. 3-pass migration
(teacher-forced → end-to-end → holdout), progress screen, results screen
(score delta per stage).

**M5 — Product polish: partial.** Done: auth, settings, BYOK, branding
(logo, centered README with badges). Not done: model-card picker in the
migration wizard, scorecard screen, config export — all depend on M3/M4
producing real results to show.

## Phase 0 — Cleanup [DONE — 2026-07-12]

- [x] Removed an earlier, abandoned attempt at depending directly on an
      external package for the Prism strategy — reverted cleanly, no
      trace left in `pyproject.toml`/`uv.lock`
- [x] `packages/core` full suite: 255 passed, 2 skipped
- [x] `apps/api` full suite: 99 passed (after fixing
      `test_list_api_keys_returns_multiple_providers_sorted`, which was
      correctly failing since it asserted the old `ApiKeyOut` shape before
      `base_url` was added — see "Groundwork" below)

## Groundwork — self-hosted BYOK + Migration progress fields [DONE]

Done before the Prism/simple split was decided, still needed by both
strategies:

- [x] `apps/api/src/reprompt_api/models.py`:
  - `WorkspaceApiKey.base_url: str | None` — customer self-hosted endpoint
    (Ollama/vLLM/LM Studio/etc), forwarded to LiteLLM as `api_base`
  - `Migration`: added `total_cost_usd`, `stopped_early`, `stop_reason`,
    `progress_stage_name`, `progress_current`, `progress_total`,
    `completed_at` (all nullable) — for the polling status endpoint in
    Phase 4
- [x] Alembic migration:
  `apps/api/alembic/versions/f3a7b1c9d2e4_add_base_url_and_migration_progress.py`
  — applied cleanly against a full rebuild of the dev DB
- [x] `apps/api/src/reprompt_api/llm_context.py`: `base_url` threaded
  through `complete_with_workspace_credentials()` as `api_base=`,
  `_resolve_workspace_key_row()` extracted so both `resolve_workspace_credential`
  and the base_url lookup share one query
- [x] `apps/api/src/reprompt_api/settings.py`: `base_url` in
  `ApiKeyCreate`/`ApiKeyOut`, round-trips through add/list

## Why guided critique/refine instead of DSPy or genetic/Pareto search

Considered and deliberately not used, for Prism's mutation step:

- **Genetic/evolutionary search** (population + crossover + selection over
  generations) needs dozens-to-hundreds of evaluations to converge, and
  every evaluation here is a real, paid LLM call against a hard per-
  migration dollar budget (`BudgetTracker`). Not viable for an
  every-migration product feature at that evaluation cost.
- **Critique-guided refinement converges faster.** PromptWizard's actual
  insight — using the LLM's own understanding of *why* a candidate failed
  to directly propose a better one — is a guided local search, not blind
  mutation + selection pressure. Fewer, smarter calls beat many, dumb ones
  under a tight budget. This is *why* we're drawing from PromptWizard's
  technique specifically rather than a generic evolutionary optimizer.
- **DSPy** is a full framework (Signatures/Modules/optimizers) that would
  mean restructuring stage/prompt representation to fit its programming
  model, plus a new dependency — the same class of adoption cost already
  rejected for PromptWizard's own package. We already have a purpose-built
  rubric-based evaluation pipeline (`scoring.py`) richer than a generic
  DSPy metric function would be; bridging DSPy's optimizer loop into it
  would add indirection for unclear benefit.
- **Pareto/multi-objective search** needs more evaluations to build a
  meaningful front, and `selection.py` already encodes a simpler,
  explainable rule instead (best candidate that clears `parity_threshold`,
  else best-effort) — a deliberate, already-documented "cut from MVP" in
  the original plan doc, not an oversight.
- **Optuna remains the right tool for *numeric* search** (temperature/
  format sweep, already built — `sweep.py`'s `GridSampler` was chosen so
  it can swap to a Bayesian sampler later without re-plumbing). Prompt
  *text* mutation is a discrete, semantic space where an LLM proposing
  variants is the natural operator regardless of the search strategy
  wrapped around it.

## Loop & harness engineering discipline — apply throughout Phases 1-2

Two established disciplines from the broader AI-agent-engineering
literature (studied via `cobusgreyling/loop-engineering` and
`ai-boost/awesome-harness-engineering` — browsed for ideas only, nothing
cloned into this repo, per this project's standing policy on external
reference material). Most of both repos target autonomous, multi-tool
*agents*, which Prism is not (it's a small, bounded, deterministic
pipeline — no dynamic action space, no tool-calling) — so their heavier
frameworks (agent loops, planning/task decomposition, permissions,
sandboxes, cross-session memory) don't apply here. Four specific,
concrete practices from that literature genuinely do apply and must be
followed when building Phases 1-2:

### 1. Early-stopping on plateau (loop engineering)

**The gap:** as spec'd, if `max_refine_rounds` allows more than one round,
Prism would keep spending on refinement even if a round produced no real
improvement over the previous one — wasted budget for no benefit.

**The rule:** after each critique/refine round, compare the new best
`cheap_score` for a candidate to its `cheap_score` from the previous
round. If the improvement is below a small threshold —
`PLATEAU_EPSILON = 0.02` (same 0-1 scale as every other score in this
codebase) — stop refining *that specific candidate* early, even if
`max_refine_rounds` would allow another round. This only has a visible
effect once `max_refine_rounds > 1` is actually built (Phase 2 currently
specs `max_refine_rounds` fixed at effectively 1) — but design
`_optimize_stage_prism`'s internal round-loop with this check from the
start, so generalizing to >1 round later doesn't require retrofitting it.
**Implemented and corrected during Phase 2** (2026-07-12): the first draft
tracked `previous_cheap_score` keyed by candidate *text*, which is a bug —
each round's refined candidates have entirely new text, so that lookup
never matches across rounds and the plateau check silently never fires.
Fixed via `candidate_baseline: dict[str, float]`, keyed by a refined
candidate's text but storing its *parent's* cheap_score (set at the moment
of refinement, not looked up later) — the score a refined candidate must
beat by more than `PLATEAU_EPSILON` when *it* gets ranked in the next
round to justify refining it again. Round-1 candidates have no baseline
(nothing to compare against yet), so they always get a first refinement
attempt. See `_optimize_stage_prism` in `loop.py` for the actual code;
covered by `test_prism_plateau_early_stop` in
`test_optimizer_loop.py`.

### 2. Harness discipline at every new LLM call site (harness engineering)

**Already true, consistently, for every existing call site**
(`generate_prompt_mutations`, `judge_pairwise`, `generate_rubric`): a
Pydantic `response_format` schema for structured output, a
retry-once-on-malformed-JSON policy, a distinct documented exception type
(`PromptMutationError`, `JudgeResponseError`, `RubricGenerationError` —
never a bare `Exception`), and every real spend recorded via
`budget.record_spend()` regardless of whether the call's *content* ended
up usable (the money was already spent once the call happened — see
`budget.py`'s own documented design decision).

**The rule going forward:** every new call site Prism adds — the
cheap-score completion call (step 2 of the per-stage algorithm above),
`critique_and_refine()`, `select_few_shot_examples()` — must follow this
exact same discipline. Do not let a later call site get looser under time
pressure just because it's "only" a refinement step; a malformed critique
response is exactly as capable of corrupting the loop as a malformed
mutation response would be, and the retry-once/typed-exception pattern is
cheap to apply consistently. Treat this as a checklist item when
implementing each function in Phase 1, not an afterthought.

### 3. Name the verification harness explicitly

The three-way scorer (`reprompt_core.deterministic` +
`reprompt_core.embedding` + `reprompt_core.judge`, combined by
`reprompt_core.scoring.score_candidate`) *is* what the harness-engineering
literature calls a "verification harness" — the scaffolding that lets the
rest of the system trust a candidate's output without a human checking
every one by hand. This is already fully built; the only action item is
documentation: when Phase 1/2 code and docstrings reference "the scorer,"
it's worth one sentence acknowledging this is deliberately the system's
verification harness, not just a scoring utility — so a future reader
recognizes it as a named design category rather than an implementation
detail, especially if the product ever adds a second kind of pipeline
(non-LLM stages, tool calls, etc.) that would need its own harness in the
same spirit.

### 4. Bound context growth across rounds (context delivery/compaction)

**The risk:** once `max_refine_rounds > 1` exists, a naive implementation
of `critique_and_refine()` could accumulate the *full history* of every
previous round's critique + attempted refinement into each new call's
prompt — growing unboundedly with each round, inflating both cost and
latency for no proportional benefit (older rounds' critiques are largely
superseded by newer ones anyway).

**The rule:** each `critique_and_refine()` call should only ever include
the *current* candidate's *most recent* critique/attempt as context, not
the full round-by-round history. If a future iteration wants the model to
avoid repeating a previously-failed refinement direction, pass forward a
short, explicitly-summarized "previously tried and didn't help: ..." note
rather than the full prior conversation — same bounded-context principle,
applied deliberately rather than by accident.

## Phase 1 — Extend `mutator.py` for Prism [DONE — 2026-07-12]

File: `packages/core/src/reprompt_core/optimizer/mutator.py` (existing —
`generate_prompt_mutations()` already there, stays unchanged, is the
"simple" strategy's only mutation step, and is also Prism's round-1
variant generator — Prism does not replace it, it adds rounds after it).

### 1a. Variant framing (round 1) — reuse as-is, no changes needed

`generate_prompt_mutations()` already asks for varied framing across its
`num_variants` (different explicitness/ordering/few-shot-vs-zero-shot).
PromptWizard's technique additionally frames each variant through a
distinct "expert identity"/"thinking style" persona (e.g. "an expert
technical writer", "a meticulous fact-checker") to force real diversity
rather than superficial rewording. Worth strengthening the existing
system prompt in `mutator.py` (`_SYSTEM_PROMPT_TEMPLATE`) to explicitly
ask for one distinct persona per variant — small change, do it as part of
Phase 1 rather than a separate step, since it's the same call.

### 1b. `critique_and_refine()` — the new core function

```python
def critique_and_refine(
    prompt_variant: str,
    score: CompositeScore,
    original_examples: Sequence[MutationExample],
    rubric: dict[str, Any],
    target_model: str,
    *,
    call: Callable[..., LLMResponse],
    mutator_model: str | None = None,
    temperature: float = DEFAULT_MUTATOR_TEMPERATURE,
    timeout: float | None = None,
) -> PromptMutationResult:  # .variants has exactly 1 entry: the refined prompt
```

One LLM call. Prompt construction shows the model, concretely:
- The candidate prompt that underperformed.
- **Exactly what failed**, drawn straight from `score: CompositeScore` —
  `score.deterministic.results` (per-check `passed`/`reason`, already
  human-readable per `deterministic.py`'s design), `score.gate_reason` if
  gated, `score.judge_score` and (if available) the judge's own
  per-criterion `reasoning` text (`JudgeResult.criteria[i].reasoning`,
  from `judge.py` — thread this through if a judge call happened for this
  candidate; the loop already has the `JudgeResult`, not just the float,
  at the point where this would be called — pass the reasoning text
  through, don't discard it).
- Ask for: (a) a short critique — *why* this likely failed against the
  specific checks/criteria shown, and (b) one refined prompt variant
  addressing that critique specifically (not a generic rewrite).

Same structural conventions as `generate_prompt_mutations`: a
`_RawCritiqueOutput` Pydantic model (`critique: str`, `refined_prompt: str`),
retry-once-on-malformed-JSON, `PromptMutationError` on total failure
(caller — `loop.py` — degrades to "keep the un-refined variant" on this
error, same graceful-degradation pattern the existing mutation call
already uses).

### 1c. `select_few_shot_examples()` — optional, Prism-only

```python
def select_few_shot_examples(
    prompt: str,
    examples: Sequence[MutationExample],
    *,
    call: Callable[..., LLMResponse],
    model: str,
    max_examples: int = 2,
) -> list[MutationExample]
```

Asks the mutator model to pick (not fabricate) the `max_examples` most
illustrative *real* benchmark examples already available for this stage
to append as few-shot context to the winning prompt — genuinely picking
from `stage_input.examples`, never inventing new ones (avoids introducing
unvetted synthetic data into a real customer's prompt). Only called when
`include_few_shot=True` on `run_optimizer`, and only once per stage on
the *final* winning candidate (not per round — no point selecting
few-shot examples for a candidate that doesn't end up winning).

Reuse existing patterns exactly throughout: `_parse_raw_output`-style
helper, `_sum_optional` for combining cost across a retry, same
system-prompt-construction style as `_build_messages`.

## Phase 2 — Extend `loop.py` with strategy selection [DONE — 2026-07-12]

File: `packages/core/src/reprompt_core/optimizer/loop.py`. Already has
(from earlier work, done):

- `run_sweep_for_stage(stage_input, prompt_candidates, *, call, budget, judge_model, parity_threshold, max_sweep_candidates_per_prompt, on_attempt) -> StageResult`
  — the backend/strategy-agnostic half (model-card transform, template
  render, param/format sweep, scoring, budget accounting, selection).
  **Do not duplicate this logic** — both strategies call it, it never
  needs to know which strategy generated `prompt_candidates`.
- `_optimize_stage(...)` — currently the "simple" strategy's
  implementation: generate variants via `generate_prompt_mutations` once,
  call `run_sweep_for_stage`.

To do:

- [ ] Add `strategy: Literal["simple", "prism"] = "simple"` parameter to
      `run_optimizer()`, threaded down to stage optimization.
- [ ] Rename current `_optimize_stage` to `_optimize_stage_simple` (or
      keep the name, add a new `_optimize_stage_prism`) — dispatch on
      `strategy` inside `run_optimizer`'s per-stage loop.

### Prism's per-stage algorithm, step by step

```
1. GENERATE  generate_prompt_mutations(original, ..., num_variants=N)
             → candidates = [original, variant_1, ..., variant_N]

2. CHEAP SCORE each candidate (deterministic + embedding only — NOT the
             judge, regardless of should_run_judge's gate; this pass
             exists purely to rank candidates cheaply before spending on
             a judge call, so it must itself stay free/local):
             for each candidate:
               render + apply_model_card_transform (reuse from
               run_sweep_for_stage's existing helpers — extract
               _render_template/_apply_format_mode if needed as shared
               module-level functions, don't duplicate)
               → one real completion() call at a fixed default param
                 point (temperature=0.2, structured_output_mode=False —
                 NOT the full sweep grid yet, that's step 5)
               → evaluate_deterministic_checks + embedding_similarity
               → cheap_score = deterministic_score*0.5 + embedding*0.5
                 (a simple local ranking heuristic, distinct from the
                 real CompositeScore weights — this is only for picking
                 which candidates are worth refining, never persisted as
                 a real Candidate row's score)

3. RANK      sort candidates by cheap_score ascending, take the weakest
             min(2, len(candidates)) — these are the ones worth refining;
             a candidate that's already scoring well doesn't need a
             critique pass spent on it.

4. CRITIQUE+REFINE each weakest candidate:
             critique_and_refine(candidate, its_real_score_from_step_2,
               examples, rubric, target_model, call=call, ...)
             → wrap in try/except PromptMutationError: on failure, log +
               skip this one refinement (keep going with whatever
               refined variants did succeed) — never abort the stage over
               this, matching the existing mutation-failure fallback
               pattern in _optimize_stage today.
             → append each successful refined_prompt to `candidates`

5. FULL SWEEP  run_sweep_for_stage(stage_input, candidates, ...) — exactly
             the existing shared function, completely unchanged. This is
             where the real param/format grid + full scoring (with judge,
             gated by should_run_judge as normal) + budget accounting +
             selection all happen, for the ORIGINAL + MUTATED + REFINED
             set together. No special-casing for which candidates came
             from which step.

6. FEW-SHOT  (only if include_few_shot=True) select_few_shot_examples()
             on the StageResult.best.prompt_variant that step 5 selected,
             attach to StageAttempt.few_shot_examples.
```

`max_refine_rounds: int = 1` bounds steps 2-4 to run once. `>1` would
repeat critique→refine→cheap-score again before the final step-5 sweep —
only build that generalization if it's cheap to do once step 1 exists;
otherwise ship fixed at effectively 1 round and note the generalization
as a documented follow-up rather than over-building speculatively.

- [ ] Thread judge reasoning into the critique step: at the point in
      `run_sweep_for_stage` where a `JudgeResult` is obtained (currently
      only `judge_result.overall_score` is kept, `judge_result.cost_usd`/
      `latency_ms` are captured, the per-criterion `reasoning` text is
      currently discarded) — Prism's critique step wants the RAW
      candidate outputs' cheap-score detail, not judge reasoning, since
      step 2 deliberately skips the judge. No `run_sweep_for_stage` change
      needed for Phase 2 itself; only relevant if a future round wants to
      critique using judge output too — note this as explicitly
      out-of-scope for the first Prism implementation, not silently
      dropped.
- [ ] `include_few_shot: bool = False` param — if set (Prism only), call
      `select_few_shot_examples()` on the winning candidate and attach the
      result somewhere visible on `StageResult`/`StageAttempt` (add a
      field, e.g. `StageAttempt.few_shot_examples: list[dict] | None`).
- [ ] `BudgetTracker.is_exhausted` remains the one real hard stop for
      *both* strategies — step 2's cheap-score completion calls and
      step 4's critique/refine calls both record spend via
      `budget.record_spend()` like every other call already does (cheap
      scoring still makes one real completion call per candidate — it's
      "cheap" in that it skips the judge and uses one fixed param point
      instead of the full grid, not that it's free). Check
      `budget.is_exhausted` before starting step 2 and before each
      candidate within it, same pattern already used in
      `run_sweep_for_stage`.

## Phase 3 — `packages/core` tests [DONE — 2026-07-12]

`test_optimizer_mutator.py` (10 tests) and `test_optimizer_loop.py` (8
tests) written and passing — see the checklist below for what each
originally-planned test became in practice (a few were combined/renamed
during actual implementation; the coverage they describe is all present).

`packages/core/tests/test_optimizer_mutator.py` — extend with:

- [ ] `test_critique_and_refine_calls_with_score_and_example_context` — mock
      `call` to capture its `messages` argument, assert the prompt actually
      contains the failing check reasons from `score.deterministic.results`
      and (if gated) `score.gate_reason`.
- [ ] `test_critique_and_refine_retries_once_on_malformed_json` — first
      mocked response is invalid JSON, second is valid; assert exactly 2
      calls to `call`, result reflects the second response, `cost_usd` is
      the sum of both.
- [ ] `test_critique_and_refine_raises_after_retry_also_fails` — both
      mocked responses invalid; assert `PromptMutationError` raised, no
      third call attempted.
- [ ] `test_select_few_shot_examples_only_returns_real_examples` — mock
      `call` to return example text that doesn't exactly match any input
      example; assert the function only returns entries actually present
      in the input `examples` list (never fabricates new ones — see Phase
      1's "picks, not fabricates" design note).
- [ ] `test_select_few_shot_examples_respects_max_examples` — input has 5
      examples, `max_examples=2`; assert result length is at most 2.

`packages/core/tests/test_optimizer_loop.py` — extend with:

- [ ] `test_prism_strategy_runs_multi_round_flow` — mock `call` to return
      different responses per round (round-1 mutation → weak cheap-score →
      round-2 critique/refine with an improved response); assert
      `run_sweep_for_stage`'s final candidate set includes the refined
      variant, not just original + round-1 mutations.
- [ ] `test_prism_plateau_early_stop` — mock the critique/refine response
      to *not* improve `cheap_score` beyond `PLATEAU_EPSILON`; assert no
      further round is attempted for that candidate even though
      `max_refine_rounds` would allow one (see the "Loop & harness
      engineering discipline" section above — this is the concrete test
      for point 1 there).
- [ ] `test_simple_strategy_unchanged` — run `strategy="simple"` with the
      exact same mocked `call` sequence used by the pre-Prism test suite;
      assert byte-identical behavior to before this phase (regression
      guard — this strategy must never silently change).
- [ ] `test_prism_budget_hard_stop_mid_loop` — `BudgetTracker` with a tiny
      budget that gets exhausted partway through Prism's cheap-score pass;
      assert the loop stops attempting further candidates and still
      returns a valid `StageResult` from whatever was scored so far.
- [ ] `test_prism_one_stage_failure_does_not_abort_run` — one stage's
      `_optimize_stage_prism` raises an unexpected exception (not a
      `PromptMutationError`, something genuinely unhandled); assert
      `run_optimizer` still returns results for the other stages with this
      one's `StageResult.error` set (mirrors the existing simple-strategy
      test for the same property — don't just add a new test, confirm it
      matches that existing one's assertions shape).
- [ ] `test_prism_call_site_harness_discipline` — for each new Prism call
      site (cheap-score completion, critique/refine, few-shot selection),
      confirm a malformed/exception-raising mocked response is caught and
      handled per the harness-discipline rule (point 2 in the section
      above), not left to propagate raw.

- [ ] Run `cd packages/core && uv run pytest` — must stay at 255+ passed
      plus whatever new tests are added, 2 skipped (unrelated, pre-existing).

## Phase 4 — `apps/api` wiring [NOT STARTED]

### Before you start (if you're picking this up cold)

1. Verify the environment is healthy first, before writing anything:
   ```bash
   cd packages/core && uv run pytest -q   # expect: 273 passed, 2 skipped
   cd ../../apps/api && uv run pytest -q  # expect: 99 passed
   ```
   If either doesn't match, something changed since this was written —
   figure out why before adding Phase 4 on top of an unknown state.
2. Read `packages/core/src/reprompt_core/optimizer/loop.py`'s module
   docstring and `run_optimizer()`'s docstring in full — Phase 4 is purely
   about *calling* this function correctly with real data; it does not
   change anything inside `packages/core`. If you find yourself wanting to
   edit `loop.py` or `mutator.py` to make Phase 4 easier, stop — that's a
   sign the calling convention wasn't understood yet, not that the engine
   needs to change.
3. Scope call for this phase: **only wire up `strategy` selection.** Don't
   expose `mutator_model`, `max_refine_rounds`, `max_sweep_candidates_per_prompt`,
   or `include_few_shot` as new API/UI controls yet — call `run_optimizer()`
   with their defaults (`mutator_model=None`, `max_refine_rounds=1`,
   `include_few_shot=False`) for now. Turning these into real per-migration
   settings is a reasonable *future* enhancement, not part of "make the
   engine reachable at all" — don't gold-plate this phase.

### Definition of done for Phase 4

Not done until all of these are true, in this order:
- [ ] `optimizer_runner.py` exists, `run_optimizer_for_migration()` runs
      the real engine against real DB data (verified against at least one
      seeded pipeline+migration, not just imagined).
- [ ] `POST .../start` and `GET .../status` both exist, both tested
      (Phase 4b).
- [ ] A migration with an unapproved rubric is provably blocked (`422`,
      not a silent no-op or a 500).
- [ ] A migration that completes writes real `Candidate` rows with real
      `scores`/`cost` — checked by actually querying the table after a
      run, not just by reading the code and assuming it's right.
- [ ] `cd packages/core && uv run pytest -q` and
      `cd apps/api && uv run pytest -q` both still pass in full.
- [ ] This section's `[NOT STARTED]` marker (and Phase 4b's, and the
      "Current state" paragraph near the top of this file) updated to
      reflect reality — don't leave the tracker stale once the work is
      actually done, same discipline as every phase before this one.

### `apps/api/src/reprompt_api/optimizer_runner.py` (new)

Reads `OPTIMIZER_STRATEGY` env var (`os.environ.get("OPTIMIZER_STRATEGY", "simple")`).

**Building `stages: list[StageOptimizationInput]`** — concrete query plan,
using the real schema (see `apps/api/src/reprompt_api/models.py`):

```python
stages = db.scalars(select(models.Stage).where(models.Stage.pipeline_id == pipeline_id)).all()
for stage in stages:
    # target model resolution: Migration.target_model_config shape is
    # {"default": "<model>", "stages": {"<stage.id>": "<model override>"}}
    # (string keys — migrations.py's create_migration already validates
    # these against real stage ids at creation time)
    target_model = migration.target_model_config.get("stages", {}).get(
        str(stage.id), migration.target_model_config["default"]
    )

    rubric = db.scalar(select(models.Rubric).where(models.Rubric.stage_id == stage.id))
    # rubric may be None if ungenerated — see the approval-gate check below,
    # which must catch this before optimizer_runner is ever invoked

    # Benchmark examples: Pipeline -> BenchmarkSet -> Trace[] -> StageRecord[]
    # filtered by stage_id, same source rubric_generator.py already reads.
    records = db.scalars(
        select(models.StageRecord)
        .join(models.Trace, models.StageRecord.trace_id == models.Trace.id)
        .join(models.BenchmarkSet, models.Trace.benchmark_set_id == models.BenchmarkSet.id)
        .where(models.BenchmarkSet.pipeline_id == pipeline_id, models.StageRecord.stage_id == stage.id)
        .order_by(models.StageRecord.id)
        .limit(8)  # same cap convention as rubric_generator.DEFAULT_MAX_SAMPLES
    ).all()
    # records[0] becomes examples[0] - the "representative example" Phase
    # 1/2's run_sweep_for_stage scores every attempt against (see loop.py's
    # own module docstring on why M3 uses one representative example, not
    # multi-example holdout - that's M4's job)
```

Builds `StageOptimizationInput(stage_id=stage.id, stage_name=stage.name,
original_prompt_template=stage.prompt_template, target_model=target_model,
rubric={"deterministic_checks": rubric.deterministic_checks,
"judge_criteria": rubric.judge_criteria}, examples=[{"input": r.input,
"output": r.output} for r in records])` per stage.

**`on_attempt` callback** — persists a `Candidate` row per attempt (real
field names: `migration_id`, `stage_id`, `prompt_variant`, `params`,
`format`, `scores`, `cost`, `latency` — note `format` not `format_mode`,
and `scores` is the JSON dict, not a single float — map from
`StageAttempt.scores`/`format_mode`/`cost_usd`/`latency_ms` accordingly,
names don't match 1:1), and updates
`Migration.progress_stage_name/progress_current/progress_total` after
each stage completes (not after each attempt — that would be too chatty
for a polling endpoint; stage-level granularity is enough signal).

**Entry point**: `run_optimizer_for_migration(db: Session, migration_id: int) -> None`
— loads `Migration`/`Pipeline`/`Workspace` fresh from `db` (this runs
inside a `BackgroundTasks` task, which needs its own session — see the
`GET .../status` note below on why), builds `stages`, resolves a
`judge_model` (use `migration.target_model_config.get("judge_model")` if
present, else fall back to `target_model_config["default"]` — no new
config surface needed for this phase, document the fallback clearly),
calls `run_optimizer(stages, call=lambda model, messages, **kw:
complete_with_workspace_credentials(db, workspace, model, messages, **kw),
budget=BudgetTracker(budget_usd=migration.budget),
judge_model=judge_model, strategy=strategy, parity_threshold=migration.parity_threshold,
on_attempt=on_attempt)`. Sets final `Migration.status` (`"completed"` if
`not result.stopped_early` else `"stopped_early"`),
`total_cost_usd=result.total_cost_usd`, `stopped_early`, `stop_reason`,
`completed_at=datetime.now(timezone.utc)`, commits. Wraps the whole body
in try/except: any unhandled exception sets `status="failed"` with the
exception string as `stop_reason` instead of leaving `status="running"`
stuck forever — this is the one case where a bug must still leave the DB
in a legible state for the UI to show something sane.

### `apps/api/src/reprompt_api/migrations.py` — new endpoints

- **`POST /pipelines/{pipeline_id}/migrations/{migration_id}/start`**
  - Load the `Migration`, 404 if not found or wrong pipeline.
  - Check every `Stage` in scope (per `target_model_config`'s keys, or all
    stages if only `"default"` is set) has a `Rubric` row with
    `approved=True` — if any is missing/unapproved, `422` naming the
    stage(s) by `name` (not just id — a human-readable error).
  - Else: set `migration.status = "running"`, commit, then
    `background_tasks.add_task(run_optimizer_for_migration, ..., migration_id=migration.id)`
    — status is set *before* `add_task` so a client polling immediately
    after `start` returns always sees `"running"`, never a stale
    `"pending"` from a race with the background task actually starting.
  - Returns the updated `Migration` (reuse whatever `MigrationOut` schema
    `migrations.py` already has for `create_migration`, extended with the
    new progress/cost fields).
- **`GET /pipelines/{pipeline_id}/migrations/{migration_id}/status`**
  - Plain read of the `Migration` row's `status`/`progress_*`/`total_cost_usd`/
    `stopped_early`/`stop_reason`/`completed_at` fields — no computation,
    just what `optimizer_runner.py`'s background task last wrote. No SSE
    (none exists in this codebase yet, none needed here — matches the
    "no Docker/no proxy" constraint already established for this whole
    feature; a client polls this on an interval, e.g. every 2s, from the
    migration detail screen).

**`apps/api/.env.example`** (new — doesn't exist yet; the repo-root
`.env.example` is only for the optional Postgres/Langfuse docker-compose
stack, a different thing). Create one covering every env var `apps/api`
actually reads, so a new developer doesn't have to grep the source to
discover them — at minimum: `DATABASE_URL` (commented out, showing the
default), `REPROMPT_SETTINGS_ENCRYPTION_KEY` (placeholder value + a
comment saying `scripts/setup.sh` generates a real one), `REPROMPT_DEV_MAGIC_LINKS`
(default `true`, from `auth.py`), and the new `OPTIMIZER_STRATEGY=simple`
with a one-line comment pointing at this file's "Why two strategies"
section for what `prism` does.

## Phase 4b — `apps/api` tests [NOT STARTED]

- [ ] `test_start_blocked_when_rubric_not_approved` — create a migration
      where one stage's rubric exists but `approved=False`; assert `422`
      and the response names that stage.
- [ ] `test_start_blocked_when_rubric_missing_entirely` — a stage with no
      `Rubric` row at all; assert `422` (distinct case from
      "exists but unapproved" — both must be caught, test both).
- [ ] `test_start_happy_path_sets_running_and_schedules_task` — mock
      `run_optimizer_for_migration` (patch it out entirely — this test
      layer never makes real LLM calls, that's Phase 3's job); assert
      response status is `"running"` immediately, and the mocked function
      was scheduled (via FastAPI's test client + `BackgroundTasks`, which
      runs the task synchronously in tests — assert it was actually
      invoked with the right `migration_id`).
- [ ] `test_status_reflects_progress_fields` — directly write
      `progress_stage_name`/`progress_current`/`progress_total` onto a
      `Migration` row, `GET .../status`, assert the response matches
      exactly.
- [ ] `test_status_reflects_terminal_states` — one test each for
      `status="completed"` (with `total_cost_usd` set) and
      `status="failed"` (with `stop_reason` set) — confirm both surface
      correctly, not just the "running" happy path.
- [ ] Run `cd apps/api && uv run pytest` — must stay at 99+ passed.

## Phase 5 — Docs [PARTIALLY DONE]

- [x] This file
- [ ] `README.md` — one line pointing at this file
- [ ] `docs/DEVELOPMENT.md` — "Remaining plan" section updated to point
      here instead of carrying its own separate M3 description (avoid two
      sources of truth drifting apart)

## Phase 6 — Final verification & handoff [NOT STARTED]

- [ ] `cd packages/core && uv run pytest` — full suite green, including
      every new Phase 3 test.
- [ ] `cd apps/api && uv run pytest` — full suite green, including every
      new Phase 4b test.

**Manual walkthrough** (needs a real BYOK key configured — see README's
"Getting an AI model API key" section):

1. Import a pipeline (or reuse a seeded one), confirm at least one stage
   has a `Rubric` row (seed via `seed_rubrics.py` if none exists yet).
2. Approve that stage's rubric via the rubric review screen (or directly:
   `rubric.approved = True` + commit, if the UI trigger from
   `docs/DEVELOPMENT.md`'s remaining-plan item 1 isn't built yet).
3. Create a `Migration` via the existing wizard (`POST .../migrations`)
   with a real `budget` and a `target_model_config` pointing at a real,
   configured provider.
4. `OPTIMIZER_STRATEGY=simple` (or leave default) → `POST .../start` →
   confirm `422` if you deliberately leave a stage unapproved first (test
   the gate before testing the happy path), then approve and retry →
   confirm `200`, `status="running"`.
5. Poll `GET .../status` every couple seconds until `status="completed"`
   (or `"stopped_early"`/`"failed"` — inspect `stop_reason` if so).
6. Query `Candidate` rows for this `migration_id` directly (DB browser or
   a quick script) — confirm real `scores`/`cost`/`params`/`format`
   values, not placeholders, and confirm the count is plausible given
   `max_sweep_candidates_per_prompt` × number of prompt variants tried.
7. Repeat steps 4-6 with `OPTIMIZER_STRATEGY=prism` on a fresh migration
   — additionally confirm: at least one stage's winning candidate came
   from a refined (not original/round-1-mutation) variant for at least
   one test run (Prism's whole value proposition is that refinement
   sometimes wins — if it *never* does across several manual runs, treat
   that as a signal to revisit the critique prompt's quality, not just a
   passing/failing checkbox).
8. Confirm a deliberately-tiny `budget` (e.g. `$0.01`) on a migration
   produces `stopped_early=True` with `stop_reason` mentioning budget,
   for both strategies.

- [ ] Git commands given to the user to run (never pushed by the AI
      session itself — standing project rule): `git add` the specific
      changed files (never `git add -A` — this repo's working tree
      routinely accumulates local-only DB files like `apps/api/test.db`/
      `reprompt.db` that must never be committed), a commit message
      summarizing the phase(s) completed, and `git push origin master`
      left for the user to actually run.

## Phase D(a) — Model-card info in wizard [DONE — 2026-07-15]

Read-only display of model card transform rules in the migration wizard's
model picker, so users can see what prompt rewrites will be applied to each
target model's variants. No changes to `packages/core/src/reprompt_core/llm/model_card.py`
itself (read-only use only); no changes to `migrations.py`, `optimizer_runner.py`,
or `loop.py` (other agents own those files in parallel worktrees).

**Backend** — `apps/api/src/reprompt_api/model_cards.py` (new):
- `GET /{model:path}` endpoint (using `path` type to allow "/" in model names
  like `ollama/llama3`)
- Returns `FamilyCardOut` schema with resolved family, version, description,
  `is_small_variant` boolean, and `rules: list[TransformRuleOut]`
- Each rule includes `name`, `description`, `applies_to` ("all" or "small_only"),
  and `will_apply` boolean (reflects whether the rule fires for this specific model)
- Pure in-memory computation, zero DB queries, zero LLM calls
- Registered in `main.py` via `app.include_router(model_cards_router)`
- `tests/test_model_cards.py`: 13 tests covering all families, size detection,
  rule applicability, and public (no-auth) access

**Frontend** — `apps/web/src/routes/new-migration.tsx`:
- Added `useEffect` to fetch model card for each available model when
  `modelsQuery.data` loads
- Model picker now displays a "Model transform rules" info panel below each
  model's cost/capabilities badges
- Rules rendered with checkmark (✓) if will apply, strikethrough (—) if not
- Panel shows rule name and description in human-readable form
- On fetch error, card silently fails gracefully (no error shown, just no panel)
- `new-migration.test.tsx`: added mock for `getModelCard`, updated test suite
  to verify model card display appears with correct rules
- `src/lib/api.ts`: added `ModelCardInfo` and `TransformRuleInfo` types,
  `getModelCard(model)` function using URL-safe encoding for model names

**Tests**:
- `packages/core`: 264 passed, 21 skipped (unaffected — verified clean run)
- `apps/api`: 122 passed (109 baseline + 13 new)
- `apps/web`: 68 passed (65 baseline + 3 new), clean `tsc --noEmit`

**What a user sees**: in the migration wizard's "Target models" step, each model
card now has a small info section below the existing cost/capability badges,
titled "Model transform rules", listing which prompt transform rules apply to
this specific model — e.g. "xml_wrap_sections: Wrap recognized labeled sections
in XML tags" with a checkmark, and "terseify_if_small: Strip hedging... (only
for small models)" with a strikethrough for a large model. Clicking Continue
is unaffected; this is purely informational UI.

## Known constraints to respect while building the above

- **No Docker, no LiteLLM proxy, no external framework dependency** for
  either strategy — both call `reprompt_core.llm.client.complete()`
  directly, same as every other LLM-powered piece in this codebase.
- **`packages/core` stays headless** — zero FastAPI/DB imports. Progress
  and persistence are `apps/api`'s job via the `on_attempt` callback.
- **One stage's failure never aborts the run** — already true for
  "simple," must stay true for "prism" (wrap the Prism-specific
  critique/refine calls in their own try/except that degrades to
  "keep the un-refined variant" rather than failing the stage).
- **Budget is currently always a real, required positive number** —
  `Migration.budget` is `NOT NULL` and `BudgetTracker.budget_usd` requires
  `gt=0`; there is no "uncapped" mode in the code today. Making budget
  optional is a real, separate future item (see `docs/DEVELOPMENT.md`'s
  "Remaining plan") — it is *not* built yet, so don't assume
  `budget_usd=None` works anywhere in Phases 1-6 above; that was a
  mismatch an earlier build spec incorrectly assumed already existed.

## Phase 1 — Unified pipeline workspace [DONE — 2026-07-15]

A separate frontend-shape track, independent of the optimizer phase
numbering above (same relationship as "Phase D(a)" — parallel work, not a
continuation of Phase 6). Replaced the three previously-separate screens
(`/pipelines/$id` canvas, `/pipelines/$id/rubrics`,
`/pipelines/$id/migrations/new`) with one route,
`/pipelines/$id?tab=canvas|data|rubrics|migrations`, tab state living in the
URL search param. No changes to `packages/core`, the optimizer loop, judge,
mutator, or anything under `packages/core/src/reprompt_core/optimizer/`.

**Backend** — `apps/api/src/reprompt_api/pipelines.py`:
- New `PATCH /pipelines/{pipeline_id}` endpoint (`update_pipeline`, body
  `{name: str}`, same PATCH-whole-resource pattern as
  `settings.py`'s `update_workspace_settings`) — powers the workspace
  header's click-to-edit-inline pipeline name. Returns the updated
  `PipelineSummary`; 404s for an unknown pipeline, 422s for an empty name
  (`Field(min_length=1)`).
- `tests/test_pipelines.py`: 3 new tests (rename + persists, empty-name
  422, unknown-pipeline 404).

**Frontend**:
- `apps/web/src/router.tsx`: `pipelineWorkspaceRoute` replaces the old
  `pipelineDetailRoute`, with `validateSearch` defaulting `tab` to
  `"canvas"` for anything missing/unrecognized. The two old paths
  (`/pipelines/$id/rubrics`, `/pipelines/$id/migrations/new`) are now
  `beforeLoad`-only stub routes that `redirect()` into the matching
  `?tab=` on the new route — no bookmarked/shared link breaks.
- `apps/web/src/routes/pipeline-workspace.tsx` (new): persistent header
  (click-to-edit-inline name, `PATCH /pipelines/{id}` via
  `updatePipeline` in `api.ts`) + tab bar (Canvas · Data · Rubrics ·
  Migrations) + body switching on the `tab` search param. Also owns the
  canvas tab's stage-rubric drawer (`StageRubricDrawer`, built on the
  existing `apps/web/src/components/ui/drawer.tsx` — a vaul-based
  primitive that already existed, not built new): fetches
  `listRubrics(pipelineId)` and filters by `stage_id` (no new endpoint),
  shows format checks/content criteria plus an inline Approve button
  (reuses `approveRubric`), and a "View full rubric →" link that switches
  to the Rubrics tab and sets `window.location.hash = "rubric-${stage_id}"`.
- `apps/web/src/components/pipeline-canvas.tsx`: added optional
  `onNodeClick?: (stageId: number) => void` prop, wired to React Flow's own
  `onNodeClick`. Omitted (as before) by the read-only canvas embed inside
  `MigrationSuccessScreen` — only the workspace's Canvas tab passes it.
- `apps/web/src/components/rubric-review-panel.tsx` (new, extracted from
  the deleted `routes/rubric-review.tsx`): identical logic, `pipelineId`
  now arrives as a prop instead of `useParams` (no longer its own route),
  no more of its own `<AppShell>`/header/back-link. Each stage's `Card`
  now carries `id={rubric-${stage_id}}`, and a `useEffect` scrolls to
  `window.location.hash` once rubrics load — this is what makes the
  drawer's "View full rubric →" deep link land on the right card.
- `apps/web/src/components/new-migration-wizard.tsx` +
  `migration-success-screen.tsx` (new, extracted from the deleted
  `routes/new-migration.tsx`): the wizard now calls an `onCreated`
  callback instead of rendering the success screen itself; the success
  screen takes an `onBackToCanvas` callback (switches tabs) instead of
  navigating away, and initializes its `started` state from
  `migration.status !== "pending"` so a migration discovered already-running
  (not just one freshly created this session) shows its live run state
  immediately.
- `pipeline-workspace.tsx`'s `MigrationsTab` decides wizard vs. success
  screen by calling the pre-existing `GET /pipelines/{id}/migrations`
  (`listMigrations` — already existed, no new endpoint needed): empty list
  → wizard; otherwise → success screen for the most recent migration (or
  whichever one was just created this session, tracked in local state so
  there's no flicker waiting on the list query to refetch).
- Deleted: `routes/pipeline-detail.tsx`, `routes/rubric-review.tsx` (+
  test), `routes/new-migration.tsx` (+ test) — fully replaced by the above.

**Tests**:
- `apps/api`: 131 passed (128 baseline + 3 new for `PATCH /pipelines/{id}`).
- `apps/web`: 85 passed (77 baseline − 11 from the two deleted route test
  files + 19 new across `rubric-review-panel.test.tsx`,
  `new-migration-wizard.test.tsx`, and `pipeline-workspace.test.tsx`),
  clean `npx tsc --noEmit`, clean `npx vite build`.
- `packages/core`: untouched — confirmed via `git status` (no files under
  `packages/core` appear in the diff).

**What a user sees**: opening any pipeline now lands on one page with a
tab bar (Canvas · Data · Rubrics · Migrations) instead of three separate
screens reached by different buttons/links. Clicking the pipeline name in
the header turns it into an editable text field. Clicking a stage node on
the Canvas tab opens a right-side drawer with that stage's rubric and an
Approve button, without leaving the canvas; "View full rubric →" jumps to
the full editor on the Rubrics tab, scrolled to that exact stage. Any old
`/rubrics` or `/migrations/new` link still works, landing on the right tab.
The Data tab currently just says "Coming soon" (Phase 3, not part of this
work — see "Phase 3 — Data dashboard tab" below for what replaced it).

## Phase 3 — Data dashboard tab [DONE — 2026-07-16]

Another separate frontend-shape track, independent of the optimizer phase
numbering (same relationship as "Phase 1 — Unified pipeline workspace" and
"Phase D(a)" above — parallel work, not a continuation of Phase 6). Replaces
the Data tab's "Coming soon" placeholder from Phase 1 above with a real,
read-only spreadsheet-style browser over every `StageRecord` (input,
rendered prompt, output, tokens/cost/latency) for a pipeline. Built in a
separate worktree (`phase3-data-tab`) in parallel with another agent's
`phase2-*` work on multi-run support (`GET /pipelines/{id}/runs`) touching
`pipelines.py`/`pipeline-workspace.tsx` at the same time — kept additive/
narrow in both shared files (new router file instead of extending
`pipelines.py`; only the Data-tab `{tab === "data" && ...}` block changed in
`pipeline-workspace.tsx`) per that hand-merge constraint. No changes to
`packages/core`, the optimizer loop, or anything under
`packages/core/src/reprompt_core/optimizer/`.

**Deliberate scope cut, not forgotten**: only a **Stage filter** is built
here. A **Run filter/dropdown** is an explicit fast follow-on, blocked on
the parallel `phase2` work's `GET /pipelines/{id}/runs` endpoint landing
first (this phase was built without depending on that endpoint existing
yet, per this phase's own brief) — pick it up once that merges, don't
re-derive whether it's in scope. No text search box either (out of scope,
would need real indexing, not part of this phase's brief).

**Backend** — new `apps/api/src/reprompt_api/stage_records.py` (deliberately
its own file, not folded into the already-large, actively-edited-in-parallel
`pipelines.py`):
- `GET /pipelines/{pipeline_id}/stage-records?stage_id=&trace_id=&cursor=&limit=`
  → `{records: StageRecordOut[], next_cursor: int | None}`. Cursor
  pagination is the simplest possible form — `StageRecord.id > cursor ORDER
  BY id LIMIT limit` (+1 row fetched to know if a next page exists without
  a second COUNT query) — `id` is an autoincrementing surrogate with no
  updates/deletes on this table, so it's stable across pages. Always scoped
  to `pipeline_id` via a `StageRecord → Stage`/`Trace → BenchmarkSet` join
  (a `StageRecord` has no direct `pipeline_id` column); `stage_id`/
  `trace_id` are additional optional equality filters applied in the same
  query — all filtering is server-side SQL, never fetch-all-then-filter in
  Python. An unknown `pipeline_id` returns an empty `records` list (200),
  not a 404 — matches this router's read-only, listing-style contract
  (same as `GET /pipelines` never erroring on an empty result).
- `StageRecordOut`: `id, stage_id, stage_name, trace_id, input,
  rendered_prompt, output, tokens_in, tokens_out, latency_ms, cost` — no
  `tokens_thinking`/`documents`/`meta` (present on the `StageRecord` model
  but not needed by this browser's columns or drawer).
- Registered in `apps/api/src/reprompt_api/main.py` (one import + one
  `app.include_router(...)` line, additive).
- Tests: new `apps/api/tests/test_stage_records.py`, 6 cases — full-field
  response shape, cursor pagination walks every page with no
  overlap/gaps/duplicates across a 10-record set paginated 4-at-a-time,
  `stage_id` filter (cross-checked against the DAG's stage ids), `trace_id`
  filter, pipeline-scoping (no cross-pipeline leakage between two imported
  pipelines), unknown pipeline → empty list not an error.

**Frontend**:
- Added `@tanstack/react-virtual` (`apps/web/package.json`) — row
  virtualization for the record table, pairs with the already-used
  `@tanstack/react-query`.
- New `apps/web/src/components/data-table.tsx` (`DataTable`): toolbar with
  a Stage `<Select>` ("All stages" default, options from `getPipelineDag`
  under the same `["pipeline-dag", pipelineId]` query key the Canvas tab's
  `PipelineCanvas` already uses, so switching Canvas ↔ Data tabs in one
  session doesn't re-fetch the DAG) above a CSS-grid-based virtualized
  table (`useVirtualizer` over a `useInfiniteQuery` against
  `listStageRecords`, `getNextPageParam: (page) => page.next_cursor`, 50
  records/page, auto-fetches the next page once the last rendered virtual
  row nears the end of what's loaded). Columns: Trace (id) · Stage (badge)
  · Input/Rendered Prompt/Output (all truncated ~80 chars) · Tok in · Tok
  out · Cost · Latency. Whole row is a clickable `<button>` that opens a
  drawer with the full untruncated input (pretty-printed JSON), rendered
  prompt, output, and exact token/cost/latency figures — reuses the
  existing `apps/web/src/components/ui/drawer.tsx` primitive (the same
  vaul-based one Phase 1's stage-rubric drawer uses), not a second drawer
  implementation.
- `apps/web/src/lib/api.ts`: additive `StageRecordOut`/`StageRecordsPage`
  types + `listStageRecords()`, right before the existing "Trace format
  reference" section.
- `apps/web/src/routes/pipeline-workspace.tsx`: only the
  `{tab === "data" && ...}` block changed — now renders
  `<DataTable pipelineId={pid} />` instead of the "Coming soon" `<div>`;
  everything else in the file (header, tab bar, canvas/rubrics/migrations
  tabs, the stage-rubric drawer) is untouched, per the hand-merge
  constraint noted above.
- Read-only throughout, by design — no edit/approve affordance anywhere in
  this tab; that stays exclusive to the Rubrics tab.
- Tests: new `apps/web/src/components/data-table.test.tsx`, 4 cases — stage
  filter populated from the DAG fetch, empty state, row truncation +
  drawer shows full untruncated content on click, changing the stage
  filter re-fetches scoped to the selected `stage_id`. One jsdom-specific
  setup note worth knowing if this file is touched again: `jsdom` gives
  every element a `0` `offsetHeight`/`offsetWidth` by default (no real
  layout engine), which makes `useVirtualizer` think the viewport is
  zero-sized and render no rows at all — the test file stubs
  `HTMLElement.prototype.offsetHeight`/`offsetWidth` and a no-op
  `ResizeObserver` in a `beforeAll`, same spirit as
  `pipeline-workspace.test.tsx`'s existing note on `@xyflow/react` needing
  browser APIs jsdom doesn't provide.

**Verified**: `cd apps/api && uv run pytest -q` → **137 passed** (131
baseline + 6 new). `cd apps/web && pnpm exec tsc --noEmit` → clean.
`cd apps/web && pnpm test` → **89 passed** (85 baseline + 4 new), 11 test
files. `packages/core` untouched — confirmed via `git status` (only
`apps/api`/`apps/web` files plus this doc and `docs/TESTING.md` appear in
the diff).

**What a user sees**: `/pipelines/$id?tab=data` now shows a real table —
every benchmark trace's stage-by-stage input/prompt/output with token,
cost, and latency figures, filterable by stage, scrolling to load more
rows automatically, click any row for the full untruncated record in a
side drawer. No Run filter yet (see the deliberate-scope-cut note above).

**Where this leaves off**: the Run filter/dropdown is the next piece once
`phase2`'s `GET /pipelines/{id}/runs` lands and is merged in — add a second
`<Select>` next to the Stage one in `data-table.tsx`'s toolbar, threading a
`runId`/similar param through `listStageRecords`/`stage_records.py` the
same way `stage_id` is threaded today (the backend's cursor-pagination
query already has the right shape to add one more optional equality
filter). Nothing else about this phase is mid-flight.
