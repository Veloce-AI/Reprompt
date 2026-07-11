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

See `docs/DEVELOPMENT.md` for the exact list of what's left and in what order.

## How to run it / try it yourself

- **First time setup + running it**: `docs/TESTING.md`
- **Full technical plan**: `docs/DEVELOPMENT.md`
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

| Part | Tech |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy |
| Frontend | React, TypeScript, Vite |
| Talking to AI models | LiteLLM — one interface, works with OpenAI, Anthropic, Gemini, or a model running on your own servers |
| "Does this answer make sense" scoring | A local similarity model (no API key needed) + an AI judge |
| Database | SQLite for now, works with Postgres too |

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
