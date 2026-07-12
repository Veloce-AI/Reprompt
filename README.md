<div align="center">
<img src="docs/logo.svg" width="80" height="80" alt="Refract logo" /><br/>

# Refract

**Change the AI model behind your product without breaking it — and prove it.**

*by [Veloce AI](https://veloceai.in/)*

![Status](https://img.shields.io/badge/status-in%20development-4C5FE8)
![License](https://img.shields.io/badge/license-proprietary-8B5CF6)
![Python](https://img.shields.io/badge/python-3.12-14B8A6)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20TypeScript-4C5FE8)

Migrates multi-stage LLM pipelines to cheaper or on-prem models, and proves
the outputs still match — no manual prompt rewriting, no guessing.

[What it does](#what-refract-does) · [What's built](#whats-built-so-far) · [How to run it](#how-to-run-it--try-it-yourself)

</div>

---

## The problem, in plain words

Say your product asks 20 different questions to an AI model, one after
another, to answer one user query (classify → search → summarize →
write the answer, etc). That costs money — every one of those 20 calls
is a paid API call.

You want to switch to a cheaper AI model to save money. But if you just
swap the model, the answers often get worse, because every one of those
20 prompts was written and tuned for the *old* model.

Fixing this by hand — rewriting 20 prompts, testing them, checking nothing
broke — takes a team weeks per product.

## What Refract does

You give Refract real examples of your pipeline running (what went in,
what came out, at every step). Refract:

1. **Learns what "a good answer" looks like** for each step, from your own examples.
2. **Tries the cheaper model** with different prompts/settings until it matches.
3. **Checks the match three ways**: rule-based checks (free, fast), an AI
   judge comparing old vs. new answers, and a similarity score.
4. **Proves it** on examples it never used while searching — no cheating.
5. **Hands you back**: the new working prompts + a scorecard (accuracy kept,
   cost saved, speed change) you can show anyone.

You never touch a prompt by hand. You pick the model, Refract does the rest.

## How the "try it until it matches" step actually works

Step 2 above ("tries the cheaper model with different prompts/settings")
is the interesting part. In plain words:

- **Two ways to search for a better prompt**, picked by a setting, not
  hardcoded: **simple** just asks an AI to rewrite the prompt once, then
  tries a handful of settings (temperature, output format) around it.
  **Prism** is smarter: it rewrites the prompt, tries it, looks at
  *exactly why* the weak attempts fell short (which checks failed, how
  different it was from your original answer), and asks the AI to fix
  those specific problems — then tries again. A couple of rounds of
  "try, look at what went wrong, fix it" beats guessing blindly, and
  costs a lot less than trying hundreds of random variations.
- **It knows when to stop.** Refract tracks real spend as it goes and
  has a hard dollar ceiling per migration — it never keeps trying once
  that's hit. Prism also stops refining a specific attempt early if a
  round didn't actually improve it, instead of wasting money chasing a
  dead end.
- **Every AI call is double-checked before it's trusted.** Refract never
  just believes what a model says back — every response is checked
  against a strict, validated shape, and if it comes back malformed, it
  gets one automatic retry with a note about what went wrong before
  giving up. This applies everywhere Refract asks an AI to do something,
  not just prompt rewriting.

We built this ourselves rather than adopting an existing framework —
studied how similar published approaches work (mainly Microsoft's
PromptWizard, for the "look at what went wrong and fix it" idea), then
built our own version that works with any AI provider (including
running entirely on your own servers) instead of being locked to one.
See `DEV_TRACKER.md` for the full reasoning and technical detail.

## What's built so far

| Piece | Status |
|---|---|
| Import your pipeline's data | ✅ Working |
| Understand the pipeline structure (steps, order, parallel steps) | ✅ Working |
| Learn "what good looks like" per step | ✅ Working |
| Score an answer 3 ways (rules / AI judge / similarity) | ✅ Working |
| Review screens (see your pipeline, review what Refract learned) | ✅ Working |
| Log in, save your API keys securely | ✅ Working |
| **The actual "try the cheaper model until it matches" search** | 🚧 Not built yet |
| Final report screen | 🚧 Waiting on the above |

See `docs/DEVELOPMENT.md` for the exact list of what's left and in what
order, and `DEV_TRACKER.md` for the detailed, actively-updated
phase-by-phase status of the optimizer (M3) work specifically.

## How to run it / try it yourself

- **First time setup + running it**: `docs/TESTING.md`
- **Full technical plan**: `docs/DEVELOPMENT.md`
- **Detailed, current build status of the optimizer**: `DEV_TRACKER.md`
- **The exact data format it expects**: `docs/trace-format.md`

### Getting an AI model API key

Refract needs at least one AI model API key to run rubric generation, the
AI judge, and test migrations. It works with any provider (OpenAI, Anthropic,
Gemini, NVIDIA NIM, or a local model) — this project currently develops
against **NVIDIA NIM**, since it gives free access to strong open models
like Nemotron:

1. Go to [build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b](https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b)
2. Sign in (or create a free NVIDIA account)
3. Click **Get API Key** and copy it (starts with `nvapi-...`)
4. Add it either:
   - as an environment variable — `NVIDIA_NIM_API_KEY=nvapi-...` in a local
     `.env` file (never committed — see `.gitignore`), or
   - in the app itself, via **Settings → API Keys** once you're logged in
     (stored encrypted per-workspace, never in plaintext or in git)

Never commit a real key to git or paste it into a prompt/chat.

## What it's built with

| Part | Tech | What it's actually for |
|---|---|---|
| Backend framework | Python 3.12, FastAPI | HTTP API layer (`apps/api`) |
| Backend data | SQLAlchemy, Alembic | ORM + versioned schema migrations. SQLite for now, works with Postgres too — nothing in the schema is SQLite-only |
| Core engine | Python, zero FastAPI imports | `packages/core` — the pipeline/scoring/optimizer logic, kept runnable headless (CLI, tests, no web server needed) |
| Validation & data shapes | Pydantic v2 | Every internal data shape (trace schema, rubric checks, scoring results, optimizer types) is a typed, validated Pydantic model — not a loose dict |
| Talking to AI models | LiteLLM | One call interface that works with OpenAI, Anthropic, Gemini, or a self-hosted model (Ollama/vLLM/etc.) — nothing in the codebase special-cases a provider |
| Secrets at rest | `cryptography` (Fernet) | Encrypts each workspace's saved API keys in the database — never stored in plaintext |
| "Does this answer make sense" scoring | Rule-based checks (deterministic, free) + a local similarity model (`bge-m3` via `sentence-transformers`, no API key needed) + an AI judge (pairwise, bias-controlled) | The three-way scoring described above |
| Parameter search | Optuna | Searches the *numeric/categorical* knobs around a prompt (temperature, output format, structured-output mode) — not prompt text itself. Currently plain grid search, deliberately routed through Optuna's API so it can swap to a smarter search strategy later without changing the calling code |
| Prompt mutation | In-house (own code, no external framework) | An LLM proposes rewritten prompt variants; see `DEV_TRACKER.md` for the two strategies (simple one-shot vs. Prism's multi-round critique-and-refine) |
| Frontend framework | React, TypeScript, Vite | `apps/web` |
| Frontend data/routing | TanStack Query, TanStack Router | Server-state caching + client-side routing |
| Pipeline visualization | React Flow | Renders the DAG canvas (stages, dependencies, parallel groups) |

See `DEV_TRACKER.md` for a running note of *why* certain tools were or
weren't used (e.g. why Optuna and not a genetic/DSPy-based search for
prompt mutation) — kept there rather than duplicated here since it
changes as decisions get made.

## Folder structure

```
apps/api/       The backend server
apps/web/       The website / product UI
packages/core/  The actual "brain" - the logic above lives here, kept
                separate so it can run on its own, not tied to the web app
docs/           Everything else - how to run it, the data format, the plan
```

## License

Proprietary — Veloce AI. All rights reserved. See `LICENSE`.
