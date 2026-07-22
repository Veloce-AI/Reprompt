# Reprompt — Dev Tracker

Single source of truth for what's built across the whole project (M0-M5)
and, in detail, what's in progress and what's next on the M3 optimizer
specifically. Update this in the same commit as any change to the phases
below — mark `[x]` as you complete an item, and keep "Current state"
accurate so anyone (human or AI) can pick this up cold without
re-deriving context. Read `START_HERE.md` first if you haven't — it
points here plus the rest of the docs in reading order.

Last updated: 2026-07-22.

**Fix: Data tab table cell text overlap [DONE — 2026-07-22]**: Product owner
reported the Data tab's `DataTable` (`apps/web/src/components/data-table.tsx`,
"Phase 3 — Data dashboard tab" below) rendering stage names, input JSON
previews, and rendered-prompt text visually smashed together in cells,
illegible with real (long, dense) data. Root cause: the "Stage" column's
`<Badge variant="outline">` had no width constraint, truncation, or
`overflow-hidden` of its own, nor did its wrapping grid-cell `<div>`. CSS
Grid items default to `min-width: auto`, so a long, space-free stage name
(e.g. `extract_entities_and_classify_intent` — underscores aren't wrap
points) rendered at its full intrinsic width, overflowing the Stage
column's grid track directly into the Input column; since the `outline`
badge variant has no background fill, the overflow text painted right on
top of the Input cell's text instead of being clipped. The other cells
(Input/Rendered prompt/Output) already had Tailwind's `truncate` applied
directly and were unaffected — confirmed by reproducing with a real
Playwright render before touching any code (dense mock data modeled on the
screenshot: 30 rows, underscore-joined stage names, long prompts/JSON
input) and measuring the badge's bounding box extending ~140px past the
Input column's start. Fix (`data-table.tsx`): wrapping `<div>` gets
`min-w-0 overflow-hidden`; `Badge` gets `max-w-full truncate` — single-line
ellipsis within its own cell, row height (fixed 56px) unaffected since
everything now genuinely single-lines. Click-to-expand into the drawer for
full untruncated content (existing Phase 3 design) still works, re-verified
in the same spec. New permanent regression test:
`apps/web/e2e/data-table-density.spec.ts` (4 cases: no cell-to-cell overlap
with dense long-content data, consistent row height, drawer still shows
full content on click, no overlap at a narrow 900px viewport) — a real
Playwright/Chromium render, deliberately not a jsdom unit test, since jsdom
has no real layout engine and cannot reproduce CSS Grid track overflow (see
`saas-product-design` skill's precedent: a passing jsdom suite missed a
CSS flex-height bug the same way). Confirmed the new spec actually catches
the regression by reverting the fix and re-running (2 of 4 cases fail
without it, all 4 pass with it). `apps/web`: `tsc --noEmit` clean, `pnpm
test` **153 passed** (unchanged — no vitest-level behavior change), new
Playwright spec **4 passed**. No changes to `packages/core` or `apps/api`.

**Phase 5 — Contract Mining [DONE — 2026-07-22]**: NLI cross-encoder module (`packages/core/src/reprompt_core/nli.py`, lazy-load `cross-encoder/nli-deberta-v3-base` via `@lru_cache`, exact-match fallback when `sentence_transformers` absent). Bidirectional entailment clustering + Shannon entropy (`contract/cluster.py`). Two-axis contract mining (`contract/mine.py`): Axis A = existing trace outputs (no LLM calls), Axis B = K repeats at temperature 0.7 to measure noise floor. Structural invariant extraction: `required_keys` (key intersection), `enum_values` (cardinality ≤5), `regex` (common prefix ≥3 chars). `assertions` DB table + Alembic migration `b2c3d4e5f6a7`. Four API endpoints (list/mine/approve/retire) in `contracts.py` + router wired into `main.py`. `AssertionOut` + 4 client functions in `apps/web/src/lib/api.ts`. `ContractReviewPanel` component + "Contracts" workspace tab. Tests: `test_nli.py` (7), `test_contract_cluster.py` (14), `test_contract_mine.py` (10), `test_contracts.py` (10). `apps/api`: **201 passed** (191 → 201). `packages/core`: **326 passed, 21 skipped** (297 → 326). `apps/web`: **153 passed** unchanged.

**Fix 2 failing web tests [DONE — 2026-07-22]**: `migration-success-screen.test.tsx`'s
two "Results section" tests (`fetches and renders results once the migration is
terminal` / `does not fetch results while the migration is still running`) were
crashing with `TypeError: Cannot read properties of null (reading 'isServer')`
because `<MigrationSuccessScreen>` renders a `<Link>` from `@tanstack/react-router`
when `isTerminal` is true, and these tests never provided a `RouterProvider` context.
Root cause confirmed — `isTerminal` is true for both `"completed"` and `"failed"`
status fixtures; the `Link` calls `useRouter()` internally, which reads a context
that doesn't exist in plain `render(...)`. Fix: added a `vi.mock("@tanstack/react-router")`
at the top of the test file that spreads `vi.importActual` (so everything else — types,
hooks — is unchanged) and replaces `Link` with a passthrough fragment. App code is
correct and untouched. `apps/web`: **153 passed** (151 → 153, 0 failing) + clean
`tsc --noEmit`.

**Graph tab — Upgrade: model nodes + expandable call nodes [DONE — 2026-07-18]**
(commit `8edaa6e`): Upgraded the Graph tab (see entry directly below) with two
major additions: (1) **Model nodes** in a fixed right column with dashed edges
from each stage that uses that model — clicking a model node highlights/unhighlights
all connected stage nodes (blue border glow); (2) **Inline call nodes** — clicking
a stage node now expands its individual inference records as child nodes inline below
it (`CallGraphNode` shows tokens in/out, latency, cost, truncated I/O with "Show full
text" toggle). Records fetched lazily on first expand via `listStageRecords`,
cached for re-expand so a second click is instant. `apps/web/src/components/pipeline-graph.tsx`
only (261 lines changed, 226 replaced). No backend changes, no new test count update
in commit (fixtures-only changes in sibling test files from the Graph tab commit below
still apply).

**Graph tab — Obsidian-style pipeline visualization [DONE — 2026-07-18]**
(commit `dccf39b`): New fifth workspace tab (`"graph"`) added to `WORKSPACE_TABS`
in `pipeline-workspace.tsx`. New `PipelineGraph` component
(`apps/web/src/components/pipeline-graph.tsx`, 470 lines): richer stage nodes than
the Canvas tab (name, model badge, `trace_count`, avg tokens/latency, `total_cost_usd`,
"View inference calls" affordance), dagre layout reusing the same
`computeCanvasLayout` function and `["pipeline-dag", id]` React Query cache as the
Canvas tab (no second fetch when switching between tabs), orientation toggle (→/↓)
persisted per pipeline in localStorage under a separate key from Canvas tab's layout.
**ModelPanel** floating card (top-right): lists each unique model in the pipeline;
click one to highlight all stage nodes using that model with a blue border glow —
click again to deselect. **Backend**: `StageInfo` extended with `trace_count: int`
and `total_cost_usd: float | None` — both added to the `/dag` aggregation query
(`apps/api/src/reprompt_api/pipelines.py`) via `func.count`/`func.sum`; all
test fixtures updated with the two new fields. `docs/TESTING.md §3.3d` added for the
Graph tab walkthrough. `apps/web` test file fixture updates only (no new test count
change — pipeline-graph.tsx itself has no dedicated test file yet).

**Scorecard link + word-diff refinement [DONE — 2026-07-17]** (commit `a2f57cb`):
Added a "View full results →" `<Link>` button on `MigrationSuccessScreen` (the
Migrations tab's live run view) that navigates to `/pipelines/$pipelineId/migrations/$migrationId`
once a migration reaches a terminal state — previously the scorecard route existed
but nothing linked to it from the run screen. Also refined the word-diff display in
`migration-detail.tsx`: unchanged text rendered as plain `<span>`, deletions as
`line-through` in `text-parity-fail`, insertions in `text-parity-pass`. Frontend
only, no backend changes.

**Not started**: Phase 6 (final end-to-end manual verification).

**Phase 4 — Seam-level regression [DONE — 2026-07-22]**: After an upstream stage is migrated, every downstream stage (per `Stage.dependents` DAG) is re-validated: run the winning upstream prompt → substitute output into the downstream input under the upstream `source_id` key → run the original downstream prompt → score with det+embedding (no judge, same rationale as holdout). New `packages/core/src/reprompt_core/optimizer/seam.py` (`SeamExample`, `SeamInput`, `SeamResult`, `evaluate_seam`). New `SeamCheckResult` DB model + Alembic migration `f1c2d3e4a5b6`. `_run_seam_regression` wired into `optimizer_runner.py` after all stage loops. `GET /pipelines/{pid}/migrations/{mid}/seam-results` endpoint. "Seam checks" table in `migration-detail.tsx`. 7 core unit tests, 5 API tests. `apps/api`: **191 passed** (186 → 191). `packages/core`: **297 passed, 21 skipped** (290 → 297). `apps/web`: **153 passed** (unchanged).

**Phase 3 — Config export [DONE — 2026-07-22]**: `GET /pipelines/{pid}/migrations/{mid}/export` returns the winning migrated config as a JSON attachment keyed by `Stage.source_id`. "Download winning config" button on `migration-detail.tsx` — visible only in terminal state with ≥1 result, uses fetch+blob so cross-origin download works without auth complexity. 6 new API tests. `apps/api`: **186 passed** (180 → 186). `apps/web`: **153 passed** (unchanged).

**Phase 2 — M4 Holdout pass [DONE — 2026-07-22]**: Train/test split in `_build_stage_inputs` (optimizer_runner.py): prefers `Trace.is_holdout`-flagged records; auto-splits last record when none are explicit. `_evaluate_holdout` in core runs the winning prompt on withheld examples scoring with det+embedding only (no judge). `holdout_score` persisted on `Candidate` (new nullable Float column, migration `e4a1b8c7f203`). `StageResultOut.holdout_score` exposed in `GET .../results`. `migration-detail.tsx` shows a "Holdout" column (badge when set, dash when null). `apps/api`: **180 passed** (178 → 180). `apps/web`: **153 passed** (unchanged). `packages/core`: **290 passed, 21 skipped** (unchanged).

**Next phases planned (2026-07-22)**:
See `docs/PRISM_PHASES_PLAN.md` for the full per-phase spec (data model, API surface, core logic, tests, dependencies) — written by Opus against the PDF + live codebase. Build order: 5 → 8 → 6 → GEPA → 7.
- **Phase 5 — Automated contract mining**: NLI cross-encoder (DeBERTa-class) + semantic entropy clustering + two-axis sampling → auto-generated executable assertions.
- **Phase 8 — Executable assertions**: consuming Phase 5's assertion specs, backtracking, counterexample capture.
- **Phase 6 — Lessons file**: cross-migration model-family memory for the mutator.
- **GEPA backend**: third optimizer strategy branch.
- **Phase 7 — Governance plane**: end-to-end regression, promotion gate (staged→live), feature flags, rollback, drift daemon.

**Edit button for inline pipeline rename [DONE — 2026-07-16]**: Added an
explicit pencil/edit icon button next to the delete icon in the Pipelines
home list's action-icon area, triggering the same inline-rename behavior
that already existed via click-on-name. No new rename logic — reuses existing
`startEditingName` callback and state management. `apps/web` test suite:
2 new tests (edit button renders per pipeline row, clicking it triggers the
rename input with correct initial value), final: **99 passed** + clean
`tsc --noEmit`.

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
21 skipped` after. **Graph tab [DONE — 2026-07-18]**: new fifth workspace
tab (Obsidian-style interactive node graph), `PipelineGraph` component in
`apps/web/src/components/pipeline-graph.tsx` — richer stage nodes with
trace_count/cost/token stats, ModelPanel (click-to-highlight by model
family), model nodes in a right column with dashed edges, inline expandable
call nodes (individual inference records fetched lazily). Backend:
`StageInfo` now carries `trace_count` + `total_cost_usd`. **Fix 2 failing
tests [DONE — 2026-07-22]**: mocked `@tanstack/react-router`'s `Link` in
`migration-success-screen.test.tsx` so terminal-state tests no longer crash
on missing `RouterProvider` context — `apps/web` **153 passed, 0 failing**. **Phase D(a) — Model-card info in wizard [DONE —
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
**Branding/copy pass — Prism as self-evolving optimizer [DONE — 2026-07-16]**:
docs/UI copy only, no engine/schema changes — see the dated section below
for the full list of what changed and why.
**Phase C — Before/after prompt diff [DONE — 2026-07-16]**: once a
migration reaches a terminal state, the Migrations tab now shows each
stage's original prompt against the winning candidate's prompt as a word
diff, alongside which target model won and its composite score — see the
dated section below for the full design. Display-only, no new optimizer/
scoring logic. `apps/api` 154 passed (147 + 7 new), `apps/web` 105 passed
(93 + 12 new) + clean typecheck, `packages/core` untouched.
**Fix judge/mutator self-grading bias [DONE — 2026-07-16]**: extends the
"Model auto-selection for rubric generation" phase's exact `select_model()`
pattern to the two optimizer call sites it was deliberately not wired into
yet — `judge_model` no longer falls back to `target_models[0]`, and
`mutator_model` (previously not passed to `run_optimizer` at all, so it
silently fell back to the target model inside `packages/core`) is now
explicitly selected too, both from the workspace's own available models,
never from the migration's target models — see the dated section below for
the full design, plus a real schema gap (`judge_model` wasn't actually an
accepted field on `TargetModelConfig`, so the override was dead code) and a
circular-import fix found along the way. `apps/api` 165 passed (160 + 5
new), `packages/core` untouched (305 passed, 2 skipped).
**Product owner report investigated — "Canvas has nothing in it, Settings
is empty, no rename" [FIXED — 2026-07-16]**: two of the three complaints
didn't reproduce against current code (Settings' "Configured models" card
and the pipeline-workspace Canvas route both work when actually driven in
a browser); the third was a real CSS layout bug that made the Canvas
tab's DAG genuinely invisible (correct data, zero-height viewport) despite
looking fine in unit tests — see the dated section below for the full
root-cause trace and fix. Inline rename was also added to the Pipelines
home list itself (previously only in the workspace header, one click
deeper than where the report said to look). `apps/web` 117 passed
(unchanged - jsdom doesn't do real CSS layout, so this bug and its fix are
both invisible to Vitest either way) + clean `tsc --noEmit`, `apps/api`
165 passed (untouched), `packages/core` untouched.
**Canvas tab live migration overlay [DONE — 2026-07-16]**: the main Canvas
tab (`pipeline-workspace.tsx`, the default landing tab) now shows the same
live per-stage coloring/pulsing/sub-step signal the Migrations tab's
embedded canvas already had, whenever a migration is running in the
background — previously it always rendered a static, uncolored DAG
regardless — see the dated section below for the full design (a shared
`useMigrationStatusPoll` hook, a lightweight conditional list-check, and a
"Migration running" pill). `apps/web` 121 passed (117 + 4 new) + clean
`tsc --noEmit`, `apps/api`/`packages/core` untouched.
**Settings empty-page perception fix + System models visibility [DONE —
2026-07-16]**: re-investigated the product owner's "Settings is empty"
report (a follow-up task, separate from the "Canvas has nothing in it"
investigation directly above, which had already concluded "Configured
models" renders fine on the happy path but hadn't tested unauthenticated/
zero-key states or crash resilience) — none of the three real states
(unauthenticated, signed-in with zero BYOK keys, signed-in with a key)
actually render blank when driven live via Playwright against real dev
servers, but the app had **zero React error boundaries anywhere**, so any
uncaught render exception on any route (e.g. a hand-merge introducing a
frontend/backend shape mismatch — a real, live risk given this project's
several-worktrees-then-hand-merge workflow) fell through to the router's
bare, unstyled default error text with no nav or branding, which is
visually indistinguishable from a blank page in a quick screenshot. Fixed
by adding a root-level `errorComponent` (new
`apps/web/src/components/route-error-fallback.tsx`, wired in
`router.tsx`) that renders inside the app's own `AppShell` (nav stays
usable) instead, plus defensive optional-chaining in
`ConfiguredModelsCard`'s `model_card` usage so the one realistic shape-drift
case doesn't even reach the boundary. Separately, made judge/mutator/
rubric-generation auto-selection (fixed in code by commit `128bc94`, per
that commit's own note "No UI surfaces the effective/overridden judge or
mutator model yet") visible: new read-only "System models" card in
Settings, backed by a new `GET /settings/system-models` endpoint that calls
the exact same `select_model()` apps/api's real run paths use. See the
dated section below for the full design, root-cause trace, and the
Playwright evidence (including a deliberately-injected malformed API
response proving the crash-to-fallback path actually works). `apps/api`
**168 passed** (165 + 3 new), `apps/web` **119 passed** (117 + 2 new) +
clean `tsc --noEmit`, `packages/core` untouched (**286 passed, 21
skipped**, this worktree's own environment-dependent skip count — see
Phase 1's note on why that number varies by machine).
**Per-stage target-model overrides + migration CTA [DONE — 2026-07-16]**:
`TargetModelConfig` gains optional `stage_overrides: {stage_id: [models]}`
— pin specific model(s) per stage, other stages keep the global `models`
list (`optimizer_runner._get_target_models_for_stage` resolves override
first). Wizard gains an "Advanced: customize per stage" disclosure
(pre-filled with the global selection, only diffs submitted), and the
Migrations tab shows a prominent "+ Start a migration" CTA when none
exists. Note: the agent building this hit a session limit before writing
docs/committing — code was verified green and committed by the main
session; `docs/TESTING.md` click-path for the per-stage section is still
owed (next session: add it, the feature itself is fully tested — apps/api
177 passed incl. 9 new, apps/web 130 passed incl. 8 new on merged master).
**"Settings STILL empty" — definitive root cause: ghost dev server serving
pre-fix code [SOLVED — 2026-07-16]**: the owner's report after the fixes
merged was real but was never a code bug — the browser was talking to an
orphaned uvicorn worker (spawned 12:41, before the merge) that survived its
parent's death and kept serving the pre-fix backend; netstat blamed the
dead parent's PID (unkillable "ghost"), but the orphan itself was findable
and killable via WMI command-line match. Proven by the stale process's own
`/openapi.json`: 27 paths, **no `/settings/system-models`** — vs 29 paths
including it after a real restart. Port 8000 was recovered (no port change
needed). New `scripts/dev-restart.ps1` does the reliable
kill-by-commandline → verify-ports-free → fresh-start → serving-current-code
health check in one command; `docs/TESTING.md` §2 now leads with it. See
the dated section below.
**Fix overlapping stage node text [DONE — 2026-07-17, superseded same day
— see the dagre entry directly below]**: the product owner
reported stage nodes' text overlapping on the Canvas — reproduced live with
Playwright (import `packages/core/tests/fixtures/mixed_12stage.json`,
12 stages, long names/models, across both layout presets and both
orientations). Root cause was inter-node spacing, not internal card text
(the name/model text already truncate with a `title` tooltip): the grid and
layered layout algorithms in `apps/web/src/lib/canvas-layout.ts` used one
`CROSS_GAP` (190px, tuned for a card's ~150-175px height) for the cross axis
regardless of orientation, but in **vertical** orientation the cross axis
runs left-to-right, where cards are 224px wide (`w-56`) — so cards packed
only 190px apart overlapped directly, borders and text colliding across
node boundaries. Fixed by splitting into `CROSS_GAP_HORIZONTAL` (190,
unchanged) and `CROSS_GAP_VERTICAL` (280, matching the width-tuned
`MAIN_GAP`), picked via a new `crossGapFor(orientation)` helper; horizontal
orientation's layout is byte-for-byte unchanged. `canvas-layout.test.ts`'s
two "swaps axes" tests updated to reflect the now-intentionally-different
cross gap per orientation instead of asserting a literal axis swap.
`apps/web` **149 passed** (unchanged count — no new tests added, existing
coverage updated in place) + clean `tsc --noEmit`. `apps/api`/
`packages/core` untouched. **Superseded**: the very same day, the whole
gap-tuning approach this fix lived in (`CROSS_GAP_HORIZONTAL`/
`CROSS_GAP_VERTICAL` in the hand-rolled grid/layered algorithm) was
replaced wholesale by the dagre rewrite immediately below — a real
graph-layout library computes spacing now, these constants no longer exist
in the codebase. Kept as a historical record of the bug/fix reasoning, not
because the code still matches this description.

**Canvas: dagre-based auto layout [DONE — 2026-07-17]**: replaced the
hand-rolled grid/layered position math in `pipeline-canvas.tsx`/
`lib/canvas-layout.ts` with `@dagrejs/dagre`-computed positions — the real
fix for the product owner's report that a large, real pipeline (35 stages)
still rendered outside the viewport despite the grid/layered presets and
refit work — see the dated section below for the full design, the two real
bugs found and fixed along the way (React Flow's default `minZoom` silently
capping how far a very tall/wide graph could shrink to fit, and a refit
race against a live-migration overlay that resizes the canvas after first
paint), and the Playwright evidence. `apps/web` 151 passed (149 baseline +
2 net new in `canvas-layout.test.ts`) + clean `tsc --noEmit`, new
`e2e/canvas-layout.spec.ts` (2 tests, real Chromium render) both green.
`packages/core`/`apps/api` untouched.
**Corrected same day — see "Canvas: legible zoom floor + spacing picker"
below**: this entry's own verification used a WIDE mock DAG (6 layers, two
12-nodes-wide) and its "fits entirely on screen" claim didn't hold for the
product owner's actual pipeline shape (TALL/narrow, ~35 single-node layers)
— `fitView`'s `minZoom: 0.05` let it shrink a long chain into illegible
slivers to satisfy "everything visible," which is not the same thing as
"legible." The position math (dagre itself) was and remains correct; only
the zoom-floor/fit philosophy was wrong. Left in place below as the
accurate record of what dagre itself fixed (real position computation from
graph edges) — the entry below is what fixed how the canvas *uses* those
positions.
**Canvas: legible zoom floor + spacing picker [DONE — 2026-07-17]**: fixed
the real bug — `fitView`'s near-zero `minZoom` (0.05) let a tall/narrow
pipeline (the product owner's actual ~35-stage shape, mostly one node per
layer) shrink into illegible slivers to satisfy "everything visible."
Raised the floor to 0.5 (empirically confirmed legible via screenshot, not
guessed), let an oversized graph pan instead of shrinking further, and
brought back a real "Compact"/"Spacious" spacing picker (dagre
`nodesep`/`ranksep`) next to the existing orientation toggle, both
persisted per pipeline. See the dated section below for the full
root-cause chain and verification (six new/rewritten Playwright e2e tests
against the real reported shape, not just the previous round's wide mock).
`apps/web` 153 passed (151 + 2 net new) + clean `tsc --noEmit`.
`packages/core`/`apps/api` untouched.
**Not started**: Phase 6 (final end-to-end manual verification).

**Note for future sessions/developers**: each phase above updates
`DEV_TRACKER.md` itself as part of "done" — same discipline applies to
`docs/TESTING.md` for anything screen/behavior-facing. Don't create a
separate status doc; just flag completion inline in whichever `.md` file
the change actually touches.

## Ghost dev-server root cause — "Settings STILL empty" [SOLVED — 2026-07-16]

The product owner reported Settings still empty *after* the fixes
(root error boundary, System models card, `GET /settings/system-models`)
were verifiably merged to master. Root cause found and proven — not a code
bug, and not "works for me":

**Evidence trail (all commands run 2026-07-16 ~22:30):**
1. `netstat -ano` showed port 8000 LISTENING, owned by PID **32756** — but
   `Get-Process -Id 32756` says that PID **does not exist**. The classic
   ghost socket this repo's `stop.sh` header already documents.
2. The ghost still served requests: `GET http://localhost:8000/openapi.json`
   returned **27 paths with no `/settings/system-models`** — i.e. the
   owner's browser was hitting a **pre-fix backend**. That's the smoking
   gun: the frontend (Vite, live process, serves current disk files) called
   the new endpoint, got 404s/stale shapes, and Settings looked broken
   regardless of what was merged.
3. WMI (`Get-CimInstance Win32_Process`) found the ghost's real body: PID
   25076, `python.exe -c "from multiprocessing.spawn import spawn_main;
   spawn_main(parent_pid=32756, ...)"`, created **12:41** — spawned by a
   long-dead uvicorn reloader parent (32756, the PID netstat still blamed)
   *before* the fixes landed. A second orphan (PID 12664, parent 34948) and
   a leftover worktree vite were also found and killed.
4. `Stop-Process` on the orphan (by its real PID, found via command line —
   never via netstat's PID column) freed port 8000 immediately. **No port
   change was needed** — 8000/5173 stay the dev ports.
5. Fresh servers: `/openapi.json` now returns **29 paths including
   `/settings/system-models`**, and an authenticated request (dev
   magic-link flow → `Authorization: Bearer <session_token>`) to
   `GET /settings/system-models` returns real data — all three purposes
   (`rubric_generation`/`judge`/`mutator`) with a selected model.

**Mechanism (why this keeps happening):** uvicorn `--reload` on Windows
spawns its worker via `multiprocessing`. Killing/closing the parent does
not cascade to the child; the orphan keeps the port and the *old code*
loaded in memory. Later "restarts" fail to bind (or die silently), and the
browser keeps talking to the orphan — so every fix ever merged looks like
it didn't ship. netstat reporting the dead parent's PID makes the orphan
look unkillable, which is why previous sessions concluded "ghost socket,
gave up" (see the "Product owner report" section below).

**Permanent fix:** new `scripts/dev-restart.ps1` — kills all dev-server
processes by WMI command-line match (uvicorn reloader, its
`multiprocessing.spawn` orphans, this repo's vite; deliberately never
matches vitest or pytest), verifies both ports are genuinely free (with an
explicit orphan hunt if a ghost listener remains), starts fresh servers via
the same terminal-window pattern as `start.sh`, then polls until the API
provably serves a **current-code** route (`/settings/system-models` in the
openapi spec) — so "restarted but still stale" can never silently pass
again. Script was tested end-to-end twice this session (first run caught
two script bugs: its vite pattern also matched a running vitest process,
and a 30s health timeout was too tight when another `uv` process holds the
venv lock — both fixed). `docs/TESTING.md` §2 now tells the owner to always
restart via this script and hard-refresh after.

## Canvas: dagre-based auto layout [DONE — 2026-07-17]

Product owner report: the DAG canvas still goes outside the viewport for a
real, large pipeline (35 stages), despite the "grid/layered layout presets,
orientation toggle, refit" work (commit `3151574` — never got its own
DEV_TRACKER.md entry; this section supersedes that gap too, since most of
what it built is replaced here). Root cause per that task's own hypothesis,
confirmed: hand-computed node x/y positions (`lib/canvas-layout.ts`'s old
`computeGridLayout`/`computeLayeredLayout`) don't generalize to arbitrary
DAG shapes — a preset tuned for a mostly-sequential chain (snake-wrap into
rows of 5) or classic per-layer columns (wrapping at a fixed per-layer line
count) both fall over on a shape neither hand-tuned constant anticipated.

**The fix — real graph layout, not hand-rolled math.** Added
`@dagrejs/dagre` (the actively-maintained fork; the old `dagre` package is
unmaintained) as an `apps/web` dependency — the standard pairing with React
Flow for hierarchical DAG layout. `lib/canvas-layout.ts`'s
`computeCanvasLayout(layers, edges, choice)` now builds a dagre graph from
the pipeline's real stage ids and dependency edges (previously only `layers`
was used — position math never looked at the actual edges, just topological
layer membership), sets `rankdir: "LR"` or `"TB"` from the existing
orientation toggle (dagre supports this natively — no custom orientation
math needed anymore, `oriented()`'s axis-swap helper is gone), runs
`dagre.layout()`, and maps each node's center-based output position to
React Flow's top-left-corner convention. `CanvasLayoutChoice` dropped its
`preset` field entirely (`"grid" | "layered"` is gone) — dagre computes
correct, non-overlapping spacing directly from the graph structure, so the
old presets' only job (working around the hand-rolled math's failure modes)
no longer exists. `pipeline-canvas.tsx`'s toolbar lost the preset
segmented-control; only the horizontal/vertical orientation toggle remains
(a real, user-meaningful choice — a wide pipeline can read better
top-to-bottom — so it stayed). `loadCanvasLayoutChoice` still parses a
stale `{preset: ...}` value from localStorage without erroring (just
ignores that field), so an existing user's saved orientation isn't lost by
this change.

**Two real bugs found and fixed along the way, both by actually rendering a
35-node pipeline in a real browser (Playwright) rather than trusting unit
tests** — same "jsdom doesn't do real CSS layout/paint" caution the
"Product owner report" section above already learned the hard way for a
different bug class:

1. **React Flow's default `minZoom` (0.5) silently capped how far a large
   graph could shrink to fit.** A wide dagre rank (many parallel stages at
   the same dependency depth — exactly the shape a real branchy pipeline
   produces, and exactly what this task's own verification stress-tests
   with a 12-node-wide layer) can need a zoom well below 0.5 to fit the
   whole graph in the viewport at once; `fitView` was silently clamping at
   0.5 and leaving the excess off-screen — "fitView ran" but the result
   still overflowed, the literal bug being investigated. Fixed by setting
   both the `<ReactFlow minZoom={0.05}>` instance-wide prop and a matching
   `minZoom` in the shared `FIT_VIEW_OPTIONS` object passed to every
   `fitView()` call (React Flow's `fitViewport` reads the call-site option
   ahead of the instance prop, so both need setting for belt-and-suspenders
   — confirmed by reading `@xyflow/system`'s own `fitViewport`/
   `getViewportForBounds` source, not guessed).
2. **A refit race against the live-migration overlay.** The Canvas tab's
   "Migration running" pill (`pipeline-workspace.tsx`'s `CanvasTabContent`,
   see "Canvas tab live migration overlay" below) mounts as a sibling
   *above* `<PipelineCanvas>` once a running migration is found — a real
   layout change (the canvas's available height shrinks) that arrives
   asynchronously, on a later render than `PipelineCanvas`'s own mount
   (the migrations-list/status queries resolve after the first paint), so
   `RefitOnChange`'s existing `nodeCount`/`layout`-only dependency list
   never re-fit for it — a live-migration-view load could leave the last
   couple of nodes poking out from under the now-shorter viewport. Fixed by
   adding a third `hasLiveOverlay` (`stageStates !== undefined`) dependency
   to `RefitOnChange`'s effect — deliberately keyed on *presence*, not
   `stageStates`'s contents, since that changes every 2s poll while running
   and refitting that often would yank a user's pan/zoom during the live
   view (an existing, deliberate constraint from the "Canvas tab live
   migration overlay" work, preserved here). Separately (found via the same
   Playwright run, a ~12px/563px discrepancy that a 4px tolerance in the
   test's own overlap-margin check caught): `RefitOnChange`'s single
   `requestAnimationFrame` occasionally fired a frame before
   ResizeObserver's own measurement of a node whose height depends on live
   run state (the "running" node's extra sub-step line) had landed — React
   Flow has no explicit width/height on these nodes, so `fitView`'s bounds
   are only as good as that measurement. Fixed with a second nested
   `requestAnimationFrame` before calling `fitView` (ResizeObserver
   callbacks land after a frame's layout/style pass, one frame later than a
   same-frame rAF can see them — a documented general ordering gotcha, not
   specific to this codebase).

**Verification** — real Chromium, not jsdom, per the task's own "must be
real, with evidence" requirement: new `apps/web/e2e/canvas-layout.spec.ts`,
entirely network-mocked (no live API server or auth needed — the workspace
route has no auth gate, and every fetch it makes is intercepted) against a
constructed 35-stage DAG across 6 layers, including two 12-node-wide layers
(the shape that actually exercises the `minZoom` bug above — the real
pipeline's own shape, "31 layers, 29 single-node," happens not to trigger
it). Two tests: (1) zero node-vs-node overlap and zero nodes outside the
`.react-flow` viewport's own bounding box after `fitView`, asserted in both
horizontal and vertical orientation; (2) the same layout guarantee holds
with a mocked running migration's `stage_states`/`progress_substep` layered
on top, plus asserts the pre-existing live-coloring/beam-flow-animation
behavior is genuinely unchanged (a done node's state dot, the running
node's sub-step label, `edge-beam`/`edge-passed` edge classes) — this task's
"preserve everything else exactly" constraint, checked, not assumed. Both
passed against this worktree's own dev server (run on an isolated port via
a throwaway local Playwright config, not committed — the shared
`playwright.config.ts`'s `webServer` targets port 5173 with
`reuseExistingServer: true`, which in this session would have silently
attached to the *main checkout's* already-running dev server instead of
this worktree's code, since another agent had it up in parallel).
`apps/web/src/lib/canvas-layout.test.ts` was rewritten for the new dagre
function (old grid/layered-specific assertions replaced with: zero overlaps
for a long chain and for a wide layer, dependent stages ordered along the
flow axis, orientation axis-swap, an isolated/no-edge node, malformed-edge
resilience, persistence round-trip including the stale-`preset`-field
tolerance) — **151 passed** (149 baseline + 2 net new), clean
`tsc --noEmit`. `packages/core`/`apps/api` untouched (confirmed via `git
status` — only `apps/web/`, `pnpm-lock.yaml`, and this doc/`docs/TESTING.md`
changed).

**What a user actually sees**: any pipeline's Canvas tab, including a large
branchy one, now always lays out with real, non-overlapping spacing and
fits entirely on screen after load — the preset picker is gone from the
toolbar (one less decision, dagre's default is simply good), the
orientation toggle still works exactly as before, and live migration
coloring/animation is pixel-for-pixel the same as before this change, only
the node positions underneath it differ.

**Note (2026-07-17, later the same day): this "fits entirely on screen"
claim did not hold for the product owner's real pipeline shape** — see
"Canvas: legible zoom floor + spacing picker" below, which supersedes the
claim (not the position math, which was and remains correct).

## Canvas: legible zoom floor + spacing picker [DONE — 2026-07-17]

Third round of canvas fixes this session. The product owner shared a real
screenshot of `/pipelines/$id?tab=canvas` for an actual pipeline ("Renamed
via curl test", 35 stages): every node rendered as a tiny, illegible
sliver — no text readable anywhere — on a mostly-linear vertical column (a
handful of 3-wide branch points, everything else one node per row), zoomed
out so far the whole canvas read as a smudge. The previous two rounds this
session ("Fix overlapping stage node text" and "Canvas: dagre-based auto
layout", both above) each claimed success via screenshots that turned out
not to match what the product owner actually sees — this round's
verification was built specifically to not repeat that.

**Root cause, confirmed not guessed**: the dagre entry above fixed real
node-overlap/position computation (genuinely correct, kept as-is), but its
own verification used a WIDE mock DAG (6 layers, two 12-nodes-wide) — a
fundamentally different shape from the real pipeline, which is TALL and
NARROW (~30-38 stages, almost all single-node layers). `fitView`'s job as
configured was "shrink the whole graph until it fits the viewport," with
`minZoom` lowered all the way to 0.05 specifically so a very wide graph
could shrink enough to fit. That same "shrink until it fits" logic applied
to a long vertical (or horizontal) chain shrinks every node long before the
chain actually "fits" a normal-height viewport — confirmed by rendering the
real shape in a real browser (Playwright) with the pre-fix code: node
bounding boxes measured ~20x12px, transform `scale(0.075)`–`scale(0.1)`,
no text legible in the resulting screenshot at all. "Everything visible, no
scroll" and "legible" are different goals, and the canvas was optimizing
for the wrong one.

**The fix — a legible zoom floor, spacing as a real choice, and panning
instead of over-shrinking**, all in `apps/web/src/`:

1. **`components/pipeline-canvas.tsx`**: `CANVAS_MIN_ZOOM` raised from 0.05
   to **0.5** (React Flow's own conventional default floor) — applied to
   both the `<ReactFlow minZoom>` instance prop and `FIT_VIEW_OPTIONS`
   (both still needed, same belt-and-suspenders reasoning as before: React
   Flow's `fitViewport` reads the call-site option ahead of the instance
   prop). This value was **found empirically, not guessed**: rendered the
   real ~38-stage tall/narrow shape at 0.6, then 0.5, screenshotted both,
   and visually confirmed 0.5 keeps a stage-node.tsx card's name, model
   badge, and token/latency line fully readable (0.05's ~20px-wide boxes
   were not). When the full graph doesn't fit the viewport at this zoom,
   `fitView` now simply clamps to the floor and centers on the graph's
   overall bounds — the excess is off-screen but reachable by panning
   (React Flow's native drag-to-pan, no new code) or the corner zoom
   controls, never by shrinking nodes further. Confirmed React Flow's own
   "Zoom Out" control button disables itself once `minZoom` is reached
   (Playwright-verified, not assumed) — a user genuinely cannot zoom a node
   into illegibility via the UI anymore.
2. **`lib/canvas-layout.ts`**: brought back real layout flexibility — not
   the old fake grid/layered preset picker (removed by the dagre entry
   above for good reason: it only existed to work around hand-rolled
   math's own failure modes), but a genuinely different dagre
   configuration choice. New `CanvasSpacing = "compact" | "spacious"`
   field on `CanvasLayoutChoice`, mapped to a `SPACING` table of real
   `nodesep`/`ranksep` pairs (`compact`: 48/96, unchanged from before this
   field existed; `spacious`: 96/176, roughly double) fed into
   `dagre.setGraph()`. `loadCanvasLayoutChoice`/`saveCanvasLayoutChoice`
   extended to persist it per pipeline (localStorage) alongside the
   existing orientation, defaulting a pre-existing saved value with no
   `spacing` field to `"compact"` rather than treating it as corrupt (same
   forward-compatible tolerance the function already had for the older
   dagre migration's stale `preset` field).
3. **`components/pipeline-canvas.tsx`**'s `CanvasLayoutToolbar`: a second
   `SegmentedGroup` ("Compact"/"Spacious") added next to the existing
   orientation toggle, same visual treatment (`role="group"`,
   `aria-pressed`, existing `--beam`-accent selected state) — no new
   component, no new tokens.

**Verification — driven per the `webapp-testing`/`saas-product-design`
skills' explicit "verify by driving the real app, not the diff" discipline,
against the shape that actually matters**:

- Built a mock DAG modeled directly on the product owner's screenshot: ~38
  stages across ~30 layers, almost all single-node, with four 3-wide
  branch-and-immediately-merge points — not the wide 12-nodes-per-layer
  shape the previous round's own test used.
- Rendered it pre-fix (Playwright, real Chromium) and confirmed the
  reported bug first: node boxes ~17-22px wide, `scale(0.076)`-`(0.099)`,
  screenshotted and visually inspected — genuinely illegible, matching the
  product owner's report exactly.
- Iterated the zoom-floor value empirically (0.6 → 0.5) by screenshotting
  and reading the actual rendered text each time, not by picking a number
  and asserting a bounding box passed some threshold.
- New `apps/web/e2e/canvas-layout.spec.ts` (rewritten, not just extended)
  — six tests: (1) the tall/narrow shape renders every node at a legible
  size with zero overlap in both orientations, and the zoom actually sits
  at the floor (proof the floor is enforced, not incidentally satisfied);
  (2) the Compact/Spacious picker measurably widens the real DOM gap
  between two connected nodes (not a synthetic dagre-output check — an
  actual `boundingBox()` delta) in both orientations, staying legible and
  overlap-free throughout; (3) orientation *and* spacing both survive a
  real page reload; (4) the zoom controls can zoom in past the floor and
  the Zoom Out button disables at the floor rather than continuing to
  shrink; (5)-(6) the original wide 35-stage/12-node-wide-layer shape from
  the previous round still lays out with zero overlaps and legible nodes,
  including the running-migration live-coloring/beam-flow-edge checks —
  its old "fits entirely inside the viewport" assertion was **deliberately
  removed**, since asserting that was the bug this round fixes, not a
  guarantee worth keeping.
- `apps/web/src/lib/canvas-layout.test.ts`: added a test asserting
  "spacious" produces a strictly larger real rank gap *and* sibling gap
  than "compact" (exercising both `ranksep` and `nodesep`, not just one),
  plus persistence coverage for the new `spacing` field including the
  backward-compatible default for a pre-existing saved value. **153
  passed** (151 baseline + 2 net new), clean `tsc --noEmit`.
- `packages/core`/`apps/api` untouched (confirmed via `git status` — only
  `apps/web/canvas-layout.ts`, `pipeline-canvas.tsx`,
  `canvas-layout.test.ts`, `e2e/canvas-layout.spec.ts`, and this doc/
  `docs/TESTING.md` changed).

**Honest legibility assessment, not overclaimed**: at the default zoom
(0.5) on a ~38-node mostly-linear pipeline, stage names, model badges, and
the token/latency line are all clearly readable in a screenshot — verified
by actually reading the rendered text, not just checking the bounding box
stayed non-zero. Text is smaller than at zoom 1 (expected — it's a 30+ node
diagram on one screen) but not blurred-past-reading the way the pre-fix
~0.08 zoom was. A very large pipeline (50+ stages) will still require
panning to see every node at this floor — that is the intended trade-off
per this task's own framing (real diagram tools don't force-fit everything
either), not a residual bug.

## Canvas tab live migration overlay [DONE — 2026-07-16]

Product owner complaint: "the canvas is static, it should be dynamic like
a graph that should also be able to reflect what is going on when the
pipeline is running." Root cause: live migration status (per-stage
running/done/failed coloring, pulsing nodes, sub-step labels) only ever
rendered inside the Migrations tab's own embedded
`<PipelineCanvas stageStates={...} runningSubstep={...} />` (in
`migration-success-screen.tsx`). The main Canvas tab
(`pipeline-workspace.tsx`, the default landing tab) always rendered a
static, uncolored DAG regardless of whether a migration was actively
running in the background — the two views of the exact same
`<PipelineCanvas>` component just never shared a poll.

**Shared hook, not duplicated polling logic**: extracted
`apps/web/src/hooks/use-migration-status-poll.ts`'s
`useMigrationStatusPoll(pipelineId, migrationId, options?)` out of
`migration-success-screen.tsx`'s inline `statusQuery` `useQuery` block
(same `["migration-status", pipelineId, migrationId]` queryKey,
`getMigrationStatus` queryFn, and `refetchInterval` — 2000ms while
`status === "running"`, `false` otherwise — byte-for-byte the same
convention, just parameterized by `enabled`/`initialData` instead of
hardcoded to `started`/`migration`). Low-risk extraction (a `useQuery` call
wrapped 1:1, no behavior change) rather than the "risky refactor" the task
brief flagged as an acceptable reason to duplicate instead — chose to
extract. `migration-success-screen.tsx` now calls
`useMigrationStatusPoll(pid, migration.id, { enabled: started, initialData:
started ? migration : undefined })` in place of its old inline block;
`getMigrationStatus` import removed from that file (no longer called
directly there).

**Canvas tab wiring** (`apps/web/src/routes/pipeline-workspace.tsx`, new
`CanvasTabContent`, mounted only inside the existing
`{tab === "canvas" && (...)}` conditional — so both polls below exist only
while a user is actually on this tab, never in the background on another
tab):
- A lightweight `listMigrations(pipelineId)` check, `refetchInterval:
  5000` (a deliberately lighter cadence than the live-status poll — this
  one only exists to notice a migration starting/finishing while parked on
  the Canvas tab). Reuses the exact same `["migrations", pipelineId]`
  query key `MigrationsTab` (same file) already uses, so switching to/from
  the Migrations tab is a cache hit, not a second fetch, in the common
  case.
- `.find((m) => m.status === "running")` → if found, hands its id to
  `useMigrationStatusPoll` (the same shared hook above), which takes over
  with the real 2s live-coloring poll — its `stage_states`/
  `progress_substep` feed straight into the Canvas tab's existing
  `<PipelineCanvas>` (same component, same optional props it already
  accepted from the Migrations-tab usage — no prop-shape changes needed,
  confirmed via `pipeline-canvas.tsx`'s `PipelineCanvasProps`).
- If nothing is running: `useMigrationStatusPoll` is `enabled: false` (no
  status poll at all), `<PipelineCanvas>` gets no `stageStates`/
  `runningSubstep` props — pixel-identical to the pre-existing static
  Canvas tab. Conditional, not always-on, per the task brief.
- Small UI nicety (task brief's point 4): a pill — "Migration running —
  view in Migrations →" with a pulsing dot (reusing the same
  `animate-ping` dot pattern `stage-node.tsx`'s running-node pulse already
  established) — renders above the canvas whenever `liveStatus?.status ===
  "running"`, clicking it calls the same `goToTab("migrations")` the tab
  bar itself uses. Rendered as a plain sibling of `<PipelineCanvas>` inside
  a JSX fragment (not a new wrapping `<div>`) specifically to avoid
  reintroducing the flex-height bug from the "Product owner report" section
  below — the outer `flex flex-1 flex-col overflow-y-auto` wrapper and
  `<PipelineCanvas>`'s own `h-full min-h-[480px] flex-1` sizing chain are
  untouched; the pill just takes its natural content height as a
  non-`flex-1` sibling above it.

**Tests**: new `apps/web/src/routes/pipeline-workspace.canvas-live.test.tsx`
(4 new) — its own `<PipelineCanvas>` mock echoes `stageStates`/
`runningSubstep` back as text (unlike the main `pipeline-workspace.test.tsx`
suite's bare-button stub, which only cares about tab/drawer wiring) so the
live props are actually assertable: stays static with no `stageStates`/
badge/`getMigrationStatus` call when no migration is running; colors the
canvas and shows the badge when one is; never polls or renders the overlay
at all while parked on a non-Canvas tab; clicking the badge navigates to
the Migrations tab. Existing `pipeline-workspace.test.tsx` needed one fix,
not a workaround: its shared `beforeEach` never gave `listMigrations` a
default resolved value (only `MigrationsTab` called it before, and
individual tests that cared already set their own), so once
`CanvasTabContent` became a second caller, tests that start on the Canvas
tab hit React Query's "query function returned undefined" console error via
the bare `vi.fn()` mock — fixed by adding
`vi.mocked(listMigrations).mockResolvedValue([])` to that file's
`beforeEach` (tests needing a specific list still override it themselves,
unchanged). `apps/web`: **121 passed** (117 baseline + 4 new), clean
`tsc --noEmit`. `apps/api`/`packages/core` untouched (confirmed via `git
status` — only files under `apps/web/src/` and this doc changed).

**What a user actually sees**: start a migration from the Migrations tab,
then switch to the Canvas tab while it's still running — the DAG there now
pulses/colors live exactly like the Migrations tab's own view, with a
small "Migration running" pill making it obvious why nodes are suddenly
colored and offering a one-click way back to the full run screen. Open the
Canvas tab with nothing running (or after a migration finishes) and it's
exactly the static view it always was, with no background polling.

## Settings empty-page perception fix + System models visibility [DONE — 2026-07-16]

Two separate but related asks: (1) the product owner reported a genuinely
empty `/settings` screenshot, despite the "Canvas has nothing in it,
Settings is empty, no rename" investigation directly below already having
found "Configured models" renders fine — that investigation only drove the
happy path (signed in, in a browser, no crash injection), not
unauthenticated/zero-key states or render-crash resilience; (2)
`select_model()`-based judge/mutator/rubric-generation auto-selection was
fixed in code (`128bc94`, "Fix judge/mutator self-grading bias") but that
phase's own closing note flagged "No UI surfaces the effective/overridden
judge or mutator model yet" as a known gap — hard to trust a backend-only
fix with zero visibility.

**Investigation — driven live, not read from code.** Set up this worktree
from scratch (`scripts/setup.sh`) and ran the API/web dev servers on
isolated ports (`:8010`/`:5183`, not the main checkout's `:8000`/`:5173`,
per this task's "don't touch the main checkout" constraint — required a
temporary local-only CORS allowlist addition and `REPROMPT_WEB_BASE_URL`
override to make the dev magic-link flow work cross-port; both reverted
before committing, not part of the diff). Wrote a throwaway Playwright
driver script (not committed — ad hoc verification, not a permanent spec)
covering all three real states end-to-end:

1. **Unauthenticated** — `/settings` shows "Sign in to manage your
   workspace settings." with a sign-in link. Not blank. Screenshot
   confirms a clean, small, centered message (this alone could misread as
   "empty" in a careless glance, but it's the deliberate, correct
   unauthenticated state, not a bug).
2. **Signed in, zero BYOK keys** — full page renders: Workspace card, "No
   API keys configured yet.", Configured models showing the 2 no-key-
   required Ollama models, zero console errors. `GET /settings/workspace`,
   `/settings/api-keys`, `/settings/models` all return 200 with real data.
   Not blank.
3. **Signed in, with a BYOK key** — same, now also showing `gpt-4o`/
   `gpt-4o-mini` under the new provider group. Not blank.

**None of the three real states reproduce a blank page** — consistent with
(and extending) the prior investigation's conclusion. So the actual gap
had to be something none of the three states exercises: a crash, not a
data state. Grepped the whole frontend for `ErrorBoundary` /
`componentDidCatch` / `getDerivedStateFromError` — **zero results**. No
route in `router.tsx` set an `errorComponent` either. Proved this
concretely with `page.route()`: intercepted `GET /settings/models` and
injected a malformed entry (`model_card: null`, simulating a version-skewed
frontend/backend pair — a real risk in a codebase built across several
parallel worktrees that get hand-merged, exactly the working model this
very task runs under). Result: `ConfiguredModelsCard` threw
`Cannot read properties of null (reading 'family')`, and the **entire page
— including the nav sidebar — unmounted**, replaced by TanStack Router's
default `CatchBoundary` fallback: an unstyled "Something went wrong! /
Hide Error / [stack trace]" with no branding, no nav, mostly whitespace.
That is visually indistinguishable from "the page is empty" in a quick
screenshot, and it's reachable from *any* uncaught render exception on
*any* route in the app, not just this one triggered case — a real,
reproducible mechanism for the report, even though the specific data
condition that would trigger it in production wasn't identified (every
field `ConfiguredModelOut`/`SystemModelOut` return is currently
non-optional on the Pydantic side, so this exact null wouldn't happen
today without a schema regression — but "a regression in a fast-moving
multi-worktree repo causes a shape mismatch" is exactly the class of
failure this project's own workflow makes newly plausible, not a
hypothetical).

**Fix — two layers**:
1. **App-wide crash fallback**: new `apps/web/src/components/route-error-fallback.tsx`
   (`RouteErrorFallback`), wired as `rootRoute`'s `errorComponent` in
   `router.tsx`. Renders inside the app's own `AppShell` (nav rail stays
   live/clickable — a crash on one screen no longer stops the user
   navigating elsewhere) with a styled Card: "Something went wrong", the
   real error message in a mono block, "Try again" (calls TanStack
   Router's `reset()` to re-render the failed route without a full page
   reload) and "Go to Pipelines". Re-ran the same injected-crash script
   after this change: page body now reads "Reprompt / Pipelines / Trace
   format / Settings / Something went wrong / ... / Try again / Go to
   Pipelines" — nav intact, message legible, screenshot confirms it reads
   as a real (if broken) part of the app, not a blank/dead page. This is a
   root-level fix (covers every route, not just Settings) since the
   underlying gap — zero error boundaries — was never Settings-specific.
2. **Defensive guard in the one card most tied to the original report**:
   `ConfiguredModelsCard`'s `model.model_card` access is now
   optional-chained with a graceful "Prompt family info unavailable for
   this model." fallback per-model, and `rules` defaults to `[]` — so the
   specific null-`model_card` case no longer even reaches the error
   boundary; a genuinely deeper anomaly (tested by injecting
   `rules: "not-an-array"`, which the optional-chaining can't sensibly
   guard against) still correctly falls through to the new boundary rather
   than crashing silently. `SystemModelsCard`'s purpose-label lookups
   (`SYSTEM_MODEL_PURPOSE_LABEL`/`_DESCRIPTION`) also fall back to the raw
   purpose string rather than rendering `undefined` for an unrecognized
   purpose.

**System models visibility** — the second ask, addressed alongside since
both land in Settings and share the "make an already-correct backend
decision visible" framing:
- **`apps/api/src/reprompt_api/settings.py`**: new `GET
  /settings/system-models` → `SystemModelOut[]`
  (`{purpose, selected_model, reason}`), one entry per
  `reprompt_core.llm.model_select.Purpose` (`rubric_generation`/`judge`/
  `mutator`). Calls the exact same `get_available_models(db, workspace)` +
  `select_model(purpose, available)` pair `optimizer_runner.py`/
  `rubrics.py` already call for a real run — no new selection logic, per
  the task's "don't touch `select_model()`, just call it" constraint.
  `reason` is always `"best available"` today: this view is deliberately
  workspace-scoped, not migration-scoped, since a specific migration's own
  `target_model_config.judge_model`/`mutator_model` override (added in
  `128bc94`) only makes sense in the context of that migration's own
  `target_models` — there's no single "current migration" at the
  Settings level to read an override from, so this always shows the
  no-override auto-select path (i.e. what a *new* migration would get by
  default). **Considered and deliberately not built**: a workspace-level
  default override (would need a new `Workspace` column) — per the task's
  own "keep this scoped, read-only is the priority, don't over-build it"
  instruction, and because it would sit awkwardly between "always
  auto-select" and "set it per migration" without a clear use case driving
  it yet.
- **`apps/web`**: `lib/api.ts` gained `SystemModel`/`SystemModelPurpose` +
  `listSystemModels()`. `routes/settings.tsx` gained `SystemModelsCard`,
  rendered below the existing "Configured models" card — a table of
  Purpose / Model / Why, with a human-readable label + one-line description
  per purpose, and a closing note that a specific migration can still
  override the judge/mutator model when created. Empty state
  ("No system models to show yet.") for symmetry with the other cards,
  even though `available_models` is never actually empty in practice (the
  no-key-required local models guarantee at least a tier-3 fallback).
- **Tests**: `apps/api/tests/test_settings.py` (3 new) —
  `test_list_system_models_covers_all_three_purposes` (all three purposes
  present, every entry names a real non-empty model/reason even with zero
  BYOK keys), `test_list_system_models_selects_a_stronger_model_once_a_byok_key_is_added`
  (zero keys → local Ollama fallback for all three purposes; adding an
  Anthropic key upgrades all three to `claude-sonnet-4-5` — proves the
  live upgrade path, not just a static response), `test_list_system_models_only_reflects_this_workspaces_keys`
  (workspace isolation, same pattern as the existing `/settings/models`
  isolation test). Also added `/settings/system-models` to the existing
  "all endpoints reject unauthenticated requests" test.
  `apps/web/src/routes/settings.test.tsx` (2 new): renders all three
  purposes with their models/reasons when populated; shows the empty state
  when the list is empty. Both new suites required adding
  `listSystemModels: vi.fn()` to the existing `vi.mock("@/lib/api", ...)`
  block and a default `mockResolvedValue([])` in `beforeEach`, same pattern
  every other query in this test file already follows.

**Verified**: `cd apps/api && uv run pytest -q` → **168 passed** (165
baseline + 3 new). `cd apps/web && npx tsc --noEmit` → clean; `npx vitest
run` → **119 passed** (117 baseline + 2 new), 15 test files.
`cd packages/core && uv run pytest -q` → **286 passed, 21 skipped**,
confirmed unchanged and untouched (`git status` shows no `packages/core`
files in the diff at any point in this session) — this worktree's own
environment-dependent skip count (see Phase 1's own note on why 21 vs. 2
skips varies by machine, unrelated to this work). Full click-path to
re-verify by hand: sign in → Settings → scroll past "Configured models" →
"System models" card shows Rubric generation / Judge / Mutator rows, each
with a real model name and "best available"; to see the crash-fallback,
temporarily break any Settings card's data access and reload — the nav
stays live and a styled "Something went wrong" card appears instead of a
bare error line.

## Product owner report — "Canvas has nothing in it, Settings is empty, no rename" [FIXED — 2026-07-16]

Product owner was looking at the live Pipelines home page (real, populated
table - matches this file's own description of it) and raised three
complaints. Killed stale dev-server processes first (Windows `netstat -ano`
+ PowerShell `Stop-Process`, `kill -0`/`kill %N` don't work reliably here -
see `feedback_gitbash_kill0_unreliable.md`; one port-8000 process turned
out to be an unkillable-but-healthy Windows networking ghost socket with no
matching PID in `Get-Process`/`tasklist`/`Get-CimInstance` - verified it
was actually still the correct live API via `GET /openapi.json` rather than
fight it further), then actually drove the app with Playwright (already a
project dependency for `apps/web/e2e/`, `playwright.config.ts` has
`reuseExistingServer: true` so it attached to the already-running dev
server) via the dev magic-link flow, rather than assuming from reading code
or repeating "just hard refresh."

**1. "Nothing is in Settings" - did not reproduce.** `/settings`'s
"Configured models" card (built in "Settings page — real
model-configuration content [DONE — 2026-07-15]" below) rendered fully
with real data (the curated no-key-required Ollama models, cost, prompt
family, transform-rule pills) on a fresh sign-in, zero console errors,
screenshot confirms it visually matches the rest of the app's Card-based
design language. Not a regression to fix.

**2. "The canvas and all, nothing is there" - REAL bug, found and fixed.**
Clicking a pipeline row on the home list correctly routed to
`/pipelines/$id?tab=canvas` (`apps/web/src/routes/home.tsx`'s row
`onClick`) and the DOM/React Query data were both genuinely present (35
stage nodes with real names/models/token counts in `body.innerText`,
`.react-flow__node` count = 35, 0 console errors) - but a screenshot of the
same page showed a **completely blank canvas**. Root-caused via
`page.evaluate()` measuring `getBoundingClientRect`/`getComputedStyle` down
the DOM chain in `apps/web/src/routes/pipeline-workspace.tsx`: the Canvas
tab's content wrapper (`<div className="flex-1 overflow-y-auto">`, line
~169) is a plain block div, not `display:flex` - so `PipelineCanvas`'s own
wrapper (`h-full min-h-[480px] flex-1`, `pipeline-canvas.tsx` line 98) only
ever got its height from `min-height` (480px), never from `h-full`. Per the
CSS spec, a `min-height`-derived size does not count as an "explicitly
specified" (definite) height for descendants' `height:100%` resolution -
so `@xyflow/react`'s own `.react-flow` root (inline `height:100%`, and all
its meaningful children are `position:absolute` so it has no in-flow
content to size itself by either) collapsed to computed `height:0px`.
React Flow then laid out and positioned all 35 nodes correctly *inside a
zero-height viewport* - real data, real DOM, invisible paint. This is
exactly the failure mode unit tests can't catch (jsdom doesn't run real
CSS layout - `pipeline-workspace.test.tsx`'s existing "renders the
pipeline canvas" test passed before, during, and after this fix, because
it only asserts the DOM node exists, never that it has nonzero height).

Confirmed via the working sibling case first
(`migration-success-screen.tsx` line 174 wraps the same `PipelineCanvas` in
a div with an *explicit* `h-[420px]`, not `min-h-`, and that one has always
rendered correctly) before changing anything, then fixed at the actual
root of the chain rather than patching every intermediate layer: changed
`pipeline-workspace.tsx`'s outer workspace container from
`"flex h-full min-h-[calc(100vh-1px)] flex-col"` to
`"flex h-[calc(100vh-1px)] flex-col"` (an explicit height, still
viewport-relative so no behavior change in the normal case, but now a
spec-definite size that correctly propagates through every `flex-1`/
`h-full` step below it) and made the Canvas tab's content wrapper a real
flex container (`"flex-1 overflow-y-auto"` → `"flex flex-1 flex-col
overflow-y-auto"`) so `PipelineCanvas`'s own `flex-1` (previously inert -
its parent wasn't `display:flex`) actually takes effect. Re-measured after
the fix: `.react-flow` height went from `0px` to `603.4px`, screenshot
confirms all 35 stage nodes now paint with names/models/token counts and
working pan/zoom controls. Single child per tab (the four tab branches are
mutually exclusive) so this doesn't change layout for Data/Rubrics/
Migrations.

**3. "Edit pipeline name is not there" - real gap, not a bug (expected,
called out in the task brief).** Inline rename already existed in the
pipeline workspace header (`pipeline-workspace.tsx`'s `startEditingName`/
`saveName`, click-to-edit pattern) but not on the Pipelines home list the
owner was actually looking at. Added the identical pattern to
`apps/web/src/routes/home.tsx`: click a row's name → editable `Input` →
`Enter`/blur saves via the same `PATCH /pipelines/{id}`
(`updatePipeline`) the workspace already uses → optimistic
`queryClient.setQueryData` update, same pattern the row's own delete
button already uses on this screen. `event.stopPropagation()` on the name
button/input so clicking to rename doesn't also trigger the row's
navigate-into-workspace `onClick`. Verified round-trip live (rename →
confirm persisted in the table → rename back), no accidental navigation.

**Verification**: `apps/web` typecheck clean, `117 passed` (unchanged from
baseline - confirmed via `git stash` before/after comparison, since this
CSS bug and its fix are both invisible to jsdom-based Vitest either way).
`apps/api` `165 passed` (untouched - this was a frontend-only investigation
and fix). `packages/core` untouched. No schema/API changes.

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

## Branding/copy pass — Prism as self-evolving optimizer [DONE — 2026-07-16]

Copy/docs-only pass positioning Prism as **"a self-evolving prompt
optimizer"** — no engine changes, no schema changes, no new aggregation.
The framing is deliberate and bounded: Prism's existing mutate →
judge-aware critique → refine (×3 rounds) → sweep → select loop genuinely
revises its own output based on its own critique within a single run,
which earns "self-evolving" honestly. The one thing actively avoided
everywhere this copy touches: never implying cross-migration
memory/learning that doesn't exist — no "gets smarter over time," no
"learns from your migrations," no "remembers what worked." Nothing
persists across separate migrations today; every place below that adds
"self-evolving" language also says so explicitly.

1. **UI label**: there is no user-facing strategy picker anywhere in
   `apps/web/src/` — `OPTIMIZER_STRATEGY` is a backend env var
   (`apps/api/.env.example`), not a per-migration UI choice, confirmed by
   grepping `apps/web/src` for `strategy`/`prism` before making any change
   (only hit: `ParityBeam`'s unrelated `prismPosition` prop). The one
   place Prism's activity is actually visible to a user is the Migrations
   tab's live view (`MigrationSuccessScreen`), so that's where the label
   went: a subtitle line — "Optimizing with **Prism** — a self-evolving
   prompt optimizer" — directly above `<MigrationRunBar>`, shown once a
   migration has started. `apps/web/src/components/migration-success-screen.tsx`
   (new subtitle block just before the existing `<MigrationRunBar>` render,
   ~line 145).
2. **"How Prism works" explainer**: new, self-contained
   `apps/web/src/components/prism-explainer.tsx` — owns its own
   open/close state, so it's a one-line drop-in (`<PrismExplainer />`).
   Trigger is a small "How Prism works" text link next to the new
   subtitle in `MigrationSuccessScreen`; opens the existing `Drawer`
   primitives (`components/ui/drawer.tsx`, the same ones
   `StageReasoningDrawer` in the same file already uses) with two short,
   factual paragraphs describing the real loop (judge-aware critique, up
   to 3 refine rounds, budget-bounded, per-stage, plateau early-stop) plus
   one explicit paragraph on what Prism doesn't do (no cross-migration
   memory). `migration-success-screen.tsx`'s own layout wasn't
   restructured — only the new subtitle/trigger row was added above the
   pre-existing `<MigrationRunBar>` call.
3. **Docs**: `README.md`'s "Two search methods" table — Prism's row
   reframed with "evolves the prompt through several rounds before
   locking in a winner," plus a new sentence directly under the table:
   "**Prism evolves within one migration, not across migrations**."
   `DEV_TRACKER.md`'s own "Why two strategies, and why the name 'Prism'"
   section (below) — reframed the same way, plus an explicit
   per-migration/not-cross-migration sentence so the absence of
   cross-run memory is never later mistaken for a regression.

**Tests**: `apps/web/src/components/prism-explainer.test.tsx` — 3 new
(renders the trigger with the panel closed by default; opens on click and
shows the self-evolving explanation including the no-cross-migration-memory
line; closes on Escape). Ran against this worktree's own clean baseline
first (`apps/web` **93 passed**, 12 test files, clean `tsc --noEmit`).
Final: **96 passed** (93 + 3 new), 13 test files, clean `tsc --noEmit`;
`migration-success-screen.test.tsx`'s existing 3 tests still pass unchanged
alongside the new subtitle/trigger row. `packages/core` and `apps/api`
untouched (confirmed via `git status` — only `DEV_TRACKER.md`,
`README.md`, and files under `apps/web/src/` changed), so their suites
weren't re-run.

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
rebuilt in-house rather than depending on their package. We describe it
externally as **a self-evolving prompt optimizer**: within a single run
it genuinely revises its own output based on its own critique — mutate,
get judge-aware critique (real reasoning from the AI judge, not just a
score), refine against that specific feedback for up to 3 rounds per
stage, sweep, select the best-scoring candidate — which is honest
framing for what's actually built, not a stretch. **This is per-migration,
not cross-migration**: each migration evolves its own prompt from
scratch, and Prism doesn't yet carry learnings between separate
migrations — there's no persistence of "what worked" across runs today,
so this should never be described as "getting smarter over time" or
"learning from your migrations." Built entirely on the engine's own
already-universal `llm/client.py`, so it works with any provider
(OpenAI, Anthropic, Gemini, self-hosted Ollama/vLLM/etc.) uniformly,
with no proxy and no extra dependency. Named to match the existing
brand — the logo and `ParityBeam` UI component already use a
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

## Pipeline delete [DONE — 2026-07-16]

Another separate frontend-shape track, independent of the optimizer phase
numbering (same relationship as "Phase 1 — Unified pipeline workspace" and
"Phase 3 — Data dashboard tab" above). Closes out the **Pipeline CRUD**
backlog item: rename already existed (Phase 1's `PATCH /pipelines/{id}`,
the workspace header's click-to-edit-inline name) and naming-at-import
already worked (a pipeline's name always comes from the imported trace
file's `pipeline.name` — see `pipelines.py`'s `import_pipeline` /
`ImportResult.name`, unchanged here); the only missing piece was delete.
All three are now built. No changes to `packages/core`, the optimizer
loop, or anything under `packages/core/src/reprompt_core/optimizer/`.

**Backend** — `apps/api/src/reprompt_api/pipelines.py`:
- New `DELETE /pipelines/{pipeline_id}` (`delete_pipeline`) — 404 if the
  pipeline doesn't exist, else a single `db.delete(pipeline); db.commit()`
  and `204 No Content`. Same 404-if-missing / 204-on-success shape as
  `settings.py`'s `delete_api_key`.
- **Cascade check done before writing this, not assumed**: read every FK
  in `models.py` that points at `Pipeline` (`Stage.pipeline_id`,
  `BenchmarkSet.pipeline_id`, `Migration.pipeline_id`) and one level
  further down (`StageRecord.stage_id`/`trace_id`, `Rubric.stage_id`,
  `Candidate.migration_id`/`stage_id`, `Trace.benchmark_set_id`). Every
  one of them already carries both `ForeignKey(..., ondelete="CASCADE")`
  *and* the matching ORM `relationship(..., cascade="all, delete-orphan")`
  on the parent side (`Pipeline.stages`/`.benchmark_sets`/`.migrations`,
  `Stage.stage_records`/`.rubric`/`.candidates`, `BenchmarkSet.traces`,
  `Trace.stage_records`, `Migration.candidates`) — confirmed "cascades
  already work" was accurate, not stale. A single `db.delete(pipeline)`
  is therefore sufficient; no manual child-deletion-in-order code needed.
  (Note for later: SQLite FK enforcement itself is off in `db.py` — no
  `PRAGMA foreign_keys=ON` — so the DB-level `ondelete="CASCADE"` is inert
  on SQLite today; the ORM-level `cascade="all, delete-orphan"` is what
  actually does the work in tests/dev, and would keep working unchanged
  if this project moves to Postgres later where the DB-level cascade
  would also kick in.)
- `tests/test_pipelines.py`: 2 new tests —
  `test_delete_pipeline_removes_pipeline_and_cascades_to_children` (seeds
  one row in every child table — rubric, migration, candidate, on top of
  the diamond import's existing stages/benchmark_set/traces/stage_records
  — deletes the pipeline, then asserts all seven tables are empty
  afterward, not just `pipelines`) and
  `test_delete_pipeline_for_unknown_pipeline_returns_404`.

**Frontend**:
- `apps/web/src/lib/api.ts`: new `deletePipeline(pipelineId)` — same
  bare-`fetch`-with-manual-error-handling shape as the existing
  `deleteApiKey` (not the shared `request<T>()` helper, since that always
  calls `.json()` and a `204 No Content` response has no body).
- `apps/web/src/routes/home.tsx`: each pipeline row in the Pipelines home
  table gets a trash-icon `Button` (`lucide-react`'s `Trash2`,
  `variant="ghost" size="icon"`, `aria-label="Delete {name}"`). Click
  handler calls `event.stopPropagation()` first (the row itself navigates
  to the pipeline on click) then `window.confirm(...)` naming the
  pipeline and warning that stages/rubrics/runs/migrations are all
  permanently removed — only on confirm does it call the new
  `deletePipeline` mutation. **`window.confirm` was a deliberate choice,
  not a placeholder**: no modal/dialog primitive exists anywhere in
  `apps/web/src/components/ui/` yet (checked before building this), and
  adding one purely to gate a single destructive button would be more new
  surface area than the task warrants — it still satisfies the real
  requirement (an explicit confirm step, not a bare click). On success,
  invalidates the `["pipelines"]` query so the row disappears without a
  full reload; on failure, shows the error inline above the table (same
  `ApiError`-aware pattern as the page's existing load-error banner).
- Tests: new `apps/web/src/routes/home.test.tsx`, 5 cases — delete button
  present per row, cancelling the confirm dialog makes no request,
  confirming calls `deletePipeline` with the right id and the row is gone
  after refetch, clicking delete never navigates into the pipeline (stays
  on `/`), and a failed delete surfaces the error message.

**Verified**: `cd apps/api && uv run pytest -q` → **149 passed** (147
baseline + 2 new). `cd apps/web && pnpm exec tsc --noEmit` → clean.
`cd apps/web && pnpm test` → **98 passed** (93 baseline + 5 new), 13 test
files. `packages/core` untouched — confirmed via `git status` (only
`apps/api/src/reprompt_api/pipelines.py`, `apps/api/tests/test_pipelines.py`,
`apps/web/src/lib/api.ts`, `apps/web/src/routes/home.tsx` (modified) and
`apps/web/src/routes/home.test.tsx` (new) appear in the diff, plus this
doc and `docs/TESTING.md`).

**What a user sees**: on the Pipelines home screen, each row now has a
trash icon at the right edge. Clicking it (without navigating into the
pipeline, even though the row itself is normally a click-to-open target)
pops a browser confirm dialog naming the pipeline and warning the delete
is permanent; confirming removes it — and everything under it — for good,
and it disappears from the list immediately.

**Pipeline CRUD backlog item: fully closed.** Create (import), Read
(list/DAG/data tab), Update (rename), Delete are all built and tested —
nothing left open under this item.

## Phase C — Before/after prompt diff [DONE — 2026-07-16]

Another separate, narrow display-only track (parallel work in its own
worktree, `phase-c`, off the same base commit as `branding`,
`pipeline-delete`, `model-auto-select`, all needing hand-merging
afterward) — not a continuation of Phase 6. The gap: `Candidate.
prompt_variant` (every attempt tried) and `Stage.prompt_template` (the
original) already existed and were fully populated by the M3 optimizer
wiring, but nothing ever showed a user the *winning* prompt next to the
original — a reviewer had no way to see exactly what the optimizer changed
without reading raw `Candidate` rows out of the DB directly.

**No "winner" flag exists on `Candidate`** — checked `selection.py`
(`packages/core/src/reprompt_core/selection.py`) and `optimizer_runner.py`'s
`on_attempt` closure first: `select_best_candidate` picks a winner
in-memory per stage per target-model run and only its `StageAttempt` (via
`on_attempt`) gets persisted as a `Candidate` row alongside every other
non-winning attempt from the sweep — none of them carry a boolean marking
which one actually won that stage's optimization. What *is* persisted:
`Candidate.scores` is the full `{"deterministic":, "judge":, "embedding_sim":,
"final":, "judge_disagreement":, "judge_low_confidence":}` dict `packages/
core`'s `run_sweep_for_stage` builds (see `reprompt_core.optimizer.loop`
around its `StageAttempt(...)` construction) — `scores["final"]` is the
same composite score `select_best_candidate` itself uses to rank
candidates. So "the winner" is recomputed at read time: highest
`scores["final"]` among a stage's `Candidate` rows for this migration,
ties broken by row-insertion order (`Candidate.id` ascending) — the same
tie-break rule `select_best_candidate` already uses (Python `max()` keeps
the first element attaining the max), so a recomputed "winner" here always
agrees with what the optimizer itself picked, not a second competing
notion of "best." No schema change, no Alembic migration.

**Backend** — `apps/api/src/reprompt_api/migrations.py`:
- New `GET /pipelines/{pipeline_id}/migrations/{migration_id}/results` →
  `list[StageResultOut]`, `StageResultOut = {stage_id, stage_name,
  original_prompt, winning_prompt, winning_model, score}`.
- **Not gated on `Migration.status` being terminal** (the task's own
  "your call, document which" — documented here and in the endpoint's own
  docstring): a stage only appears in the response once it has at least
  one `Candidate` row for `(migration_id, stage_id)`. For a `pending`
  migration that's an empty list; for `running`, whichever stages have
  already finished at least one attempt; for a terminal state, the full
  per-stage set. This matches every other read endpoint in this router's
  own "return what's available" contract (e.g. `list_migrations` on an
  empty pipeline) rather than adding a second, endpoint-specific
  not-ready-yet error shape. The frontend still only *fetches* this once
  terminal (see below) since there's nothing worth showing/polling for
  mid-run, but the endpoint itself doesn't enforce that.
- `scores.get("final") or 0.0` guards a `Candidate` row saved without a
  `"final"` key (older/partial data, or a directly-seeded test row) —
  treated as the worst possible score rather than raising, covered by
  `test_results_treats_missing_final_score_as_zero`.
- Tests: 7 new cases in `apps/api/tests/test_migrations.py` — empty before
  any candidate, picks the highest-`final`-score candidate across multiple
  target models for one stage (and only includes stages with >=1
  candidate), missing `"final"` key treated as zero, available for a
  still-`running` migration, no cross-migration candidate leakage on the
  same pipeline/stage, unknown migration/pipeline → 404.

**Frontend**:
- No diff library added — `package.json` untouched (checked first per the
  task's own "keep it minimal" framing; prompts are short enough that a
  hand-rolled diff is simpler than vetting/adding a dependency, and it
  avoids a `package.json`/lockfile merge conflict with the three sibling
  worktrees). New `apps/web/src/lib/text-diff.ts`: pure `diffWords(before,
  after) -> DiffOp[]` — whitespace-preserving tokenization + a standard
  O(n·m) LCS table (prompt-sized inputs, not documents — this is plenty
  fast) — `DiffOp = {type: "equal"|"insert"|"delete", text: string}`,
  consecutive same-type tokens coalesced so the renderer emits one `<span>`
  per changed run, not one per word. Zero React/DOM — unit-tested on its
  own in `apps/web/src/lib/text-diff.test.ts` (9 cases: identity, isolated
  single-word change, pure insertion/deletion including empty-string
  before/after, and two round-trip checks that concatenating equal+insert
  reproduces `after` exactly and equal+delete reproduces `before` exactly).
- `apps/web/src/components/migration-success-screen.tsx`: added a
  `resultsQuery` (`getMigrationResults`, `enabled: isTerminal`) and, when
  terminal, a **"Results — before / after prompts"** section below the
  existing Activity log — one card per stage with its name, winning
  model, score, and the word diff rendered inline (deletions
  strikethrough in `parity-fail`, insertions highlighted in `parity-pass`
  — reusing the existing design-token colors the pass/fail `Badge`
  variants already use, not new arbitrary Tailwind colors). Added as two
  new functions (`StageResultsSection`, `StageResultCard`) at the bottom
  of the file, same convention this file already established with
  `ActivityLogList`/`StageReasoningDrawer` (Phase B) — one file, several
  small presentational components, not a new file per component.
- `apps/web/src/lib/api.ts`: additive `StageResultOut` type +
  `getMigrationResults()`, placed right after `getMigrationStatus`.
- Tests: 3 new cases in `apps/web/src/components/migration-success-
  screen.test.tsx` — fetches and renders once terminal (diff spans present,
  winning model/score shown, correct `pipelineId`/`migrationId` args),
  does **not** fetch while still `running`, empty-state message when no
  stage has a candidate yet. Needed a `beforeEach(() =>
  vi.mocked(getMigrationResults).mockReset())` scoped to just this
  `describe` block — the file's mocks aren't reset globally between tests
  (no `beforeEach` at file scope), so a mock call count asserted in one
  test would otherwise leak into the next; same pattern `data-table.test.
  tsx`/`new-migration-wizard.test.tsx`/`rubric-review-panel.test.tsx`
  already use for their own `beforeEach`, just scoped narrower here since
  the file's *other* (Phase B) tests don't need resetting.

**Verified**: `cd apps/api && uv run pytest -q` → **154 passed** (147
baseline + 7 new). `cd apps/web && npx tsc --noEmit` → clean. `cd apps/web
&& npx vitest run` → **105 passed** (93 baseline + 12 new: 9 in
`text-diff.test.ts`, 3 in `migration-success-screen.test.tsx`), 13 test
files. `packages/core` untouched and `package.json`/lockfile untouched —
confirmed via `git status` (only `apps/api/src/reprompt_api/migrations.py`,
`apps/api/tests/test_migrations.py`, `apps/web/src/lib/api.ts`,
`apps/web/src/lib/text-diff.ts` (new), `apps/web/src/lib/text-diff.test.ts`
(new), `apps/web/src/components/migration-success-screen.tsx`,
`apps/web/src/components/migration-success-screen.test.tsx`, plus this doc
and `docs/TESTING.md` appear in the diff).

**What a user sees**: once a migration finishes (completed, stopped early,
or failed), the Migrations tab's run screen gains a "Results — before /
after prompts" section below the Activity log — one card per stage that
got at least one attempt, showing the winning target model, its composite
score, and the original prompt against the winning prompt as an inline
word diff (struck-through red for removed text, highlighted green for
added text, unchanged words plain). Nothing to click/expand — it's visible
as soon as the section renders, no separate "view diff" action.

## Planned, not yet built — LLM call telemetry + scorecard (multi-model report)

Design pass completed 2026-07-16 (Plan agent, grounded in actual code, not
guessed) — full detail below, this is the concrete next-up work, not a
vague idea. Triggered by the product owner's explicit architecture
clarification: a migration's `target_model_config.models` are the user's
own choice of model(s) to compare — the thing being tested. Rubric
generation, judging, and the mutate/critique/refine harness are
Reprompt's own infrastructure and must use an independently-selected
model (via `select_model()`), never the model under test — see "Fix
judge/mutator self-grading bias" section (below, or being merged
concurrently) for the bug this surfaced.

**The ask**: (1) store stats for every LLM call the system makes, not
just the subset that becomes a `Candidate` row today: (2) a real
per-target-model report — winning prompt, model-card info, cost, latency
— organized per stage; (3) when a migration tried multiple target
models, a clear side-by-side with a decisive "which is actually best"
verdict, not just raw numbers.

**Key facts the design is grounded in**: every LLM call in the codebase
flows through exactly 2 closures (`rubrics.py`'s per-stage `_call`,
`optimizer_runner.py`'s per-target-model lambda) — both call
`llm_context.complete_with_workspace_credentials`, which already returns
a fully-populated `LLMResponse` (tokens/cost/latency/model/provider).
`BudgetTracker` is pure in-memory today (`packages/core/src/reprompt_core
/budget.py`) — per-call detail dies once a run finishes for anything
that isn't a sweep attempt. `Candidate` already has `target_model`
(fixed 2026-07-16), `cost`, `scores`, `prompt_variant` per attempt — the
scorecard's per-stage-per-model data is a read-time rollup over what's
already there, no new schema needed for that half.

**Decisions made** (see the full design in this session's planning
output if picking this up — summarized here):
- **New `LLMCall` table** (`apps/api` only, `packages/core` stays
  headless — only gains two additive, provider-stripped string kwargs
  `purpose`/`stage_id` threaded through ~9 existing `call(...)` sites).
  Logs every call including failures (`succeeded=false`), best-effort
  (never allowed to raise into/block the call path it's observing, same
  philosophy as `BudgetTracker.record_spend`). Purposes: `rubric_generation`,
  `judge`, `mutator_mutate`, `mutator_critique_refine`,
  `mutator_few_shot_select`, `optimizer_cheap_score`, `sweep_attempt`.
- **New `GET .../scorecard` endpoint** — does NOT replace or modify the
  existing `GET .../results` (Phase C's before/after diff keeps working
  as-is, stays the smaller/faster single-winner read). Scorecard returns
  per stage: every target model tried, its winning prompt, model-card
  info (reuses `model_cards.build_family_card()`, zero duplication),
  cost, latency, a `is_recommended` flag + human `recommendation_reason`.
  Rolls up to an `overall` per-target-model summary + `overall_recommended_model`.
- **"Best" is not raw score** — a model within `SCORE_PARITY_EPSILON` of
  the top score (reuse Prism's existing `PLATEAU_EPSILON` constant/value,
  don't invent a new number) wins on lowest cost, tie-broken by latency,
  tie-broken by position in `target_model_config.models`. Same rule
  applies at both per-stage and overall altitude. This directly answers
  "give the best," not "show the highest number."
- **UI**: extends `migration-success-screen.tsx`'s existing "Results"
  section (renamed "Scorecard") — single-model stages render like today,
  multi-model stages get a side-by-side row per model with a
  "Recommended" badge (reuses existing `Badge` "pass" token) and the
  reason as a tooltip/caption.

**Phasing**: (1) `LLMCall` telemetry, backend-only, invisible to users —
pure groundwork; (2) scorecard endpoint + UI, the real consumer-facing
feature; (3) a raw `LLMCall` ledger endpoint for debugging/cost-audit,
no UI, low priority. Not started — pick up at Phase 1.

**Invariants that must hold**: budget hard-stop untouched (telemetry is
pure side-observation, never a pre-check/gate); rubric-approval gate
untouched; per-stage failure isolation untouched (a telemetry write
failure degrades silently, never becomes a stage/migration failure);
`packages/core` stays headless.

**Open, non-blocking**: whether `LLMCall.workspace_id` should eventually
back a workspace-wide "Settings → Usage" cost dashboard (schema supports
it, no UI scoped yet); whether `judge_pairwise` vs `judge_single_pass`
need separate `purpose` values later (currently lumped as `"judge"`,
one-value addition if ever needed, not a schema change).

## Fix judge/mutator self-grading bias [DONE — 2026-07-16]

Architectural intent, confirmed with the product owner: a migration's
`target_model_config.models` is the user's own choice of model(s) to
compare/test — the thing actually being optimized (candidate prompts run
on it, compared against the original trace's output). Rubric generation,
judging/validation, and the mutate/critique/refine harness are Reprompt's
OWN infrastructure and must use an independently-selected model, decoupled
entirely from whatever the user picked to test — so the model being
evaluated never grades or refines its own output. Rubric generation was
already fixed correctly in the prior "Model auto-selection for rubric
generation" phase above (calls `select_model("rubric_generation", ...)`
against the workspace's own available models); this phase extends the
exact same pattern to the two remaining, deliberately-out-of-scope-until-now
call sites, both in `apps/api/src/reprompt_api/optimizer_runner.py`.

**The bug** (both violations confirmed by reading the code before touching
anything):
1. `judge_model = migration.target_model_config.get("judge_model") or
   target_models[0]` — with no explicit override, the judge fell back to
   the *first target model*, i.e. the model potentially under test judged
   its own output.
2. `run_optimizer(...)` was called with no `mutator_model` kwarg at all, so
   `packages/core/src/reprompt_core/optimizer/loop.py`'s own `mutator_model
   or stage_input.target_model` fallback (line ~865) silently used the
   target model as the mutator too.

**The fix** — `apps/api/src/reprompt_api/optimizer_runner.py`'s `_run()`:
both `judge_model` and `mutator_model` are now `migration.target_model_
config.get(...)` (explicit override, unchanged behavior when present) or
`select_model("judge"/"mutator", available_models)`, where
`available_models` comes from `reprompt_api.migrations.get_available_models
(db, workspace)` — the workspace's own BYOK-filtered configured models,
**never** `target_models`. `mutator_model=mutator_model` is now passed
explicitly into the `run_optimizer(...)` call (previously missing
entirely). `packages/core`'s `select_model()` itself was not touched — it
already declared both `"judge"` and `"mutator"` as valid `Purpose` values
from the rubric-generation phase, just unused until now; this phase is
pure call-site plumbing, no new heuristic. Deliberately did **not** add
logic to exclude target models from `available_models` — the architectural
requirement is that the *selection* isn't driven by what the user picked
to test, not that the two must never coincidentally match; if the
genuinely best available judge model happens to equal a target model,
that's fine and left alone.

**Real gap found and also fixed**: `apps/api/src/reprompt_api/migrations.py`'s
`TargetModelConfig` Pydantic model only declared `models: list[str]` — no
`judge_model`/`mutator_model` fields at all, despite `optimizer_runner.py`
already reading `.get("judge_model")` off the raw dict. Since `POST
/pipelines/{id}/migrations` builds the stored `target_model_config` via
`migration_in.target_model_config.model_dump()`, any `judge_model` a caller
sent through the real API was silently stripped by Pydantic before ever
reaching the DB — the "explicit override" path was dead code for any
migration created through the actual endpoint (only reachable if a test
wrote directly to the DB, bypassing the schema). Fixed by declaring both
fields as `Optional[str] = None` on `TargetModelConfig`, with a docstring
explaining the same target-vs-harness split. `model_dump()` at the create
endpoint was changed to `model_dump(exclude_none=True)` so a migration that
doesn't set either override still stores/round-trips the original bare
`{"models": [...]}` shape (existing tests assert exact dict equality on
this field — `exclude_none=True` keeps that assertion true rather than
padding the dict with two `null` keys every caller would now see).

**Circular import found and fixed**: `apps/api/src/reprompt_api/migrations.py`
already imports `run_optimizer_for_migration` from `optimizer_runner.py` at
module level (for its `BackgroundTasks.add_task()` call in `create_migration`'s
sibling "start" endpoint). A naive top-level `from reprompt_api.migrations
import get_available_models` in `optimizer_runner.py` would therefore be a
genuine circular import (`ImportError` on the partially-initialized
`migrations` module, since the cycle would resolve mid-way through
`migrations.py`'s own top-level execution, before `get_available_models` is
defined in that file). Fixed with a function-local import inside `_run()`
— the standard, minimal-footprint fix for this shape of cycle; no
restructuring of either module.

**Tests** — `apps/api/tests/test_optimizer_runner.py` (3 new):
`test_judge_and_mutator_auto_select_from_workspace_not_target_model` (a
migration targeting a weak, always-available local model
`ollama/llama3.1`, with an Anthropic BYOK key configured, auto-selects
`claude-sonnet-4-5` — a stronger tier-1 model — for both judge and mutator,
proving the selection is driven by the workspace's available models, not
`target_models[0]`, and is genuinely decoupled since the two differ),
`test_explicit_judge_model_override_wins_over_auto_select`,
`test_explicit_mutator_model_override_wins_over_auto_select` (either
override key still wins outright, unvalidated against available models,
per `select_model()`'s existing contract). `apps/api/tests/test_migrations.py`
(2 new): `test_create_migration_persists_explicit_judge_and_mutator_model_
overrides` (round-trips through the real `POST .../migrations` endpoint —
proves the schema gap above is actually fixed, not just the dict-reading
side), `test_create_migration_omits_judge_and_mutator_model_when_not_given`
(bare `{"models": [...]}` shape preserved when neither override is set).

**Verified**: `cd apps/api && uv run pytest -q` → **165 passed** (160
baseline + 5 new: 3 in `test_optimizer_runner.py`, 2 in
`test_migrations.py`). `cd packages/core && uv run pytest -q` → **305
passed, 2 skipped**, byte-for-byte unaffected — confirmed via `git status`
that no `packages/core` file changed at all (only
`apps/api/src/reprompt_api/migrations.py`,
`apps/api/src/reprompt_api/optimizer_runner.py`,
`apps/api/tests/test_migrations.py`,
`apps/api/tests/test_optimizer_runner.py`, plus this doc and
`docs/TESTING.md` appear in the diff).

**Where this leaves things**: a target model can no longer silently become
its own judge or mutator, in either the auto-select or (previously broken)
explicit-override path, matching rubric generation's existing pattern
exactly. No UI surfaces the effective/overridden judge or mutator model
yet — see `docs/TESTING.md`'s new §3.3b for the current API-level manual
check and the explicit note that a UI surface (e.g. showing the judge model
next to a migration's results) is a real, not-yet-built follow-up, out of
scope for this backend plumbing fix.

## Pre-merge review fixes for PR #8 (Phase 2/3/4 — holdout/config-export/seam) [DONE — 2026-07-22]

A code review pass (evidence-based, `code-reviewer-persona`/`spec-driven-
planning` skills applied) before merging this branch found two real issues,
both fixed here:

1. **`_run_seam_regression` hardcoded `parity_threshold=0.95`** instead of
   using the migration's actual configured value — while the main
   optimization loop correctly threads `migration.parity_threshold` through
   twice already (`optimizer_runner.py`, the two `run_optimizer(...)` call
   sites), the seam-check call site was missed. A migration with a
   non-default threshold would have every seam check evaluated against the
   wrong bar. Fixed: `_run_seam_regression` gained a required keyword-only
   `parity_threshold: float` parameter, threaded from `migration
   .parity_threshold` at its one call site — same pattern the rest of the
   file already uses.
2. **`docs/TESTING.md`'s §3.3d described UI that doesn't exist** — it said
   the Graph tab has a "floating Models in pipeline panel" and a "calls
   drawer that slides in from the right." The actual implementation
   (`pipeline-graph.tsx`) renders everything as inline React Flow nodes
   (`ModelGraphNode`, `CallGraphNode`) positioned directly in the graph —
   no panel, no drawer. Rewrote §3.3d to describe the real inline-node UI.

Both fixes verified: `cd apps/api && uv run pytest -q` → **191 passed**
(unchanged count — the `parity_threshold` fix doesn't add new test
coverage, it corrects existing runtime behavior; see the review's own
noted gap below). No `packages/core`/`apps/web` files touched by either
fix.

**Known gap, not closed by this pass** (flagged by the same review, left
for a follow-up): the new `apps/api` orchestration glue
(`_run_seam_regression`, `_persist_holdout_scores`) has zero integration
test coverage — all of PR #8's own new `test_migrations.py` cases exercise
only the read endpoints (`/export`, `/seam-results`, `/results`) against
directly-seeded DB rows, never `_run()`/`_run_seam_regression` itself
end-to-end. This is exactly why the `parity_threshold` bug above went
uncaught by the existing suite. Worth a dedicated follow-up: seed a real
migration fixture, run the actual orchestration function, assert the
persisted `SeamCheckResult`/`holdout_score` rows are correct — not done
here to keep this fix pass narrow and mergeable quickly.

## Per-model cards: thinking-mode + tool-calling + code samples [Phases 1-3 DONE — 2026-07-22, Phase 4 not started]

Research pass completed (re-dispatched after a first attempt died in
early data-gathering with nothing to salvage). Full findings, condensed:

**Audit confirmed via grep**: cost/context/JSON-mode/function-calling-
boolean already existed (`registry.py`), preferred prompt style already
existed (`model_card.py`), but working invocation code, tool-calling
*shape*, and thinking-mode support were genuinely absent anywhere in the
codebase — not something a prior pass missed, a real gap.

**LiteLLM-first research (per the owner's own correction — "couldn't we
get this from LiteLLM?" — confirmed correct)**: queried this repo's own
installed LiteLLM against all 8 `CURATED_MODELS` directly. Only
`claude-sonnet-4-5`/`claude-haiku-4-5` are genuine reasoning-tier models
among the 8 (GPT-4o/Gemini-2.0-Flash are not — that's o-series/gpt-5 and
Gemini's `-thinking-exp`/3.x lines respectively, none curated here).
Tool-calling is one fixed LiteLLM-normalized shape across every provider
(`tools=[{"type":"function","function":{...}}]`), not per-model data.
Ollama's raw `reasoning_effort`/`tools` flags were found internally
inconsistent (permissive param-passthrough, not real capability) — hand-
overridden to `False` rather than trusted.

**Architecture decided and built** (not a hand-curated table — both new
facts are already live LiteLLM data, so live-derivation was simpler than
maintaining a table, per this project's own `ponytail` discipline):

- **Phase 1** [DONE]: `packages/core/src/reprompt_core/llm/registry.py` —
  `ModelCapabilities` gained `supports_reasoning: bool`, sourced from
  `litellm.get_model_info()["supports_reasoning"]` the same way
  `max_input_tokens`/cost already are, with the Ollama override applied
  in `get_model_capabilities()`. 3 new tests
  (`test_llm_registry.py`).
- **Phase 2** [DONE]: new `packages/core/src/reprompt_core/llm/code_sample.py`
  — pure function `generate_code_sample(caps: ModelCapabilities) -> str`,
  renders a real `reprompt_core.llm.client.complete()` call including
  `tools=`/`thinking=` only when the model actually supports them. Same
  "never imports/calls `complete`" purity discipline and test pattern as
  `model_card.py`. 8 new tests (`test_code_sample.py`).
- **Phase 3** [DONE]: `apps/api/src/reprompt_api/model_cards.py` —
  `FamilyCardOut` gained `supports_reasoning`/`code_sample` fields,
  `build_family_card()` populates both. `settings.py`'s
  `ConfiguredModelOut.model_card` already embeds `FamilyCardOut` directly
  (confirmed: zero changes needed there, the new fields propagate for
  free). 3 new tests (`test_model_cards.py`) — one initial test assertion
  bug found and fixed during verification (checked for the substring
  `"thinking="` which false-matched its own "omitted" comment line; fixed
  to check the real invocation vs. the comment specifically).

**Verified**: `packages/core` 361 passed (350 + 11 new), 2 skipped.
`apps/api` 204 passed (201 + 3 new). Both suites confirmed fully green,
not just the new test files in isolation.

**Phase 4 — NOT STARTED, deliberately deferred**: a "copy code" affordance
in `ConfiguredModelsCard` (`apps/web/src/routes/settings.tsx`) surfacing
`code_sample` — frontend-only, depends on Phase 3's response shape (now
live), kept separate per this project's standing small-task discipline.

**Separate follow-up, still queued, not started**: expand `CURATED_MODELS`
(`apps/api/src/reprompt_api/migrations.py`) with the new provider families
explicitly requested — Gemini (latest), Llama, DeepSeek, GLM, MiniMax,
Qwen, whatever else is genuinely best-in-class at the time. Each needs its
own real provider-family research (new API conventions, not more
instances of an already-researched family) — deliberately not started
alongside Phases 1-3.

## Canvas/Graph tab merge [DONE — 2026-07-22]

Implements ADR-001 (`docs/architecture/adr-001-merge-canvas-and-graph-tabs.md`).
The standalone "Graph" tab is gone — `pipeline-graph.tsx` deleted, `"graph"`
removed from `WORKSPACE_TABS`. Its capabilities (model nodes, per-stage
call drill-down) are folded into `pipeline-canvas.tsx` as an
`analytics`/`live` mode, toggled via a segmented control in the same
toolbar as Spacing/Orientation. Auto-selects `live` while a migration is
running for the pipeline, `analytics` otherwise; manual override holds
for the session only (deliberately not persisted to `localStorage`, unlike
Spacing/Orientation — a stale saved preference must never suppress
auto-switching to Live when a run starts). One shared dagre layout engine,
one zoom floor, one `localStorage` key, one `["pipeline-dag", id]` query
cache for both modes — the old Graph tab's separate, laxer `minZoom: 0.25`
(the actual root cause of the illegibility bug reported this session) no
longer exists anywhere in the codebase.

**Note on how this landed**: the implementing agent hit a session-limit
termination after completing the actual code (confirmed: clean `tsc
--noEmit`, all 153 `apps/web` unit tests passing unchanged) but before
writing its final report or updating `docs/TESTING.md` — the doc update
above (§3.3d rewrite) and this entry were completed directly rather than
via the agent's own report. Verified independently before writing this:
`WORKSPACE_TABS` confirmed graph-free, `pipeline-graph.tsx` confirmed
deleted, mode-toggle state (`modeOverride`, `PipelineCanvasMode`) and the
Live/Analytics segmented control confirmed present and wired to the
`runningMigration` auto-select signal.

**Update**: `cd apps/web && npx playwright test canvas-modes minimap` run
directly — **6/6 passed** (Analytics model nodes + call drill-down, Live
mode coloring/substep/beam/minimap unchanged, mode auto-select/manual
override/reload-refresh, minimap markers on a 50-stage pipeline, Map
toggle). Fully verified, closed.
