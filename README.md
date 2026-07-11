# Refract

**Migrate multi-stage LLM pipelines to cheaper or on-prem models — with proof they still work.**

## What and why

Companies run pipelines of 5–50 chained LLM calls (mixed models, sequential
+ parallel). Swapping any model to save cost breaks output quality, because
prompts are tuned per-model. Manually re-tuning a 30-stage pipeline takes
weeks. Refract automates it: import your pipeline's real traces, it learns
what "good" looks like per stage, then searches for prompts/settings on your
target model until outputs match your original — proven on held-out data,
not just claimed.

**Output:** a migrated config + a scorecard (parity %, cost delta, latency
delta) you can hand to a buyer or a CFO.

## How it works, in short

```
Import traces → generate a rubric per stage (what "good" means)
             → search for a matching prompt/config on the new model
             → score candidates (rule checks + AI judge + similarity)
             → pick the best one within budget
             → prove it on data never used during search
             → export the migrated config + scorecard
```

## Structure

```
apps/api/       Backend (Python, FastAPI) — imports, evaluates, serves the UI's data
apps/web/       Frontend (React) — the actual product screens
packages/core/  The engine — schema, evaluation, optimization logic.
                No web framework code; runs standalone/headless too.
docs/           How to run it, the trace format spec, what's built vs. not
```

## Core modules (`packages/core`)

- **trace** — the canonical format any pipeline's data gets converted into
- **dag** — figures out which stages run in what order / in parallel
- **importers** — converts a real product's export into the canonical format
- **deterministic** — free, rule-based output checks (required fields, format, etc.)
- **embedding** — local similarity scoring between two outputs (no API key)
- **judge** — AI-judged comparison between original and candidate output
- **scoring** — combines all three checks above into one score
- **rubric_generator** — asks a model to write the "what good looks like" checklist per stage
- **llm** — talks to any model provider (OpenAI/Anthropic/Gemini/local) through one interface
- **sweep / budget / selection** — the search: try variations, track spend, pick a winner

## Tech

- **Backend:** Python, FastAPI, SQLAlchemy, Alembic, LiteLLM (any model provider)
- **Frontend:** React, Vite, TypeScript, TanStack Query/Router, React Flow
- **Data:** SQLite (dev), Postgres-ready
- **Evaluation:** local embeddings (bge-m3), LLM-as-judge, Optuna for search

See `docs/DEVELOPMENT.md` to run it, `docs/TESTING.md` to click through it,
`docs/trace-format.md` for the data format.

## Status

Import, evaluation engine, and the review/config screens are built and
tested. The actual optimization search loop (the core "try it and prove
it" step) is the next piece — see `docs/DEVELOPMENT.md` for the exact plan.
