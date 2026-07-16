# Testing & navigation guide

A manual walkthrough of the actual app as it exists right now — every screen,
what it does, and how to verify it by hand. For automated test commands and
environment setup, see `DEVELOPMENT.md`; for what broke and why, see
`LESSONS.md`. This file is a **living document** — see "Maintaining this
doc" at the bottom for the rule on keeping it current.

## 1. First-time setup (do this once per machine)

Everything below assumes nothing is installed yet except the base tools:
**Node 22+, pnpm, Python 3.12+, uv**. If you don't have those, install them
first (nvm/Node installer, `npm install -g pnpm`, python.org or your OS
package manager, `pip install uv` or the uv installer script) — not covered
here, it's a one-time machine setup, not a repo setup.

### 1.1 Get into the repo

```bash
cd C:/VeloceAI/Reprompt          # or wherever you cloned/copied it
```

Everything from here on is relative to this folder. Open two more terminal
tabs/windows now — you'll want three total (one per Python package, plus
the frontend), though in practice you mostly just need two running at once
later (API + web).

**Fast path**: `bash scripts/setup.sh` from the repo root does everything
in §1.2-1.4 below for you (both Python installs, the BYOK encryption key,
the database, and the frontend install), and is safe to re-run. The
step-by-step below is for understanding what it does or doing it by hand.

### 1.2 `packages/core` — the engine (trace schema, DAG, evaluators)

This is a **separate Python venv** from `apps/api` — not a shared
workspace. Do this in its own terminal:

```bash
cd packages/core
uv sync --all-extras
uv pip install -e . --no-deps
```

Why both commands: `uv sync` installs dependencies (pydantic, pytest,
sentence-transformers, litellm, optuna, etc.) into `.venv`, but doesn't
install the package itself in editable mode in every case — the second
command guarantees `import reprompt_core` actually resolves. If you ever
see `ModuleNotFoundError: No module named 'reprompt_core'` later, re-run
just that second line.

Verify it worked:

```bash
uv run pytest -q
# should end with something like "240 passed, 1 skipped"
```

(The 1 skipped test needs a local Ollama server — that's expected and
fine, not a failure.)

### 1.3 `apps/api` — the backend

Also its own separate venv:

```bash
cd ../../apps/api        # from packages/core, or `cd apps/api` from repo root
uv sync --all-extras
uv pip install -e . --no-deps
```

`apps/api` depends on `packages/core` as a local editable path dependency
(declared in its `pyproject.toml`), so it needs step 1.2 done first — if
you skipped it, go back and do it.

Verify it worked:

```bash
uv run pytest -q
# should end with something like "88 passed"
```

Two more one-time steps before you can actually *run* the app (not needed
just to run the test suite above — `uv run pytest` doesn't touch either):

**Encryption key** — Settings/BYOK API-key storage needs
`REPROMPT_SETTINGS_ENCRYPTION_KEY` set or it 500s. Generate one and put it
in `apps/api/.env` (gitignored):

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# echo "REPROMPT_SETTINGS_ENCRYPTION_KEY=<paste the output>" > .env
```

**Database** — create it via Alembic, not by just starting the API and
letting it auto-create tables. `main.py`'s dev-convenience auto-create
builds tables matching the current models but never stamps
`alembic_version`, so a later `alembic upgrade head` against that same
file fails with "table already exists" — a real gotcha hit and fixed
during this project's own development (see `DEV_TRACKER.md`):

```bash
set -a && source .env && set +a
uv run alembic upgrade head
```

### 1.4 `apps/web` — the frontend

```bash
cd ../../apps/web         # from apps/api, or `cd apps/web` from repo root
pnpm install
```

Verify it worked:

```bash
npx tsc --noEmit          # should print nothing (clean)
pnpm test                 # should end with something like "52 passed"
```

### 1.5 First-time setup is done. Now go to §2 to actually run the app.

If anything above failed, check `DEVELOPMENT.md` §"Known environment
gotchas" before assuming it's a real bug — several of the failure modes
you'd hit on first setup (venv install ordering, a missing
`[build-system]` table, Windows-specific process issues) are already
documented there with the fix.

## 2. How to start (every time after first-time setup)

Two terminals, both from repo root:

```bash
# Terminal 1 — API
cd apps/api
set -a && source .env && set +a
uv run uvicorn reprompt_api.main:app --reload
# → http://localhost:8000 (docs at /docs)

# Terminal 2 — Web
cd apps/web
pnpm dev
# → http://localhost:5173
```

Fresh database: delete `apps/api/test.db`, then run `uv run alembic
upgrade head` again (not just `rm` + start the API — see the "Database"
step in §1.3 for why letting the API's own auto-create rebuild it instead
causes a later `alembic upgrade head` to fail).

## 3. How to navigate — the full screen map

```
/                                      Pipelines home
/pipelines/import                      Import wizard (3 steps)
/pipelines/$pipelineId?tab=canvas      Pipeline workspace — Canvas tab (default, React Flow DAG)
/pipelines/$pipelineId?tab=data        Pipeline workspace — Data tab (StageRecord browser, Phase 3)
/pipelines/$pipelineId?tab=rubrics     Pipeline workspace — Rubrics tab (screen 4)
/pipelines/$pipelineId?tab=migrations  Pipeline workspace — Migrations tab (screen 5)
/login                                 Request a magic link
/auth/verify?token=...                 Exchange a magic link for a session
/settings                              Workspace name + BYOK API keys
/dev/kit                               Design system reference (not a product screen)
```

**The old three-route shape** (`/pipelines/$id`, `/pipelines/$id/rubrics`,
`/pipelines/$id/migrations/new` as separate screens) was replaced 2026-07-15
by the single unified workspace above — see DEV_TRACKER.md's "Phase 1 —
Unified pipeline workspace". `/pipelines/$id/rubrics` and
`/pipelines/$id/migrations/new` still work as URLs (any old bookmark or
shared link) but now just redirect into the matching tab of
`/pipelines/$id` — they render nothing of their own anymore.

**The real click-path** through the product as built so far:

```
/  →  (drop a trace file)  →  /pipelines/import
   →  (validate, continue)  →  DAG preview  →  "View pipeline canvas"
   →  /pipelines/$id (Canvas tab)  →  click "Rubrics" tab  →  ?tab=rubrics
                                    →  click "Migrations" tab  →  ?tab=migrations
```

Auth and Settings are a separate, currently-unconnected flow — nothing
above requires being logged in yet (see `LESSONS.md`/commit history: auth
exists but isn't retrofitted onto the pipeline/rubric/migration endpoints
by design, that's a deliberate future decision, not an oversight).

## 4. How to check — manual walkthrough

Run this after any change touching import, the canvas, rubrics, or
migrations. An automated pass is not a substitute for actually looking at
the screen — this is the same checklist a human reviewer should run before
calling a milestone done.

### 3.1 Import → canvas (screens 1–3)

1. Open `/` on a fresh DB → see the "Import your first pipeline" empty
   state with a working drop zone.
2. Drop `packages/core/tests/fixtures/mixed_12stage.json` (or a real file
   from `Sample Queries/`, converted via
   `reprompt_core.importers.query_log.convert_file`).
3. Validation report shows the correct stage/trace counts → click
   "Continue to DAG preview" → layer breakdown looks right → click "View
   pipeline canvas".
4. Canvas renders the right node count, model badges, avg token/latency
   stats per stage, and edges matching the DAG.
5. Back at `/`, the table now shows the imported pipeline (not the empty
   state) with correct stage count, model badges, benchmark query count.

### 3.1b Unified pipeline workspace (tabs, inline rename, rubric drawer)

Added 2026-07-15 — see DEV_TRACKER.md's "Phase 1 — Unified pipeline
workspace". Covers the persistent header/tab bar that now wraps the Canvas,
Data, Rubrics, and Migrations screens, plus the canvas's new node-click
drawer.

1. On `/pipelines/$id`, click directly on the pipeline name in the header →
   it turns into a text input. Change it, press Enter (or click away) →
   confirm it saves (`PATCH /pipelines/{id}`) and the header shows the new
   name after the input closes. Press Escape while editing → confirm it
   discards the draft instead of saving.
2. Click each of the four tab buttons (Canvas · Data · Rubrics ·
   Migrations) → confirm the URL's `?tab=` query param changes to match and
   the body below swaps — the header and tab bar itself never re-render/flash.
3. The Data tab now shows the real StageRecord browser — see §3.1c below
   for its own walkthrough (built in Phase 3, 2026-07-16; it used to be a
   plain "Coming soon" panel).
4. On the Canvas tab, click any stage node → a drawer slides in from the
   right showing that stage's rubric (format checks + content criteria) and
   an "Approve" button. Approving from the drawer updates the badge in
   place without closing the drawer or navigating away.
5. In the drawer, click "View full rubric →" → the workspace switches to
   the Rubrics tab and scrolls straight to that stage's card (each card has
   an anchor id — no other card should end up at the top of the viewport
   for even a frame first).
6. Visit `/pipelines/$id/rubrics` or `/pipelines/$id/migrations/new`
   directly (typed URL or an old bookmark) → confirm each redirects to
   `/pipelines/$id?tab=rubrics` / `?tab=migrations` respectively, landing on
   the right tab with the right tab button visually active.

### 3.1c Data tab — StageRecord browser (Phase 3, 2026-07-16)

A read-only, spreadsheet-style browser over every `StageRecord` (input,
rendered prompt, output, tokens/cost/latency) captured for a pipeline's
benchmark traces. No edit/approve affordances here by design — that stays
exclusive to the Rubrics tab.

1. On `/pipelines/$id?tab=data`, confirm a table renders with columns:
   Trace · Stage · Input · Rendered Prompt · Output · Tok in · Tok out ·
   Cost · Latency — the three text columns (Input/Rendered Prompt/Output)
   show truncated (~80 char) previews, not the full text.
2. Use the "Stage" dropdown above the table (default "All stages",
   populated from the same DAG fetch the Canvas tab uses) to filter down to
   one stage → confirm only that stage's rows remain and the row count
   drops accordingly.
3. Click any row → a drawer slides in from the right (same drawer
   component the Canvas tab's rubric drawer uses) showing that record's
   full, untruncated input (pretty-printed JSON), rendered prompt, and
   output, plus its exact token/cost/latency figures.
4. Scroll a pipeline with many benchmark traces → confirm more rows load
   in automatically as you approach the bottom (cursor pagination against
   `GET /pipelines/{id}/stage-records`, ~50 records per page) without a
   visible "load more" click or a full page re-fetch.
5. **Deliberately not built yet, not a bug**: no Run filter/dropdown (a
   fast follow-on once Phase 2's `GET /pipelines/{id}/runs` multi-run
   endpoint lands — see `DEV_TRACKER.md`'s Phase 3 entry) and no text
   search box (out of scope, would need real indexing).

### 3.2 Rubric review (Rubrics tab, screen 4)

1. Either seed rubrics for the imported pipeline via the dev-only script
   (`cd apps/api && uv run python -m reprompt_api.seed_rubrics
   --pipeline-id <id>`), **or** use the real generator now built into the
   tab itself: enter a model name (e.g. `openai/gpt-4o`) in the field at
   the top of `/pipelines/$pipelineId?tab=rubrics` and click "Generate all
   rubrics" — needs a real BYOK key configured for that model's provider
   (see §3.4 below), makes one real LLM call per stage.
2. From the canvas, click the "Rubrics" tab → each stage shows three
   grouped sections: Format checks, Content criteria, Downstream contract
   — all in plain English (no raw JSON/schema shown to the reviewer).
3. Edit a `required_keys` or `length_bounds` check inline, save, reload,
   confirm the edit persisted.
4. Approve one stage, then "Approve all" → confirm every stage shows
   approved.

### 3.3 New migration wizard (Migrations tab, screen 5)

1. From the canvas, click the "Migrations" tab → step 1 shows the model picker
   with cost/context-window/JSON-mode info per model (including at least
   one local/no-key model like an `ollama/...` entry, which should show
   `requires_key: false`) and, next to each model option, its model-card
   info fetched from `GET /model-cards/{model}` — resolved prompt family
   (anthropic/gemini/openai/llama/generic) and which transform rules will
   actually apply to that specific model (e.g. "xml_wrap_sections" for a
   Claude target, "terseify_if_small" only for a nano/mini/haiku-class
   model) — see `DEV_TRACKER.md`'s "Phase D(a)".
2. Set a bulk default model, override one stage individually.
3. Step 2: set a budget and parity threshold (default 95%).
4. Step 3: confirm screen shows the full config correctly, including the
   per-stage override.
5. Click "Run migration" → **expected**: a real `Migration` row is
   created and the optimizer actually runs (M3/M4 wiring — Phase 4/4b —
   landed after this section was first written; the "no fake progress bar"
   caveat that used to live here is stale and superseded by the live view
   below). Needs a real BYOK key configured — see `README.md`'s "Getting
   an AI model API key" section.
6. While it's running: the pipeline DAG canvas appears live, with the
   currently-optimizing stage's node pulsing indigo (Phase 2 — "Live
   DAG/run status view") and, directly under its name, a small sub-step
   line reading e.g. "Running — critiquing weakest candidates" or
   "Running — running parameter sweep" that updates roughly every 2s as
   the optimizer moves through mutation, critique/refine rounds
   (Prism strategy only), and the final sweep/score pass (Phase A — "Live
   optimizer sub-step signal", see `DEV_TRACKER.md`). Finished stages turn
   green, a failed/budget-stopped stage turns red with the reason shown in
   the run bar above the canvas.
7. Click "Back to pipeline canvas" from the run screen → confirm it just
   switches the tab bar back to Canvas (`?tab=canvas`), not a full page
   navigation away from the workspace.
8. Switch to another tab and back to Migrations (or reload the page while
   on `?tab=migrations`) → confirm you land straight back on this same
   run/success screen (`GET /pipelines/{id}/migrations` finding the
   existing `Migration` row), not the wizard again — the wizard only shows
   when a pipeline has no `Migration` yet.

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
7. Scroll down to the **"Configured models"** card (new, 2026-07-15 — this
   used to be the empty/undersized part of the page): before adding any
   key, it lists only the no-key-required curated models (the `ollama/...`
   entries, since local/self-hosted models never need a BYOK key). Add an
   API key for `openai` (step 5 above) → reload/refetch → `gpt-4o` and
   `gpt-4o-mini` now appear too, grouped under an "openai" heading. Each
   model shows input/output cost per 1M tokens (or "Free (local)"),
   its resolved prompt family, and a pill per model-card transform rule
   that will actually apply to it — the same underlying data as the
   migration wizard's model picker (§3.3 step 1,
   `GET /settings/models`/`apps/api/src/reprompt_api/settings.py`), just
   surfaced globally instead of buried inside one pipeline's wizard.
8. A saved key is wired into: the model-picker/wizard's live model calls,
   the rubric generator (§3.2), and the optimizer (§3.3) — all three read
   workspace BYOK keys via `complete_with_workspace_credentials`
   (`apps/api/src/reprompt_api/llm_context.py`). Not wired: nothing left
   outstanding here that's specific to Settings itself.

### 3.5 Design system sanity check

`/dev/kit` — cheapest smoke test for "did I break something in a shared
component." All 8 sections should render: color, type, button, card,
table, badge, drawer (opens from the **right**, not the bottom — a past
regression, see `LESSONS.md`), ParityBeam (all 6 states, draw-in
animation actually animates the beam not the marker — also a past
regression).

## 5. Automated tests

Full commands and gotchas (E2E needing a manually-started API server,
Windows process-killing quirks, etc.) are in `DEVELOPMENT.md` §Testing.
Quick reference:

```bash
cd packages/core && uv run pytest -v   # trace/DAG/evaluators/judge/scoring/sweep/budget/model-card
cd apps/api && uv run pytest -v        # models/ingest/pipelines/stage_records/rubrics/migrations/auth/settings
cd apps/web && npx tsc --noEmit && pnpm test   # typecheck + Vitest
cd apps/web && npx playwright test     # needs the API running separately first, see DEVELOPMENT.md
```

## 6. What's not built yet (don't go looking for it)

- No route guards on any pipeline/rubric/migration screen — auth exists
  but nothing requires being logged in yet, by design.
- No API endpoint runs the raw `Sample Queries/*.txt` query-log converter
  (`reprompt_core.importers.query_log.convert_file`) — dropping one of
  those files straight into the import wizard fails validation (it's not
  yet in the universal trace schema shape). Convert it to JSON with that
  function first (one Python call, see §3.1) before importing via the UI.
  A real, pre-existing gap (not something this session broke) — worth
  closing with a proper API-side conversion step in a future pass.
- No scorecard screen, no config export — both need a full M4 3-pass
  migration run's real results, which the current single-pass M3 loop
  doesn't produce yet.
- Docker/Postgres path exists but is untested in this environment by
  choice (SQLite only so far).

## 7. Maintaining this doc

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
