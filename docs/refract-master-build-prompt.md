# REFRACT — Master Build Prompt
### Paste-ready for Claude Code. Read fully before writing any code. Also read docs/refract-parity-engine-plan.md for product context.

---

## 0. Mission

Build **Refract**, a SaaS that migrates multi-stage LLM pipelines (5–50 calls, sequential + parallel, mixed models) to new/cheaper/on-prem models with **proven output parity**. Users import execution traces, the system generates per-stage rubrics explaining why benchmark outputs are ideal, then an optimization loop (model-card transforms + DSPy MIPROv2 + param/format sweeps) tunes prompts and settings per stage until the new model matches the benchmark — validated end-to-end and on a holdout set. Output: migrated config + parity/cost/latency scorecard.

You are the sole engineering team. I review at every stop-gate. Optimize for: shippable vertical slices, boring reliable tech, a UI a non-technical buyer understands in 30 seconds.

## 1. Working Rules (non-negotiable)

1. **Small, explicitly scoped steps.** Never plan more than the current milestone. If a task feels large, split it and tell me the split before coding.
2. **Stop-gates.** At the end of each milestone: run tests, show me results + what to review, then STOP. Do not start the next milestone without my go.
3. Every feature lands with tests (pytest backend, Vitest + Playwright smoke for frontend). No TODO-and-move-on.
4. Conventional commits, one logical change per commit.
5. Keep a `docs/LESSONS.md` log: anything that broke, why, and the fix.
6. Never hardcode API keys. All model access is BYOK via env/user-supplied keys through LiteLLM.

## 2. Stack & Repo Layout (decided — don't relitigate)

Monorepo, pnpm workspaces + uv:

```
refract/
├── apps/
│   ├── api/          # Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, Celery
│   └── web/          # React 18 + Vite + TypeScript, Tailwind, shadcn/ui (restyled),
│                     # TanStack Query + Router, React Flow, Recharts, Zustand (UI state only)
├── packages/
│   └── core/         # Python: engine (ingest, DAG, rubric, optimizer, evaluator)
│                     # Zero FastAPI imports — must run headless/CLI. This is the moat.
├── infra/            # docker-compose (postgres, redis, langfuse), Dockerfiles
└── docs/
```

Backend deps: `litellm` (all model calls + registry), `dspy` (MIPROv2 inner loop), `optuna` (param sweeps, grid sampler for MVP), `langfuse` (tracing, self-host), `pydantic` v2, `sentence-transformers` w/ `bge-m3` (embedding similarity, local — keeps on-prem story clean).

Realtime: run progress streams over SSE (`GET /migrations/{id}/events`) — simpler than websockets, fine for one-way progress.

Deploy target (MVP): docker-compose on a single VM (Hetzner/Railway). Design for it; don't build k8s anything.

## 3. Design System — "Instrument Grade"

Refract = light refracting through a prism. The product proves that the *same signal* passes through a *different medium* intact. The UI should feel like a precision optical instrument: calm, exact, quietly confident. Not a hacker terminal, not a cream-and-serif landing template.

### Tokens (create as `apps/web/src/styles/tokens.css`, everything derives from these)

**Color** — light "laboratory" theme default (enterprise buyers screen-share in daylight), dark theme as toggle later:
- `--paper: #FAFBFD` (cool near-white, main bg)
- `--ink: #10182B` (deep blue-black, primary text)
- `--ink-soft: #5A6478` (secondary text, labels)
- `--line: #E3E8F0` (hairline borders, 1px, used instead of shadows)
- `--beam: #4C5FE8` (refraction indigo — primary accent: actions, links, focus rings, active nodes)
- `--beam-soft: #EDEFFE` (indigo tint for selected/hover surfaces)
- Parity semantics (fixed meanings, never decorative): `--parity-pass: #0E9F6E`, `--parity-near: #D97706`, `--parity-fail: #DC2626`
- `--spectrum` gradient (violet→indigo→teal) reserved EXCLUSIVELY for the signature element below.

**Type:**
- Display: **Spectral** (Google Fonts — the name is the brand pun; use SemiBold, only for page titles, big scorecard numbers, empty-state headlines. Restraint: max ~2 uses per screen.)
- UI/body: **IBM Plex Sans** (400/500/600)
- Data/mono: **IBM Plex Mono** (prompts, diffs, tokens, code, all numerals in tables via tabular-nums)
- Scale: 12 / 13 / 14 (base) / 16 / 20 / 28 / 40. Dense but breathable; data UIs earn small type with generous line-height (1.5+).

**Layout:** 4px spacing grid. Border-radius 6px cards / 4px controls. Depth via hairlines + background tints, not drop shadows (one shadow level allowed for popovers only). Left nav rail (icons + labels, 220px), content max-width 1440px.

**Signature element — the Parity Beam:** every stage node and the scorecard header carries a thin (3px) horizontal beam. Benchmark side is a solid `--ink` line; at the "prism" midpoint it refracts into the spectrum gradient; the candidate's parity score is a marker positioned along it, colored by parity semantics. Same component everywhere (`<ParityBeam score cost />`). This is the one memorable thing; keep everything else quiet.

**Motion:** 150–200ms ease-out on state changes only. One orchestrated moment: when a migration completes, the scorecard's beams draw in left-to-right, staggered 60ms. Respect `prefers-reduced-motion`. Nothing else animates.

**Writing in the UI:** sentence case everywhere. Buttons say what happens: "Run migration", "Export config", "Approve rubric" — never "Submit". Errors state what went wrong + the fix ("Trace file missing `stage_id` on 3 records. Download the annotated file to see which."). Empty states are invitations with one primary action. A user manages *pipelines, stages, rubrics, migrations* — never "jobs", "tasks", or "DAG nodes" in visible copy.

**Quality floor (unannounced):** responsive to 1280px min for app (marketing pages fully responsive), visible keyboard focus (`--beam` 2px ring), WCAG AA contrast, all data tables sortable, all timestamps in user locale.

### shadcn usage
Install shadcn/ui but restyle via tokens — if a screen looks like the shadcn demo (default grays, default radius, Inter), it's wrong. Audit each milestone against this.

## 4. Product Surface (MVP screens)

1. **Pipelines** (home): table of imported pipelines — name, stages, models used (badges), benchmark queries count, last migration parity. Empty state: "Import your first pipeline" + drag-drop zone + link to trace format doc.
2. **Import wizard** (3 steps): upload traces (JSON / Langfuse export) → validation report (per-record errors, downloadable annotated file) → DAG preview for confirmation.
3. **Pipeline canvas**: React Flow DAG. Node = stage card: name, model badge, avg tokens/latency, ParityBeam (after a migration exists). Parallel branches laid out horizontally. Click → Stage drawer.
4. **Rubric review** (HITL step, required before first migration): per stage, plain-English checklist of generated rubric items grouped as *Format checks / Content criteria / Downstream contract*, each editable/deletable, "Add criterion" input. Approve per stage; "Approve all" once reviewed.
5. **New migration wizard**: pick target model per stage (bulk-set + per-stage override; model picker shows cost/1M tokens, context window, JSON-mode/tool-use support from registry) → budget (max optimization spend in $, hard stop) → parity threshold (default 95%) → Run.
6. **Migration run view**: live DAG where stages progress through queued → optimizing (show candidate count + best score climbing) → pass/near/fail, via SSE. Overall progress bar = budget consumed + stages done.
7. **Stage detail drawer** (the money screen): three panes — left: rubric checklist with per-item pass/fail on best candidate; center: benchmark vs candidate output side-by-side with semantic diff highlighting; right: iteration timeline (score per candidate, and the change that caused each jump: "XML format: +11%", "temp 0.7→0.2: +4%").
8. **Scorecard**: Spectral-set big numbers — Parity %, cost delta ₹/$ per 1k queries, latency delta, holdout result ("Validated on 12 unseen queries") — plus per-stage table. Primary action: "Export config" (YAML/JSON of migrated prompts + params). This screen must be screenshot-ready for a funding deck.
9. **Settings**: BYOK keys (per provider, encrypted at rest, never displayed after save), workspace name.

Auth (MVP): email magic-link, single workspace per user. No teams/RBAC yet.

## 5. Build Order & Stop-Gates

**M0 — Scaffold + design system (2–3 days).** Monorepo, docker-compose (postgres/redis/langfuse), FastAPI healthcheck, Vite app with tokens.css, fonts, restyled shadcn Button/Card/Table/Badge/Drawer, `<ParityBeam />` component with Storybook-style demo page at `/dev/kit`. STOP: I review the kit page in browser.

**M1 — Data model + ingest (week 1).** SQLAlchemy models per plan §2 (Pipeline, Stage, BenchmarkSet, Trace, StageRecord, Rubric, Migration, Candidate) + Alembic. Canonical trace JSON schema documented in `docs/trace-format.md` + 3 synthetic fixtures (5-stage sequential; 2 parallel branches; 12-stage mixed-model). `packages/core`: ingest + DAG builder (toposort, parallel-group detection, cycle detection) with tests. API: upload endpoint + validation report. UI: screens 1–3 wired to real data. STOP: import all 3 fixtures through the UI, show canvas screenshots + test results.

**M2 — Rubric engine (week 2).** Core: rubric generator — one strong-model call per stage analyzing that stage's outputs across all traces, emitting structured rubric (deterministic checks / weighted judge criteria / downstream contract) as validated JSON. Evaluator v1: deterministic checks + bge-m3 similarity + pairwise LLM judge with position-swap. API + screen 4 (rubric review, editable). STOP: generated rubrics for the 12-stage fixture shown in UI; I sanity-check quality.

**M3 — Single-stage optimizer (weeks 3–4, the risky core — headless first).** In `packages/core`, CLI-runnable: (a) model-card transform layer (mechanical prompt rewrites per target family, driven by a versioned registry JSON on top of LiteLLM's model data); (b) DSPy MIPROv2 instruction/few-shot loop scored by the evaluator; (c) Optuna grid sweep over temperature × format (XML/JSON/plain) × structured-output mode; (d) budget accounting with hard stop; every call traced to Langfuse. STOP: CLI demo migrating one fixture stage between two real models, showing score climb + spend. No UI this milestone.

**M4 — Full migration run (week 5).** Celery orchestration: Pass 1 teacher-forced per stage in topological order (parallel groups concurrently); Pass 2 end-to-end with new upstream outputs + ripple detector re-optimizing only regressed stages; Pass 3 holdout validation (never optimized against). SSE progress. Screens 5–7. STOP: full migration of the 12-stage fixture watched live in UI.

**M5 — Scorecard + export + auth + deploy (week 6).** Screen 8, YAML/JSON config export, magic-link auth, BYOK settings, docker-compose prod profile, deploy. STOP: end-to-end run on the deployed instance; screenshot pack for the deck.

**Post-MVP backlog (do not build now):** TOON format, call-merging/retrieval optimization, skeptic adversarial agent, drift monitoring subscriptions, teams/RBAC, dark theme, on-prem installer.

## 6. First Command

Begin with M0. Before writing code, post: (1) the exact file tree you'll create, (2) the tokens.css contents, (3) the ParityBeam component API. Wait for my approval, then build M0 only.
