# Reprompt — Model Migration Parity Engine
### Benchmark-anchored, self-iterating system for migrating multi-stage LLM pipelines to new/cheaper/on-prem models

---

## 1. Problem Statement (crisp version)

Enterprises run pipelines of N LLM calls (5–50), mixed models, sequential + parallel, with inter-stage dependencies. Swapping any model breaks output parity because prompts/params/formats are model-specific. Manual re-tuning of 35 stages is weeks of work per migration.

**Product promise:** "Import your pipeline traces. Pick target models. Get back migrated prompts + params proven equivalent against your own benchmark — with a cost/latency/parity scorecard."

---

## 2. Core Concepts & Data Model

```
Pipeline
 └── Stage[]            (id, name, depends_on[], model, prompt_template,
                         params{temp, top_p, max_tokens, format_mode, ...})
Pipeline has:
 └── BenchmarkSet       (20–100 Queries; split: optimize 80% / holdout 20%)
      └── Trace[]       (one per query: full DAG execution)
           └── StageRecord (input, rendered_prompt, output,
                            tokens{in, out, thinking}, latency_ms)
Stage has:
 └── Rubric             ← THE "REASON COLUMN", structured
      ├── deterministic_checks[]   (json_schema, required_keys, regex,
      │                             length_bounds, enum_values, no_hallucinated_ids)
      ├── judge_criteria[]         (weighted; e.g. "covers entities X,Y",
      │                             "tone: formal", "no info beyond context")
      └── downstream_contract      (what the NEXT stage actually consumes —
                                    the only fields that truly matter)
Migration
 └── target_model per stage (or global), budget, parity_threshold
      └── Candidate[] per stage   (prompt_variant, params, format,
                                   scores{deterministic, judge, embedding_sim},
                                   cost, latency)
      └── Result: migrated config + scorecard
```

**Key insight on rubrics:** the `downstream_contract` is what saves you. Stage 14's output doesn't need to be *identical* to benchmark — it needs to be equivalent *in the fields stage 15 consumes*. This dramatically loosens the search and is something naive output-diffing tools miss.

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  INGEST LAYER                                               │
│  Langfuse export / OTel traces / raw JSON / manual upload   │
│  → Normalizer → Pipeline DAG + BenchmarkSet in Postgres     │
├─────────────────────────────────────────────────────────────┤
│  RUBRIC ENGINE (LLM-powered, runs once per stage)           │
│  Analyzes benchmark outputs across all traces →             │
│  emits deterministic checks + judge criteria +              │
│  downstream contract. Human can edit in UI (HITL).          │
├─────────────────────────────────────────────────────────────┤
│  MODEL CAPABILITY REGISTRY                                  │
│  Base: LiteLLM model_prices_and_context_window.json         │
│  + custom layer: format preference (XML/MD/JSON), param     │
│  support matrix, JSON-mode/tool-use support, known quirks,  │
│  prompting-guide transforms per model family                │
├─────────────────────────────────────────────────────────────┤
│  OPTIMIZATION ORCHESTRATOR (custom, Celery workers)         │
│  Pass 1 — Teacher-forced, per stage, topological order      │
│    (independent branches run in parallel):                  │
│    a. Apply model-card transforms (mechanical rewrite:      │
│       e.g. XML tags for Claude, markdown headers for        │
│       Gemini, terse system prompts for nano models)         │
│    b. DSPy MIPROv2 inner loop: instruction + few-shot       │
│       optimization against rubric score                     │
│    c. Param/format sweep: temp × format(XML/JSON/TOON/      │
│       plain) × structured-output-mode (cheap grid or        │
│       Bayesian via Optuna)                                  │
│    d. Select best candidate ≥ parity_threshold or best      │
│       within budget                                         │
│  Pass 2 — End-to-end validation:                            │
│    Run full DAG with NEW upstream outputs flowing down.     │
│    Ripple detector flags stages whose score dropped →       │
│    targeted re-optimization of only those stages.           │
│  Pass 3 — Holdout validation (untouched 20% of queries)     │
│    → final parity score. No optimization here, ever.        │
├─────────────────────────────────────────────────────────────┤
│  EVALUATION ENGINE                                          │
│  Score = w1·deterministic + w2·LLM-judge + w3·embedding-sim │
│  Judge: pairwise comparison (benchmark vs candidate),       │
│  position-swapped to kill order bias, strong model as       │
│  judge (BYOK). Deterministic checks are free — run first,   │
│  gate before spending judge tokens.                         │
├─────────────────────────────────────────────────────────────┤
│  EXECUTION LAYER                                            │
│  LiteLLM router → 100+ providers + on-prem (Ollama/vLLM)    │
│  All runs traced to self-hosted Langfuse                    │
├─────────────────────────────────────────────────────────────┤
│  UI (React) — see §5                                        │
└─────────────────────────────────────────────────────────────┘
```

**Stack:** Python FastAPI · Postgres · Celery + Redis · DSPy · LiteLLM · Optuna · Langfuse (self-host) · React + Tailwind. (Same stack as original Reprompt plan — nothing wasted.)

---

## 4. Why hybrid harness instead of pure DSPy / pure loop

| Concern | Pure DSPy | Pure custom loop | Hybrid (chosen) |
|---|---|---|---|
| Prompt/few-shot search | ✅ excellent (MIPROv2) | ❌ reinventing | ✅ DSPy inner |
| DAG orchestration, parallel stages | ❌ | ✅ | ✅ custom outer |
| Param sweeps (temp, format) | ❌ weak | ✅ | ✅ Optuna |
| Ripple / end-to-end repair | ❌ | ✅ | ✅ custom Pass 2 |
| Cost control / budgets | ❌ | ✅ | ✅ outer loop owns budget |

Also apply your skeptic-agent pattern from the code review tool: a **skeptic judge** that tries to find cases where the "converged" candidate fails (adversarial query perturbations from the benchmark set). Cheap, differentiating, reuses your architecture thinking.

---

## 5. UI Spec (non-technical-friendly)

**Screen 1 — Pipeline Canvas.** DAG of stages (React Flow). Each node: stage name, model badge (before → after), parity chip (🟢 ≥95% / 🟡 80–95% / 🔴 <80%), cost delta. A CFO can look at this and get it.

**Screen 2 — Stage Detail.** Three-pane:
- Left: rubric as a plain-English checklist ("✔ Returns valid JSON with 4 keys · ✔ Mentions all product names from input · ✘ Tone: matched 7/10 traces"). Editable — human corrections feed back into optimization.
- Center: side-by-side benchmark vs candidate output with inline semantic diff (highlight *meaningful* differences, not whitespace).
- Right: iteration timeline — score climbing per candidate, with the prompt/param change that caused each jump ("Switched to XML format: +11%").

**Screen 3 — Migration Scorecard.** Big numbers: Parity 96.4% · Cost −71% (₹4.20 → ₹1.22 per query) · Latency −38% · Holdout validated on 20 queries. Export button → migrated config as YAML/JSON (prompts + params per stage), drops straight into their codebase.

**Screen 4 — Format Lab** (your Phase 1.3): per-stage bar chart of XML vs JSON vs TOON vs plain-text score for the target model. This screen alone is shareable marketing content.

Langfuse stays as the raw-trace power-user view (embed/link), but your UI is the product — don't make customers learn Langfuse.

---

## 6. Handling your specific requirements

- **35 mixed-model calls:** each stage carries its own source + target model; global "migrate everything to X" is just a bulk-set.
- **Model cards:** registry layer, versioned; transforms encoded as rewrite rules per model family (community-contributable later = moat).
- **Context window minimization (Phase 1.2):** an optimization *objective*, not a separate phase — add token count as a penalty term in the candidate score. The loop will naturally compress prompts.
- **Retrieval optimization / call-merging (Phase 2):** the DAG + downstream contracts give you this for free later: if stage A's output is fully contained in stage B's contract and both hit the same model, propose a merged call and test it through the same parity loop. Great v2 feature; skip for MVP.
- **Graphify/Obsidian:** skip. React Flow covers DAG viz; Obsidian doesn't belong in a SaaS runtime. Don't add surface area.

---

## 7. MVP Scope (4–6 weeks, solo + Claude Code)

**Week 1–2:** Trace ingest (Langfuse export + raw JSON schema you define) → Postgres data model → DAG builder. Rubric engine v1 (single strong model generates rubric; JSON schema output).
**Week 3–4:** Single-stage optimization loop: model-card transform + DSPy MIPROv2 + temp/format sweep + pairwise judge. CLI-first, results in DB.
**Week 5–6:** Pass 2 ripple repair + minimal UI (Canvas + Stage Detail + Scorecard) + config export.

**Cut from MVP:** call merging, TOON support (XML/JSON/plain is enough), multi-tenant auth, Optuna (grid sweep is fine at this scale), skeptic agent.

**Fundable milestone:** one real pipeline (use UVA's 20-stage valuation pipeline as your own dogfood case — it's literally the ideal test subject) migrated from frontier models to Gemini Flash-Lite/Gemma with ≥95% parity and a cost-reduction number you can put in a deck. That's your pilot story for Startup India Seed Fund alongside the code review tool.

---

## 8. SaaS Positioning

- **Wedge:** "Cut your LLM bill 60–80% without quality loss — proven against your own outputs." Cost reduction sells itself; on-prem migration (sovereignty) is the enterprise upsell, consistent with the VeloceAI Sovereign framing.
- **Pricing:** per-migration project (₹/$ fixed) + platform subscription for continuous re-validation ("model drift monitoring" — rerun holdout weekly, alert on parity drop → recurring revenue, not one-shot).
- **Competition check:** DSPy/promptfoo/Langfuse are components, not products for this. Closest adjacents: prompt-optimization tools (PromptLayer, Vellum) — none anchor on *benchmark parity for whole-pipeline migration*. Validate this with a search before the deck.
- **BYOK everywhere** — you never hold customer model keys or data at rest longer than the run (on-prem tier: fully air-gapped, same as code review tool).

---

## 9. Claude Code Kickoff Prompt

Paste into Claude Code after creating the repo (use your universal CLAUDE.md too):

```
You are building "Reprompt", a model-migration parity engine. Read this
plan file fully before writing code: docs/reprompt-parity-engine-plan.md

MVP scope only (§7). Stack: Python 3.12, FastAPI, Postgres (SQLAlchemy +
Alembic), Celery + Redis, LiteLLM, DSPy, pytest. No UI yet — CLI + API.

Milestone 1 (do this first, nothing else):
1. Define Pydantic models + SQLAlchemy tables for: Pipeline, Stage,
   BenchmarkSet, Trace, StageRecord, Rubric, Migration, Candidate —
   exactly per §2 of the plan.
2. Ingest command: `reprompt ingest <traces.json>` accepting a raw JSON
   format (design the schema, document it in docs/trace-format.md, and
   generate 3 synthetic example files: a 5-stage sequential pipeline, a
   pipeline with 2 parallel branches, and a 12-stage mixed one).
3. DAG builder with topological sort + parallel-group detection + cycle
   detection. Unit tests for all three synthetic pipelines.
Stop after Milestone 1 and show me the trace format doc + test results
before proceeding. Work in small, explicitly scoped file-creation steps.
```

---

## 10. Open Questions (decide before Week 3)

1. Judge model default: Claude Sonnet vs GPT class — run a 10-sample calibration on your own data; pairwise + position-swap regardless.
2. Embedding similarity model: local (bge-m3) keeps on-prem story clean.
3. Trace format: design your own canonical JSON, treat Langfuse/OTel as importers into it — don't marry Langfuse's schema.
4. Name: "Reprompt" still fits (reprompting a pipeline through a new model). Check domain/trademark before public repo.
