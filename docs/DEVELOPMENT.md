# Development guide — running, checking, and testing Refract

Practical reference for actually running this project day to day. For product
context read `refract-parity-engine-plan.md`; for the build plan read
`refract-master-build-prompt.md`; for "what broke and why" read `LESSONS.md`.

## Prerequisites

- Node 22+, pnpm
- Python 3.12+, uv
- Docker Desktop — **optional for now.** M1 and M2 run entirely on SQLite;
  nothing currently requires Postgres/Redis/Langfuse to be up.

## Repo layout

```
apps/api/       FastAPI backend (Python) — packages/core is its dependency
apps/web/       React + Vite frontend (TypeScript)
packages/core/  Engine: trace schema, DAG builder, evaluators, importers.
                Zero FastAPI imports — must stay runnable headless/CLI.
docs/           This file, the build/plan docs, LESSONS.md, trace-format.md
Sample Queries/ Real production trace data. Gitignored — never commit it.
```

## First-time setup

Each Python package (`packages/core`, `apps/api`) has its **own separate
venv** — this is not a unified uv workspace. Run these in each:

```bash
cd packages/core
uv sync --all-extras
uv pip install -e . --no-deps   # see gotcha below on why this second step matters

cd ../../apps/api
uv sync --all-extras
uv pip install -e . --no-deps
```

Frontend:

```bash
cd apps/web
pnpm install
```

## Running the app

**API** (defaults to SQLite at `apps/api/test.db`, auto-creates tables on
startup for dev convenience):

```bash
cd apps/api
uv run uvicorn refract_api.main:app --reload
```

**Web** (http://localhost:5173, proxies API calls to http://localhost:8000
via CORS, not a Vite proxy — see `apps/api/src/refract_api/main.py`):

```bash
cd apps/web
pnpm dev
```

Run both together to actually use the app end to end: open
`http://localhost:5173`, import a pipeline, view the canvas.

## Running against Postgres instead of SQLite

Not required yet, but if you want to: `docker compose -f infra/docker-compose.yml up -d`,
then `DATABASE_URL="postgresql+psycopg://..." uv run alembic upgrade head`
before starting uvicorn. Nothing in the codebase currently assumes SQLite
specifically — models avoid Postgres-only types on purpose.

## Testing

### packages/core (Python — trace schema, DAG builder, evaluators, importers)

```bash
cd packages/core
uv run pytest -v
```

Currently 77 tests. Covers: trace-format schema validation (positive +
negative), DAG toposort/parallel-groups/cycle-detection, the deterministic-
checks evaluator, the embedding-similarity evaluator (bge-m3), and the
real-data "query log" importer — the last one runs against the actual files
in `Sample Queries/*.txt`, not synthetic substitutes.

### apps/api (Python — models, ingest, endpoints)

```bash
cd apps/api
uv run pytest -v
```

Currently 10 tests: healthcheck, SQLAlchemy round-trip, pipeline import
(valid + malformed + schema-violation + cycle-rejection paths), listing,
and the DAG endpoint.

### apps/web (TypeScript)

```bash
cd apps/web
npx tsc --noEmit      # typecheck — do this after any .ts/.tsx change
pnpm test             # Vitest unit tests
pnpm test:e2e         # Playwright e2e — see gotcha below, needs the API running
```

### E2E gotcha: Playwright does not start the API for you

`playwright.config.ts` only auto-starts the Vite dev server. Before
`pnpm test:e2e`, start the API manually against a **throwaway** database —
the import-flow tests assume an empty DB (they check for the "Import your
first pipeline" empty state first):

```bash
cd apps/api
rm -f e2e_test.db
DATABASE_URL="sqlite:///./e2e_test.db" uv run uvicorn refract_api.main:app --port 8000
```

Then in another terminal: `cd apps/web && npx playwright test`. Delete and
recreate `e2e_test.db` between runs if you re-run the suite.

## Manual verification checklist

Run this after any change touching import, the DAG, or the canvas — an
automated pass is not a substitute for actually looking at the screen:

1. Start the API (fresh/empty DB) and the web dev server.
2. Open `http://localhost:5173` — fresh DB should show the "Import your
   first pipeline" empty state with a working drop zone.
3. Drop one of `packages/core/tests/fixtures/*.json` (synthetic) — or run a
   real file from `Sample Queries/` through the importer first
   (`refract_core.importers.query_log.convert_file(path)`) and upload the
   result.
4. Confirm: validation report step shows correct stage/trace counts →
   "Continue to DAG preview" shows the right layer breakdown → canvas
   renders the right node count with model badges and token/latency stats.
5. Check `/dev/kit` still renders the full design system correctly — it's
   the cheapest smoke test for "did I break something in a shared
   component."

## Known environment gotchas (this machine: Windows + Git Bash)

- **`kill` / `kill %N` are unreliable** for dev-server child processes in
  Git Bash on Windows — they can silently no-op on the PID that actually
  owns the socket. Use `netstat -ano | grep :<port>` to find the real PID,
  then PowerShell `Stop-Process -Id <pid> -Force`. Full writeup in the
  memory file `feedback_gitbash_kill0_unreliable.md`.
- **A large `uv sync`/dependency install in one package can transiently
  break another package's editable install** if they share infrastructure
  — if you hit `ModuleNotFoundError` for a package that was working a
  minute ago, just re-run `uv pip install -e . --no-deps` in that package.
- **`packages/core/pyproject.toml` needs a `[build-system]` table**
  (hatchling) — without it, `uv` treats the project as "virtual" and never
  installs `refract_core` into its own venv, which silently breaks
  `import refract_core` in every test file. Already fixed; noted here so
  nobody removes it thinking it's unused boilerplate.
- **`<StrictMode>` is deliberately NOT used** in `apps/web/src/main.tsx` —
  it breaks `@tanstack/react-query` mutations in this dependency
  combination (callbacks fire, the component's rendered status doesn't).
  Full writeup in `LESSONS.md`. Don't re-add it without re-checking that
  interaction.
- **Docker Desktop is not required** for anything that currently works.
  Don't block on starting it unless you're specifically testing the
  Postgres/Redis/Langfuse compose stack.

## Where things stand

- **M0** — done. Design system, `/dev/kit`, ParityBeam component.
- **M1** — done. Trace schema + fixtures, DAG builder, SQLAlchemy models +
  Alembic, upload API + validation report, screens 1–3 (Pipelines home,
  Import wizard, Pipeline canvas). Independently reviewed; two real bugs
  found and fixed (a data-loss bug on ingest, a broken test).
- **M2 (partial)** — deterministic-checks evaluator, embedding-similarity
  evaluator (bge-m3, local, no API key), and a real-data trace importer
  are done, tested against actual production data in `Sample Queries/`.
  **Not started:** the rubric generator and the LLM judge — both need a
  real model API key (BYOK, per the project's own no-hardcoded-keys rule)
  that hasn't been configured yet.

## Remaining plan (short version)

Done: M0-M2 fully, screens 1-5, M3's non-LLM groundwork (model-card
transforms, param sweep, budget tracker, selection rule), M5's
auth/settings/BYOK wiring, universal trace format v1.1, self-hosted BYOK
(`WorkspaceApiKey.base_url`) and `Migration` progress-tracking columns.

Left, in order:
1. **Rubric generation trigger in the UI** - a button on the canvas/rubric
   screen calling the already-built `generate-rubric` endpoint per stage
   (or all stages), so rubrics stop requiring manual seeding.
2. **Model card picker integration** - surface `llm/model_card.py`'s
   per-family transform info in the migration wizard's model picker.
3. **M3 optimizer loop** - in active development. Full phase-by-phase
   breakdown, current status, and exact files/functions to pick up at:
   **`DEV_TRACKER.md`** (repo root) - keep that file, not this section, as
   the source of truth for M3 status; update it in the same commit as any
   M3 change rather than duplicating status here.
4. Budget should become optional (uncapped) rather than required - a
   separate, not-yet-started item; `DEV_TRACKER.md` explicitly notes the
   current code has no uncapped mode, don't assume otherwise while working
   on M3 above.
5. **M4** - wire the above into the full 3-pass migration run (teacher-
   forced -> end-to-end -> holdout), SSE progress, screens 6-7.
6. **M5 remainder** - scorecard screen, config export, once real
   migration results exist to show.
