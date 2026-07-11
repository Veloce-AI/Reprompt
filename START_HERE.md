# Start here

Read this first — for a new collaborator, or an AI assistant picking up
this project cold. Everything referenced below has full detail; this file
is just the map.

## What this is

Refract migrates multi-stage LLM pipelines to cheaper/on-prem models and
proves the outputs still match. Full plain-language explanation: `README.md`.

## Read in this order

1. `README.md` — what it is, what's built, tech stack
2. `docs/DEVELOPMENT.md` — how to set up and run it, **and the exact
   remaining build plan** (see "Remaining plan" section at the bottom)
3. `docs/TESTING.md` — full screen map, click-path, manual test checklist
   (keep this updated whenever a screen/feature changes — it says how)
4. `docs/trace-format.md` — the data format the whole system is built on
5. `docs/LESSONS.md` — real bugs found and why, worth reading before
   touching auth, React Query mutations, or Windows dev-server processes

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
4. **The actual optimizer loop (M3)** — the core "try it, score it, keep
   the best" search. Every piece it needs already exists (sweep generator,
   budget tracker, judge, scorer, selection rule) — nothing wires them
   into a real loop yet. Each attempt should be saved as a `Candidate` row
   (prompt tried, score, cost) so past attempts are always reviewable.
5. M4 — full migration run using the M3 loop, progress screen
6. M5 remainder — scorecard screen, config export (need real M3/M4 output first)

## How to test what exists right now

Full walkthrough with expected results: `docs/TESTING.md`. Short version:

```bash
# Terminal 1
cd apps/api && uv run uvicorn refract_api.main:app --reload
# Terminal 2
cd apps/web && pnpm dev
```
Open http://localhost:5173 → import a trace file → click through the canvas,
rubric review, and migration wizard screens.

Automated tests: `cd packages/core && uv run pytest`, `cd apps/api && uv run pytest`,
`cd apps/web && npx tsc --noEmit && pnpm test` — all documented in `docs/DEVELOPMENT.md`.

## If you're an AI continuing this work

Don't re-derive decisions already made — check `docs/DEVELOPMENT.md` and
`docs/LESSONS.md` first, they record *why*, not just *what*. Update
`docs/TESTING.md` in the same commit as any new screen/feature (it says
how, at its own bottom section).
