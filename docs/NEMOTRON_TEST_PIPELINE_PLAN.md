# Nemotron End-to-End Test Pipeline — Implementation Plan

Written 2026-07-23 against the real codebase and the real
production traces in `~/Downloads/2026-07-01/*.txt` (25 legal/tax RAG query
logs, already importable via `reprompt_core.importers.query_log`). Read it top to bottom before writing code.

---

## 0. Goal (what "testing pipeline" means here)

Every automated test in this repo today drives the optimizer with a **fake**
`call` callable (see `packages/core/tests/test_optimizer_loop.py`'s
`_make_call`). That proves the *logic* works, but nothing proves the whole
Reprompt flow survives contact with a **real model on real data**.

This task builds exactly that: a **real, runnable end-to-end migration
harness** that takes the real legal/tax production traces (originally run on
expensive **Gemini 3 flash preview**), migrates them to a **free NVIDIA
Nemotron** target, and verifies parity holds across the full pipeline —
import → rubric → contract mining → optimizer → seam regression → results.

It is both a **CI smoke test** (does the real LLM path work end to end?) and
a **demo script** (the "we migrated expensive Gemini → free Nemotron and
parity held" story).

**Non-goal:** this does not replace the unit suites. It is an additive,
opt-in, marked-`slow`/`live` harness that only runs when a real key is
present. The 340/201/153 unit tests must still pass untouched.

---

## 1. My view on Nemotron (the model-choice decision)

**Recommendation: use Nemotron as the primary free target, with Ollama as
the offline fallback.** Reasoning, honestly weighed:

**Why Nemotron is a good pick**
- Genuinely free via NVIDIA's hosted NIM (`build.nvidia.com`) — free credits,
  OpenAI-compatible API.
- Plugs into our stack with **near-zero code**: everything routes through
  LiteLLM (`packages/core/src/reprompt_core/llm/client.py` is the only place
  we touch a provider), and LiteLLM already supports NVIDIA NIM via the
  `nvidia_nim/` prefix. No new SDK, no proxy.
- Nemotron-70B-instruct is a strong instruction-follower — it reliably
  produces the **structured JSON** these stages need (query classification,
  section extraction, etc.), which a weaker free model would fumble.
- Makes a **convincing parity story**: a capable free model matching a paid
  frontier model is a better demo than "cheap model roughly works."

**Costs / caveats (be honest in the demo)**
- The free tier is **rate-limited** — the harness must throttle + backoff, or
  it will 429 mid-run. This is the single biggest implementation risk.
- It is a **cloud** call needing a key (`NVIDIA_NIM_API_KEY`), unlike Ollama
  which is truly local/keyless. So the harness must **skip cleanly** when the
  key is absent (never hard-fail CI on a missing secret).
- Model ids on NVIDIA's catalog shift over time — always **verify the
  exact current model id** (see §3) rather than trusting a hardcoded string.

**Why keep Ollama as fallback:** truly free-forever, no key, no rate limit,
already wired in (`CURATED_MODELS` has `ollama/qwen2.5:14b`). If NVIDIA is
down or unkeyed, the harness runs against local Ollama so it's never fully
blocked. One env var picks which.

---

## 2. What already exists — DO NOT rebuild

Grounded in the actual files. Read these before touching anything.

| Capability | Where | Note for this task |
|---|---|---|
| Query-log trace importer | `packages/core/src/reprompt_core/importers/query_log.py` | **The 25 `.txt` files are already this exact format.** It infers the DAG from consecutive-stage grouping, disambiguates parallel siblings (`#1`,`#2`), handles recurring stage names (`__2`). Do not write a new parser. |
| Importer tests | `packages/core/tests/test_importers_query_log.py` | Shows how the importer is called + asserted. Mirror this. |
| Canonical trace schema | `packages/core/src/reprompt_core/trace.py` (`TraceFile`) | The importer's output. `docs/trace-format.md` documents it. |
| Persist to DB | `apps/api/src/reprompt_api/ingest.py` (`persist_trace_file`) | Turns a `TraceFile` into Pipeline/Stage/Trace rows. |
| The only provider call site | `packages/core/src/reprompt_core/llm/client.py` (`complete`) | Pure LiteLLM. Nemotron plugs in here **by model-string convention only** — no code change to `complete` itself. |
| No-key provider set | `packages/core/src/reprompt_core/llm/registry.py` (`_NO_KEY_PROVIDERS = {ollama, ollama_chat, vllm}`) | NVIDIA NIM **does** need a key, so it is correctly NOT in this set. Confirm registry cost/context lookups degrade gracefully for an unknown NVIDIA id (they already return `None`-ish caps — verify). |
| Curated target models | `apps/api/src/reprompt_api/migrations.py` (`CURATED_MODELS`, line 74) | Nemotron must be **added here** to be selectable as a target and to appear in the model picker. |
| BYOK key → LiteLLM kwarg | `apps/api/src/reprompt_api/llm_context.py` (`complete_with_workspace_credentials`) | Bridges a stored workspace key into the LiteLLM call. Confirm it forwards a key for the `nvidia_nim` provider (it's provider-agnostic today — verify the provider-name derivation handles the `nvidia_nim/` prefix). |
| Full optimizer entry | `packages/core/src/reprompt_core/optimizer/loop.py` (`run_optimizer`) | Drive this with a **real** `call` for the harness. |
| API-shell runner | `apps/api/src/reprompt_api/optimizer_runner.py` (`run_optimizer_for_migration`) | The real DB-backed path a migration takes. The harness can either call this, or call `run_optimizer` directly against imported data. |

**Not present anywhere:** any real-model E2E test, any Nemotron registration,
any throttle/backoff wrapper around `complete`, any "live" pytest marker.

---

## 3. Nemotron integration — the actual code changes

Keep it minimal. Four small edits + one verification.

**3a. Verify the model id + provider wiring (do this FIRST, before coding).**
- Use context7 / LiteLLM docs to confirm the current LiteLLM NVIDIA NIM
  convention. Expected as of writing: provider prefix `nvidia_nim/`, env var
  `NVIDIA_NIM_API_KEY`, base `https://integrate.api.nvidia.com/v1`, and a
  model id along the lines of
  `nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1`.
- Confirm the **exact** available Nemotron id from the NVIDIA catalog — do
  not trust the string above blindly; it changes.
- Write down the confirmed id + env var at the top of the harness file.

**3b. Add Nemotron to `CURATED_MODELS`** (`migrations.py:74`). One line, e.g.
`"nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1"`. This makes it show up
in `get_available_models` / the target picker.

**3c. Verify provider-name derivation** in
`registry.py:_provider_name` and `llm_context.py` handles the `nvidia_nim/`
prefix so `missing_credential_env_vars` reports `NVIDIA_NIM_API_KEY` (not a
wrong var) and the BYOK bridge forwards the key. If the prefix is parsed as
`nvidia_nim`, this likely already works — **add a unit test asserting it**,
don't just eyeball it.

**3d. Add Nemotron to the capability tiers** in
`packages/core/src/reprompt_core/llm/model_select.py`
(`_GENERAL_ANALYSIS_TIERS`) so it can be auto-picked for judge/mutator if
desired — put it in **Tier 2 or 3** (capable free model, not frontier).
Optional but keeps the system-models view honest.

**3e. Throttle/backoff** — the one genuinely new piece of infra. The free
tier will 429. Add a small, opt-in retry-with-backoff wrapper the harness
uses around real calls (or confirm LiteLLM's built-in `num_retries` +
`RateLimitError` handling is enough given our `TransientLLMError` taxonomy in
`client.py`). Do **not** bake aggressive global retries into `complete` — keep
it in the harness so unit-test behavior is unchanged.

---

## 4. The test-pipeline design

**Pick one small trace as the smoke fixture.** The 3-stage files
(`680d95a1-…`, `7ec0b148-…`, `a236b2b1-…`, `72b2c82a-…`) are ideal — short
chain (`determine_query_type` → `extract_sections` → `response_generation`),
fast, cheap, and structurally complete. Use a 3-stager for CI; keep a bigger
one (e.g. a 33-stage file) behind a `--full` flag for the demo.

**Copy the chosen fixtures into the repo** (e.g.
`packages/core/tests/fixtures/query_log/`) — do **not** read from
`~/Downloads` (not portable, not in git, not reproducible on CI). A few MB of
committed fixture is fine; strip to the stages you need if size matters.

**The harness flow (one script/test, top to bottom):**
1. Load a fixture `.txt` → `query_log` importer → `TraceFile`.
2. (API path) `persist_trace_file` into a temp SQLite DB, OR (core path)
   build `StageOptimizationInput`s directly — prefer the **core path** for
   the CI smoke test (no server, no auth), and the **API path** for the full
   demo (exercises the real runner + endpoints).
3. Generate rubrics for each stage with a real model call
   (`rubric_generator`) — or seed minimal rubrics to keep the smoke test
   cheap. Recommend: **seed** for CI, **generate** for demo.
4. Run `run_optimizer(..., strategy="prism", ...)` with a **real** `call`
   that targets Nemotron, and a real `BudgetTracker` with a **small hard
   ceiling** (e.g. $0.50) so a bug can never burn budget.
5. Assert the run **completes**, produces a winner per stage, records spend,
   and (Phase 8) enforces any approved assertions without crashing.
6. (Optional, demo) run seam regression + export the winning config.

**What to assert (parity, not perfection):**
- The pipeline runs to completion with a real model (no exceptions).
- Every stage yields a `best` candidate with a `final_score` in `[0,1]`.
- Aggregate parity ≥ a **loose** threshold (e.g. 0.6) — this is a smoke
  test, not a quality gate; the point is "the real path works," not "Nemotron
  beats Gemini." Document the threshold as deliberately loose.
- Budget was respected (`spent_usd <= ceiling`).

---

## 5. Step-by-step

1. **Verify Nemotron wiring** (§3a) via context7 + NVIDIA catalog. Record the
   confirmed model id + env var. **Gate everything else on this.**
2. **Copy fixtures**: 1 three-stage file (CI) + 1 large file (demo) into
   `packages/core/tests/fixtures/query_log/`.
3. **Register Nemotron** (§3b–3d) + add the provider-derivation unit test.
4. **Add the throttle/backoff** wrapper (§3e).
5. **Write the core-path smoke harness**:
   `packages/core/tests/test_e2e_nemotron.py`, marked
   `@pytest.mark.live` (register the marker in `pyproject.toml`), **skipped
   when `NVIDIA_NIM_API_KEY` is unset**. Core path, seeded rubrics, $0.50
   ceiling, loose parity assert.
6. **Write the API-path demo script**:
   `scripts/demo_nemotron_migration.py` — imports a fixture, persists to a
   temp DB, kicks off a real migration via `run_optimizer_for_migration`,
   prints a readable before/after (Gemini cost vs Nemotron cost, parity per
   stage, winning prompts). This is what you run live in the demo.
7. **Add an Ollama fallback switch**: one env var
   (`E2E_TARGET_MODEL`, default the Nemotron id) so the same harness runs
   against `ollama/qwen2.5:14b` with no key. Document both invocations.
8. **Docs**: a short `docs/E2E_TESTING.md` — how to get a free NVIDIA key,
   which env vars, how to run CI smoke vs full demo, expected output.
9. **DEV_TRACKER.md**: add a dated entry summarizing what landed + test
   counts, same style as the Phase entries.

---

## 6. Guardrails (honor these — same rules as every phase)

- **Headless core:** `packages/core` stays FastAPI/DB-free. The core smoke
  test imports only core. (`client.py`/`loop.py` convention.)
- **Unit suites untouched:** the 340/201/153 fake-`call` tests must still
  pass. The live harness is **additive and skipped-by-default**.
- **Never hard-fail on a missing key:** `@pytest.mark.live` + skip when
  `NVIDIA_NIM_API_KEY` absent. CI without the secret stays green.
- **Hard budget ceiling on every real run** — a bug must never spend real
  money unbounded. `BudgetTracker` is authoritative.
- **Fixtures in-repo**, never read from `~/Downloads` (not reproducible).
- **One clear model id, verified** — no guessing NVIDIA strings.
- Use the `.claude/skills`: `spec-driven-planning` (map every claim to a real
  file — this plan already does), `ponytail` (laziest correct wiring — reuse
  the importer, don't rebuild), `webapp-testing` if the API path grows a UI
  assertion.

---

## 7. Open questions to resolve while building (flag, don't guess)

- Exact current Nemotron model id on NVIDIA NIM (verify live).
- Does `llm_context.complete_with_workspace_credentials` already forward a
  key for a `nvidia_nim/`-prefixed model, or does the provider-name
  derivation need a small tweak? (Add the test; let it tell you.)
- Free-tier rate limit in practice — tune the throttle to it, and note the
  real numbers in `E2E_TESTING.md` so the demo doesn't surprise you.
- For the demo's parity story: run the **same** fixture's original Gemini
  output vs the new Nemotron output through the existing scorer so the
  before/after is measured, not asserted qualitatively.
