# E2E Testing — Nemotron Migration Harness

This document explains the real end-to-end test and demo harness added for the
Nemotron migration pipeline task. Everything below is additive — the existing
340/201/153 unit tests are unaffected and always run without any API key.

---

## What this is

`packages/core/tests/test_e2e_nemotron.py` is a `@pytest.mark.live` test that:

1. Loads a real 3-stage production trace (Indian Income Tax Act legal/tax RAG pipeline,
   originally run on Gemini 2.5 flash) from `packages/core/tests/fixtures/query_log/`.
2. Imports it via `reprompt_core.importers.query_log` (no new parser — reuses what's built).
3. Runs `run_optimizer` (core path, no DB or API server) with **real** model calls
   targeting **NVIDIA Nemotron** (free hosted model via NVIDIA NIM).
4. Asserts: run completes, every stage has a winner with a `final_score` in `[0,1]`,
   and total spend is within the $0.50 hard ceiling.

`scripts/demo_nemotron_migration.py` is the before/after demo script — same flow but
prints Gemini original cost vs Nemotron optimizer cost, parity per stage, and winning prompts.

---

## Model: NVIDIA Nemotron

| Property | Value |
|---|---|
| LiteLLM model string | `nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1` |
| Provider prefix | `nvidia_nim/` |
| Env var | `NVIDIA_NIM_API_KEY` |
| Default base URL | `https://integrate.api.nvidia.com/v1/` |
| Free tier | Yes — free credits at [build.nvidia.com](https://build.nvidia.com) |
| Rate limit | Yes — free tier is rate-limited; the harness retries with exponential backoff |

To get a free key: go to [build.nvidia.com](https://build.nvidia.com), sign in,
navigate to the Nemotron model page, and click "Get API Key".

---

## Running the tests

### CI smoke test (Nemotron)

```bash
NVIDIA_NIM_API_KEY=nvapi-... uv run pytest -m live -v packages/core/tests/test_e2e_nemotron.py
```

Expected output: 3 stages, each scoring ≥ 0.3 parity, total spend < $0.50, test passes.

### CI smoke test (local Ollama, no key)

```bash
# Pull a model first if you haven't:
ollama pull qwen2.5:14b

E2E_TARGET_MODEL=ollama/qwen2.5:14b uv run pytest -m live -v packages/core/tests/test_e2e_nemotron.py
```

This runs the exact same test but routes to local Ollama instead of NVIDIA NIM.
No key needed, no network cost, but slower and lower quality than Nemotron.

### Full demo script (before/after story)

```bash
# 3-stage trace (fast, default):
NVIDIA_NIM_API_KEY=nvapi-... uv run python scripts/demo_nemotron_migration.py

# 32-stage trace (slower, more impressive for demos):
NVIDIA_NIM_API_KEY=nvapi-... E2E_FIXTURE=0f586e25 uv run python scripts/demo_nemotron_migration.py

# Against local Ollama:
E2E_TARGET_MODEL=ollama/qwen2.5:14b uv run python scripts/demo_nemotron_migration.py
```

### Regular unit tests (unaffected, no key needed)

```bash
uv run pytest packages/core/tests/        # skips live tests automatically
uv run pytest apps/api/tests/
cd apps/web && npm test
```

---

## Rate limit behavior

NVIDIA NIM's free tier will 429 under load. The harness handles this with a
3-attempt exponential backoff wrapper (`_call_with_backoff` in both the test
and demo script):

- Attempt 1: immediate
- Attempt 2: wait 1 second
- Attempt 3: wait 2 seconds, then re-raise as `TransientLLMError`

If you see repeated 429s, wait 30–60 seconds between runs. The free tier
resets quickly; sustained throughput requires a paid API plan.

---

## Fixtures

Two trace files are committed to `packages/core/tests/fixtures/query_log/`:

| File | Stages | Use |
|---|---|---|
| `680d95a1-...txt` | 3 | CI smoke test (fast, cheap) |
| `0f586e25-...txt` | 32 | Full demo (slower, more complete story) |

Both are real production traces from a legal/tax RAG pipeline originally running on
Gemini 2.5 flash. They are committed in the repo so CI is reproducible without
access to `~/Downloads` or any external file share.

---

## Model roles in the harness

The optimizer uses three distinct model roles — do not confuse them:

| Role | Model used | Why |
|---|---|---|
| **Target / sweep** | `nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1` | The model being migrated to — evaluates each candidate prompt |
| **Mutator** | *(fallback — original prompt)* | Nemotron rejects `response_format`; NVIDIA NIM free-tier connections hang before the 8b mutator can be used reliably. The optimizer falls back to using the original prompt, which the smoke test handles gracefully. For real migrations, configure a cloud mutator (e.g. `claude-haiku-4-5` or `gpt-4o-mini`). |
| **Judge** | `nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1` | Scores candidate outputs — Nemotron handles this without structured output |

Nemotron works fine as target and judge. It cannot be the mutator because mutation requires the model to return a strictly-typed JSON schema (`_RawMutationOutput`), and NVIDIA NIM rejects the `response_format` parameter for this model. Ollama's `qwen2.5:14b` handles mutation locally with no API cost or key.

---

## What the parity score means

The `final_score` reported per stage is a weighted composite:
- **Embedding similarity** (0.30 weight): how similar the Nemotron output is to the
  original Gemini output, measured by a local sentence-transformer model.
- **Deterministic checks** (0.25 weight): passes/fails of any structural checks
  (required JSON keys, regex patterns, enum values). The CI smoke test seeds an
  empty check list, so this is vacuously 1.0.
- **Judge** (0.45 weight): not called in the CI smoke test (empty `judge_criteria`),
  so this is omitted — the composite is embedding + deterministic only.

A `final_score` ≥ 0.3 is the CI gate, which is deliberately loose. The real parity
story for the demo is: "Nemotron output is semantically similar to expensive Gemini
output at a fraction of the cost (or free)." For a tighter quality gate, add
`judge_criteria` to the rubric and set a higher threshold.
