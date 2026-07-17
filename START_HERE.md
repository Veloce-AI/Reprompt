# Start here

Read this first — for a new collaborator, or an AI assistant picking up
this project cold. Everything referenced below has full detail; this file
is just the map.

## What this is

Reprompt migrates multi-stage LLM pipelines to cheaper/on-prem models and
proves the outputs still match. Full plain-language explanation: `README.md`.

## Read in this order

1. `README.md` — what it is, what's built, tech stack
2. `docs/DEVELOPMENT.md` — how to set up and run it, **and the exact
   remaining build plan** (see "Remaining plan" section at the bottom)
3. `DEV_TRACKER.md` — detailed, actively-updated phase-by-phase status of
   the optimizer (M3) work specifically — check this before touching
   anything under `packages/core/src/reprompt_core/optimizer/`
4. `docs/TESTING.md` — full screen map, click-path, manual test checklist
   (keep this updated whenever a screen/feature changes — it says how)
5. `docs/trace-format.md` — the data format the whole system is built on
6. `docs/LESSONS.md` — real bugs found and why, worth reading before
   touching auth, React Query mutations, or Windows dev-server processes
7. `.claude/skills/` — **MANDATORY, not optional background context.** Ten
   skills live here now: `saas-product-design`/`frontend-design`/
   `system-design` (written for this project specifically, encode real bugs
   this project already hit — read these before ANY UI/UX or architecture
   work, not just when a task looks design-y), `impeccable`/`design-system`/
   `ui-styling`/`frontend-design-anthropic`/`theme-factory` (frontend
   craft), `webapp-testing` (drive-the-real-app discipline — this project
   has repeatedly shipped bugs that passed unit tests but broke on real
   render/CSS, see `saas-product-design`'s point 5 and `system-design`'s
   point 5), `skill-creator` (for writing more of these well),
   `ponytail`/`ponytail-audit`/`ponytail-debt`/`ponytail-gain`/
   `ponytail-help`/`ponytail-review` (write-minimal-necessary-code
   discipline — read `ponytail` before any implementation task, it's the
   concrete version of this project's own "Simplicity First / No Laziness"
   rule), `code-simplifier` (post-hoc simplification pass — read after
   writing/editing code, before calling a change done), `design-references`
   (real SaaS DESIGN.md specs — Linear/Stripe/PostHog — for comparison when
   unsure how a data-dense serious-tool screen should look; reference
   points, never templates to copy verbatim), `code-reviewer-persona`/
   `ai-code-security-auditor`/`appsec-engineer-persona` (read
   `ai-code-security-auditor` specifically before treating any AI-agent-
   generated code as done — this project's whole workflow is multi-agent
   code generation, exactly the failure mode this skill exists for:
   hardcoded secrets, disabled row-level security, prompt-injection sinks
   shipped because a demo happened to work without them), `spec-driven-
   planning` (evidence-based architecture writing — read before dispatching
   any planning-only agent or writing a `DEV_TRACKER.md` phase section:
   every claim traces to a real file, no hypothetical/idealized
   components, one clear recommendation per open question). Separately,
   `.claude/skills/EXTERNAL_TOOLS.md` lists standalone systems (not
   skills — nothing to read, software you'd run on its own) that were
   considered and are documented but NOT currently set up: an
   architecture-spec drafting tool, an authorized-security-testing
   framework for testing a deployed instance later. See
   `.claude/skills/ATTRIBUTION.md` for exact sources/licenses before adding
   more; `anthropics/claude-code`'s own skills are NOT available to pull
   from (checked, all-rights-reserved). **If you are dispatching a
   sub-agent for UI, testing, or architecture work, name the specific
   relevant skill(s) in its prompt explicitly** — a skill sitting in this
   folder does nothing on its own if nobody is told to actually read and
   apply it; this was a real gap already found and fixed once in this
   project's own history, don't reintroduce it.

## Current state (see docs/DEVELOPMENT.md for full detail)

**Built and tested:** import, DAG builder, all 3 evaluators (rule-based +
embedding + AI judge), rubric generation (works, needs manual trigger),
BYOK key storage + live model calls, screens 1–5, auth, settings.

**Not built yet, in order:**
1. Rubric generation trigger in the UI (endpoint exists, no button calls it yet)
2. Model-card info (preferred prompt format per model family) surfaced in
   the migration wizard's model picker — logic exists (`llm/model_card.py`),
   not connected to that screen
3. Budget should become optional (currently required) in the migration wizard
4. **The actual optimizer loop (M3)** — in active development, see
   `DEV_TRACKER.md` for the exact phase-by-phase status and where to pick
   up. Two strategies: "simple" (one-shot mutation + sweep) and "Prism"
   (multi-round mutate → critique → refine, plus optional few-shot
   selection), both in-house, both provider-agnostic. Each attempt is
   saved as a `Candidate` row (prompt tried, score, cost) so past attempts
   are always reviewable.
5. M4 — full migration run using the M3 loop, progress screen
6. M5 remainder — scorecard screen, config export (need real M3/M4 output first)

## How to test what exists right now

Full walkthrough with expected results: `docs/TESTING.md`. Short version:

```bash
# Terminal 1
cd apps/api && uv run uvicorn reprompt_api.main:app --reload
# Terminal 2
cd apps/web && pnpm dev
```
Open http://localhost:5173 → import a trace file → click through the canvas,
rubric review, and migration wizard screens.

Automated tests: `cd packages/core && uv run pytest`, `cd apps/api && uv run pytest`,
`cd apps/web && npx tsc --noEmit && pnpm test` — all documented in `docs/DEVELOPMENT.md`.

## If you're an AI (or a developer) continuing this work

**Point whoever/whatever is picking this up at this file first.** It's
the map; `DEV_TRACKER.md` is the detailed status for whatever's actively
in progress (currently M3/the optimizer — check its "Current state"
paragraph at the top for the real, current phase).

**Before writing any code:**
1. Read `DEV_TRACKER.md`'s "Current state" paragraph and the phase list —
   don't assume this file's "Not built yet" list above is precise down to
   the sub-step; `DEV_TRACKER.md` is the source of truth for anything it
   covers, this file is the map to *find* that truth, not a substitute
   for reading it.
2. Don't re-derive decisions already made — check `docs/DEVELOPMENT.md`
   and `docs/LESSONS.md` first, they record *why*, not just *what*.
   Re-litigating a settled decision wastes a full research pass for
   nothing new.
3. Run the existing test suites (`docs/DEVELOPMENT.md`'s Testing section)
   *before* changing anything, so you know what "still passing" means
   against a clean baseline, not a state you're not sure was already
   broken.

**Before you commit/push — this is not optional, do all of it every time:**
1. Update `DEV_TRACKER.md`: mark any phase/checklist item you completed
   `[x]`/`[DONE]`, rewrite its "Current state" paragraph to match reality
   (not what was planned — what's actually true right now), and if you
   found a real bug or made a design decision worth remembering, write it
   down there (see that file's own several examples of this — a plateau
   logic bug, the PromptWizard vendoring reversal — each with why, not
   just what changed).
2. If you added/changed a screen or feature, update `docs/TESTING.md` in
   the *same commit* (it says how, at its own bottom section) — don't
   defer this, it goes stale fast otherwise.
3. If this file's own "Current state" section above (Built/Not built)
   drifted out of sync with reality because of what you just did, fix it
   too — this file is read *first*, so it drifting stale is worse than
   any other doc drifting stale.
4. Run the full test suites again and confirm they're still green before
   considering anything "done" — a passing test suite is a claim you
   verified, not one you assumed.
5. **Leave a clear "where I left off."** If you're stopping mid-phase,
   say so explicitly in `DEV_TRACKER.md`'s "Current state" paragraph —
   which specific function/file/test was in progress, and what the very
   next step is. The goal: the next session (yours or someone else's)
   should never have to re-read your diffs to figure out what you were
   about to do next.
6. Never push to git yourself unless explicitly told to for that specific
   push — give the exact `git add`/`commit`/`push` commands and let the
   human run them. (This is a standing rule for this project, not a
   suggestion.)
