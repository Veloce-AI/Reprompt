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

The optimizer uses three distinct model roles. By default the smoke test uses
the same target model for all three (no separate mutator/judge configured):

| Role | Model used | Notes |
|---|---|---|
| **Target / sweep** | `nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1` | The model being migrated to — evaluates each candidate prompt |
| **Mutator** | same target model | Rewrites prompts. Nemotron can't do native JSON mode (see below), so it's driven via prompted-JSON and parsed free-form |
| **Judge** | same target model | Not exercised by the smoke test (empty `judge_criteria`) |

### How `response_format` is handled — the model-agnostic design

Some models (notably NVIDIA NIM's Nemotron) **reject the OpenAI
`response_format` parameter at the API level**, returning a 400
`UnsupportedParamsError` — even though LiteLLM's `get_supported_openai_params`
optimistically reports the `nvidia_nim` provider as supporting it. LiteLLM
answers that question at the *provider* level, but aggregator providers route
many different underlying models through one provider string, and support
varies per model.

The engine handles this **per-call, for every model**, with no per-provider
special-casing in the harness:

1. `reprompt_core.llm.registry.supports_json_mode(model)` returns the *true*
   answer — it consults a small curated override
   (`_MODELS_WITHOUT_JSON_MODE`) for models LiteLLM misreports, on top of
   LiteLLM's own data.
2. Every structured-output call site (mutator, judge, rubric generator, and
   the sweep's `structured_output_mode` candidates) uses
   `registry.json_mode_params(model, schema)`, which spreads
   `{"response_format": schema}` into the call **only** when the model
   genuinely supports it.
3. Models that don't support it still get an explicit "respond with JSON
   only" instruction in the prompt and are parsed free-form —
   `response_format` is *enforcement on top of* that instruction, never the
   only path to JSON.
4. That free-form output is run through `reprompt_core.llm.json_extract`
   before parsing. Models on the prompted-JSON path routinely decorate their
   reply (markdown ```` ```json ```` fences, a preamble like "Here are the
   variants:", or a stray trailing brace) — the extractor strips that and
   returns the first balanced JSON value, so strict `model_validate_json`
   still succeeds. It's a no-op for already-clean native-JSON-mode output.

The upshot: the same test harness runs unchanged against **any** target model
— a JSON-mode model (GPT, Claude, Gemini) uses native structured output; a
model that rejects it (Nemotron) transparently falls back to prompted-JSON.
To add another model that misreports its JSON support, add its string to
`_MODELS_WITHOUT_JSON_MODE` in `registry.py` — no test change needed.

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
