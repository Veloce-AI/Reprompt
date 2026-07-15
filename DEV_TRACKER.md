# Reprompt — Dev Tracker

Single source of truth for what's built across the whole project (M0-M5)
and, in detail, what's in progress and what's next on the M3 optimizer
specifically. Update this in the same commit as any change to the phases
below — mark `[x]` as you complete an item, and keep "Current state"
accurate so anyone (human or AI) can pick this up cold without
re-deriving context. Read `START_HERE.md` first if you haven't — it
points here plus the rest of the docs in reading order.

Last updated: 2026-07-15.

## Current state (one paragraph)

Two optimizer strategies exist in `packages/core/src/reprompt_core/optimizer/`:
**simple** (one-shot: mutate the prompt once via one LLM call, then run
the param/format sweep) and **Prism** (multi-round: mutate → cheap-score →
critique the weak ones → refine → sweep again → full-score → select, plus
optional few-shot example selection). Both are 100% in-house code — no
vendored source, no new dependencies, both call the engine's own
`llm/client.py` so both work with any provider (OpenAI/Anthropic/Gemini/
self-hosted) uniformly. `run_optimizer(..., strategy="simple"|"prism")`
selects between them; `apps/api` reads this from `OPTIMIZER_STRATEGY`
(see `apps/api/.env.example`).

**Done and test-verified**: Phase 0 (cleanup), the DB/credential
groundwork, Phase 1 (`mutator.py`'s `critique_and_refine`/
`select_few_shot_examples`), Phase 2 (`loop.py`'s strategy dispatch and
`_optimize_stage_prism`), Phase 3 (`packages/core` tests), and **Phase 4 +
4b** (`apps/api` wiring — merged via PR #3/#4 from an external
contributor, `shreychechani`, reviewed and tested before merge — see
"PR #3/#4 review notes" below for what changed vs. this file's original
Phase 4 spec and one real gap found). **Not started**: Phase 6 (final
end-to-end manual verification), the `target_model` tracking fix (see
below).

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
- **Real gap, not yet fixed**: neither `StageAttempt` (packages/core) nor
  `Candidate` (apps/api) records *which* target model produced a given
  attempt. Once a migration tries multiple models, there's no way to tell
  from a `Candidate` row which model the winning prompt was actually tuned
  for. Cheap to fix now (add a `target_model` field to both), will be
  painful once the Phase 5/scorecard screen is built assuming the current
  schema. **Next concrete task**, not yet started.
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
