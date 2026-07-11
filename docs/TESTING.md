# Testing & navigation guide

A manual walkthrough of the actual app as it exists right now — every screen,
what it does, and how to verify it by hand. For automated test commands and
environment setup, see `DEVELOPMENT.md`; for what broke and why, see
`LESSONS.md`. This file is a **living document** — see "Maintaining this
doc" at the bottom for the rule on keeping it current.

## 1. How to start

Two terminals, both from repo root:

```bash
# Terminal 1 — API
cd apps/api
uv run uvicorn refract_api.main:app --reload
# → http://localhost:8000 (docs at /docs)

# Terminal 2 — Web
cd apps/web
pnpm dev
# → http://localhost:5173
```

First time only: run the setup steps in `DEVELOPMENT.md` §"First-time
setup" first (each Python package needs `uv sync --all-extras` +
`uv pip install -e . --no-deps` in its own venv).

Fresh database: delete `apps/api/test.db` before starting the API if you
want a clean slate (empty pipelines list, no users).

## 2. How to navigate — the full screen map

```
/                                      Pipelines home
/pipelines/import                      Import wizard (3 steps)
/pipelines/$pipelineId                 Pipeline canvas (React Flow DAG)
/pipelines/$pipelineId/rubrics         Rubric review (screen 4)
/pipelines/$pipelineId/migrations/new  New migration wizard (screen 5)
/login                                 Request a magic link
/auth/verify?token=...                 Exchange a magic link for a session
/settings                              Workspace name + BYOK API keys
/dev/kit                               Design system reference (not a product screen)
```

**The real click-path** through the product as built so far:

```
/  →  (drop a trace file)  →  /pipelines/import
   →  (validate, continue)  →  DAG preview  →  "View pipeline canvas"
   →  /pipelines/$id        →  "Review rubrics"  →  /pipelines/$id/rubrics
                             →  "New migration"   →  /pipelines/$id/migrations/new
```

Auth and Settings are a separate, currently-unconnected flow — nothing
above requires being logged in yet (see `LESSONS.md`/commit history: auth
exists but isn't retrofitted onto the pipeline/rubric/migration endpoints
by design, that's a deliberate future decision, not an oversight).

## 3. How to check — manual walkthrough

Run this after any change touching import, the canvas, rubrics, or
migrations. An automated pass is not a substitute for actually looking at
the screen — this is the same checklist a human reviewer should run before
calling a milestone done.

### 3.1 Import → canvas (screens 1–3)

1. Open `/` on a fresh DB → see the "Import your first pipeline" empty
   state with a working drop zone.
2. Drop `packages/core/tests/fixtures/mixed_12stage.json` (or a real file
   from `Sample Queries/`, converted via
   `refract_core.importers.query_log.convert_file`).
3. Validation report shows the correct stage/trace counts → click
   "Continue to DAG preview" → layer breakdown looks right → click "View
   pipeline canvas".
4. Canvas renders the right node count, model badges, avg token/latency
   stats per stage, and edges matching the DAG.
5. Back at `/`, the table now shows the imported pipeline (not the empty
   state) with correct stage count, model badges, benchmark query count.

### 3.2 Rubric review (screen 4)

1. Seed rubrics for the imported pipeline (no generator exists yet — this
   is a dev-only step): `cd apps/api && uv run python -m
   refract_api.seed_rubrics --pipeline-id <id>`.
2. From the canvas, click "Review rubrics" → each stage shows three
   grouped sections: Format checks, Content criteria, Downstream contract
   — all in plain English (no raw JSON/schema shown to the reviewer).
3. Edit a `required_keys` or `length_bounds` check inline, save, reload,
   confirm the edit persisted.
4. Approve one stage, then "Approve all" → confirm every stage shows
   approved.

### 3.3 New migration wizard (screen 5)

1. From the canvas, click "New migration" → step 1 shows the model picker
   with cost/context-window/JSON-mode info per model (including at least
   one local/no-key model like an `ollama/...` entry, which should show
   `requires_key: false`).
2. Set a bulk default model, override one stage individually.
3. Step 2: set a budget and parity threshold (default 95%).
4. Step 3: confirm screen shows the full config correctly, including the
   per-stage override.
5. Click "Run migration" → **expected**: a real `Migration` row is
   created (status "pending"), and the UI honestly states the optimizer
   that would actually run it doesn't exist yet. If you ever see a fake
   progress bar or "running" animation here, that's a regression — this
   screen is explicitly not allowed to pretend M3 exists until it does.

### 3.4 Auth + Settings (M5)

1. Go to `/login`, enter any email, submit.
2. **Dev mode** (default): the response includes a `dev_magic_link` — the
   UI should show/link it directly, since no real email provider is
   configured. Click it (or visit `/auth/verify?token=...` with it).
3. Land authenticated on `/`, session token stored (check
   `localStorage` in devtools if you want to confirm directly).
4. Go to `/settings` → rename the workspace, confirm it saves.
5. Add an API key for a provider (any string, e.g. `openai`) with a fake
   value like `sk-test-1234567890`. Confirm it appears in the list
   showing only `last_four` (`...7890`) — the full value must never
   reappear anywhere in the UI or a network response after the initial
   save.
6. Delete the key, confirm it's gone from the list.
7. **Known gap, not yet built**: a saved key doesn't do anything live yet
   beyond the one proof-of-concept endpoint
   (`POST /pipelines/{id}/stages/{id}/test-prompt`, see `apps/api/src/refract_api/llm_context.py`)
   — it isn't wired into the rubric generator or optimizer because
   neither of those exist yet either.

### 3.5 Design system sanity check

`/dev/kit` — cheapest smoke test for "did I break something in a shared
component." All 8 sections should render: color, type, button, card,
table, badge, drawer (opens from the **right**, not the bottom — a past
regression, see `LESSONS.md`), ParityBeam (all 6 states, draw-in
animation actually animates the beam not the marker — also a past
regression).

## 4. Automated tests

Full commands and gotchas (E2E needing a manually-started API server,
Windows process-killing quirks, etc.) are in `DEVELOPMENT.md` §Testing.
Quick reference:

```bash
cd packages/core && uv run pytest -v   # trace/DAG/evaluators/judge/scoring/sweep/budget/model-card
cd apps/api && uv run pytest -v        # models/ingest/pipelines/rubrics/migrations/auth/settings
cd apps/web && npx tsc --noEmit && pnpm test   # typecheck + Vitest
cd apps/web && npx playwright test     # needs the API running separately first, see DEVELOPMENT.md
```

## 5. What's not built yet (don't go looking for it)

- No route guards on any pipeline/rubric/migration screen — auth exists
  but nothing requires being logged in yet, by design.
- No rubric *generator* — rubrics only exist if hand-seeded via
  `seed_rubrics.py`.
- No optimizer — "Run migration" creates a config record, nothing more.
- No scorecard screen, no config export — both need real migration
  results that don't exist without an optimizer.
- Docker/Postgres path exists but is untested in this environment by
  choice (SQLite only so far).

## 6. Maintaining this doc

**Whenever a new screen, route, or user-facing flow ships, update this
file in the same commit (or the very next one) that ships it:**

- Add the route to the map in §2.
- Add a numbered walkthrough subsection to §3 in the same style as 3.1–3.4:
  concrete steps, concrete expected outcomes, and call out anything that
  was a **past regression** so it doesn't silently reappear.
- If a "not built yet" item in §5 gets built, delete it from §5 and give
  it a real section in §3 and a row in the §2 map — don't let §5 go stale
  in the other direction either.
- If a feature changes behavior (e.g. auth becomes required on some
  screen), update the affected walkthrough steps rather than leaving
  stale instructions — a wrong manual test is worse than no manual test,
  since it wastes a reviewer's time chasing a "bug" that's actually just
  this doc being outdated.
