<div align="center">
<img src="docs/logo.svg?v=2" width="80" height="80" alt="Reprompt logo" /><br/>

# Reprompt

**Change the AI model behind your product without breaking it — and prove it.**

*by [Veloce AI](https://veloceai.in/)*

![Status](https://img.shields.io/badge/status-in%20development-4C5FE8)
![License](https://img.shields.io/badge/license-proprietary-8B5CF6)
![Python](https://img.shields.io/badge/python-3.12-14B8A6)
![Frontend](https://img.shields.io/badge/frontend-React%20%2B%20TypeScript-4C5FE8)

Migrates multi-stage LLM pipelines to cheaper or on-prem models, and proves
the outputs still match — no manual prompt rewriting, no guessing.

[What it does](#what-reprompt-does) · [How the search works](#how-the-try-it-until-it-matches-step-actually-works) · [What's built](#whats-built-so-far) · [How to run it](#how-to-run-it--try-it-yourself)

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

## What Reprompt does

You give Reprompt real examples of your pipeline running (what went in,
what came out, at every step). Reprompt:

1. **Learns what "a good answer" looks like** for each step, from your own examples.
2. **Tries the cheaper model** with different prompts/settings until it matches.
3. **Checks the match three ways**: rule-based checks (free, fast), an AI
   judge comparing old vs. new answers, and a similarity score.
4. **Proves it** on examples it never used while searching — no cheating.
5. **Hands you back**: the new working prompts + a scorecard (accuracy kept,
   cost saved, speed change) you can show anyone.

You never touch a prompt by hand. You pick the model, Reprompt does the rest.

## How the "try it until it matches" step actually works

Step 2 above ("tries the cheaper model with different prompts/settings")
is the interesting part — here's what's actually happening under it.

### Two search methods, picked by a setting

| Method | What it does | Good for |
|---|---|---|
| **Simple** | Asks an AI to rewrite the prompt once, then tries a handful of settings (temperature, output format) around it. | Fast, cheap, the default. |
| **Prism** — a self-evolving prompt optimizer | Evolves the prompt through several rounds before locking in a winner: rewrites it, tries it, looks at *exactly why* the weak attempts fell short (which checks failed, how different the answer was, an AI judge's own reasoning), asks the AI to fix those specific problems, then tries again — up to 3 rounds. | Harder migrations where a single rewrite isn't enough — a couple of rounds of "try → see what's wrong → fix it" beats guessing blindly, for far less cost than trying hundreds of random variations. |

Both are 100% our own code, calling any AI provider the same way — see
["What it's built with"](#what-its-built-with) below. **Prism evolves within
one migration, not across migrations** — each migration starts from scratch
and refines its own prompt during that run; nothing it learns carries over
to the next migration yet.

### How it knows when to stop (loop engineering)

> Reprompt never runs longer or costs more than it has to.

- **Hard dollar ceiling.** Every migration has a real budget; once real
  spend hits it, Reprompt stops trying — no surprise bills.
- **Plateau detection.** Prism also stops refining one specific attempt
  early the moment a round stops actually improving it, instead of
  burning budget chasing a dead end that's already plateaued.

### How it stays reliable (harness engineering)

> Reprompt never just believes what an AI model says back.

Every AI response — not just prompt rewriting, everywhere Reprompt asks a
model to do something — is checked against a strict, validated shape
before it's trusted. A malformed response gets exactly one automatic
retry with a note about what went wrong, then a clear failure instead of
silently corrupting the next step.

### Why we built our own instead of using an existing framework

We studied how similar published approaches work (mainly Microsoft's
PromptWizard, for the "look at what went wrong and fix it" idea) and
built our own version on top of it — one that works with **any** AI
provider, including running entirely on your own servers, instead of
being locked to one the way the original is. Full reasoning and
technical detail: `DEV_TRACKER.md`.

## What's built so far

| Piece | Status |
|---|---|
| Import your pipeline's data | ✅ Working |
| Understand the pipeline structure (steps, order, parallel steps) | ✅ Working |
| Learn "what good looks like" per step | ✅ Working |
| Score an answer 3 ways (rules / AI judge / similarity) | ✅ Working |
| Review screens (see your pipeline, review what Reprompt learned) | ✅ Working |
| Log in, save your API keys securely | ✅ Working |
| **The actual "try the cheaper model until it matches" search** | ⚙️ Engine built + tested, not wired into the app yet — see below |
| Final report screen | 🚧 Waiting on the above |

See `docs/DEVELOPMENT.md` for the exact list of what's left and in what
order, and `DEV_TRACKER.md` for the detailed, actively-updated
phase-by-phase status of the optimizer (M3) work specifically.

## How to run it / try it yourself

First time, from the repo root: `bash scripts/setup.sh` — installs
everything, creates a local database, and generates a key for encrypted
API-key storage. **No Postgres/Docker needed** — SQLite is the default
and all you need for local dev; Postgres is optional (see
`docs/DEVELOPMENT.md` if you specifically want it). Then:

- **First time setup + running it, step by step**: `docs/TESTING.md`
- **Day to day**: `bash start.sh` opens the backend and frontend each in
  their own terminal window (closing a window stops that one); `bash
  stop.sh` stops both from wherever you are, Windows-specific process
  quirks and all handled for you.
- **Full technical plan**: `docs/DEVELOPMENT.md`
- **Detailed, current build status of the optimizer**: `DEV_TRACKER.md`
- **The exact data format it expects**: `docs/trace-format.md`

### Getting an AI model API key

Reprompt needs at least one AI model API key to run rubric generation, the
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
