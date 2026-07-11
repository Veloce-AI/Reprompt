# Refract

### Change the AI model behind your product without breaking it — and prove it.

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
