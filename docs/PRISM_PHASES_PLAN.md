# Prism — Remaining Phases Implementation Plan (Phases 3–8 + GEPA)

Written 2026-07-22 against the PDF `reprompt_prism_documentation.pdf`
and the live codebase. Each
phase section is self-contained: what to build, where it lives, the data
model, the API surface, the core logic, the tests, and its dependencies.

Ground truth as of writing: `apps/api` **180 passed**, `packages/core`
**290 passed / 21 skipped**, `apps/web` **153 passed**. Phase 2 (M4 holdout)
is complete.

---

## 0. What already exists (do not rebuild)

Read this first so no phase re-derives infrastructure that is already here.

| Capability | Where | Notes |
|---|---|---|
| Stage DAG (`depends_on` / `dependents`) | `models.py:159-173` (self-ref M2M `stage_dependencies`) | **Phase 4 seam regression uses this directly** — the downstream set is `stage.dependents`. |
| `Stage.source_id` (user's own stage id) | `models.py:141` | Comment literally says *"M5's config export needs to write migrated prompts back out keyed by the user's own stage ids."* **Phase 3 keys export on this.** |
| `Rubric.downstream_contract` (`list[str]` of field names) | `models.py:294`, editable in `rubric-review-panel.tsx:325` | The seam definition. Currently plain field names, **not** executable predicates. |
| `Trace.is_holdout` | `models.py:226` | Already consumed by Phase 2. |
| Three-signal scoring (det 25% / embed 30% / judge 45%) | `scoring.py` — `score_candidate`, `compute_composite_score`, hard-gate on `json_schema` | Reuse for all downstream/seam scoring. Do **not** fork a second scoring path. |
| Position-swapped judge + single-pass judge | `judge.py` — `judge_pairwise`, `judge_single_pass` | Cross-family. Reuse for seam validation ("independent validator, isolated context"). |
| Role separation | `model_select.py` — `select_model(purpose, available, explicit=)`, purposes `rubric_generation`/`judge`/`mutator` | Explicit override always wins. Add new purposes here as needed. |
| Optimizer engine | `packages/core/optimizer/loop.py` — `run_optimizer(strategy="simple"\|"prism")`, shared `run_sweep_for_stage`, injected `call` | GEPA slots in as a third strategy branch. |
| Mutate / critique / refine | `optimizer/mutator.py` — `generate_prompt_mutations`, `critique_and_refine`, `select_few_shot_examples` | Lessons file (Phase 6) feeds into these calls. |
| Local, zero-cost model infra pattern | `embedding.py` (bge-m3, lazy-loaded, test-overridable model name) | **The NLI cross-encoder (Phase 5) copies this exact pattern** — local, no injected `call`, no API key. |
| LLM-derived rubric ("contract v0") | `rubric_generator.py` — one strong-model call → `deterministic_checks` + `judge_criteria` + `downstream_contract` | Phase 5 contract mining is the **evolution** of this, feeding the same rubric structures. |
| API-shell wiring pattern | `optimizer_runner.py` (core stays headless; shell reads DB, builds inputs, persists rows, `on_attempt`/`on_phase` closures) | Every new core capability follows this core/shell split. |
| BYOK creds + Fernet | `llm_context.complete_with_workspace_credentials`, `models.WorkspaceApiKey` | All paid calls route through the workspace-credential closure. |

**Not yet present anywhere:** assertion registry table, feature-flag /
promotion table, lessons store, drift daemon, GEPA backend, NLI model,
any `export` endpoint.

---

## 1. Cross-cutting decisions & conflict flags

These are the places the PDF's vision collides with, or must be reconciled
against, what's already built. Resolve these once, here, so no phase
silently re-decides them.

**D1 — Contract mining augments the rubric generator; it does not replace the scoring path.**
`rubric_generator.py` already produces the exact three structures the
scorer consumes. Phase 5 changes *how invariants are derived* (NLI
semantic-entropy clustering over two-axis samples instead of one LLM call)
but the output still lands as `deterministic_checks` + an **assertion
registry** (new). There must remain exactly one composite-scoring path
(`scoring.py`). Mined invariants become executable checks *inside* that
path, not a parallel evaluator.

**D2 — Assertions are a NEW versioned table, additive to `Rubric`.**
`Rubric.deterministic_checks` is per-stage, unversioned, overwrite-on-
regenerate. The PDF wants "versioned, executable invariants" with stored
counterexamples. That is a new `assertions` table (Phase 5/8), **not** a
mutation of the rubric column. The existing HITL rubric-review flow stays
untouched.

**D3 — Do not change `downstream_contract`'s type.**
It is `list[str]` (field names) today, edited in the rubric UI and used by
Phase 4. Making it structured/executable would break the rubric-review
panel, its API, and its tests. Phase 8's executable seam predicates go in a
**separate** structure (assertion registry rows scoped to a seam), leaving
`downstream_contract` as the human-readable field list it is now.

**D4 — The NLI cross-encoder is local infra, NOT an LLM role.**
It sits beside `embedding.py` (lazy-loaded local model, overridable model
name for tests), does **not** go through the injected `call`, and does
**not** get selected via `model_select.py`. It's PDF tier-1 ("highest
volume, effectively zero marginal cost"). Keep `transformers`/`torch` an
optional/lazy import so the test suite runs without downloading it — mirror
how the embedding tests override `DEFAULT_EMBEDDING_MODEL`.

**D5 — Phase 5 and Phase 8 are two halves of one system.**
Phase 5 = *derive* invariants and store them as assertion specs. Phase 8 =
*run* those specs as predicates inside the optimizer loop with backtracking
+ counterexample capture. Build 5 first (produces data), then 8 (consumes
it). Seam regression (Phase 4) can ship a v1 **before** either, using
embedding+judge parity on the downstream output; it gets sharper once
assertions exist.

**D6 — GEPA is a third `strategy`, not a rewrite.**
`run_optimizer(strategy=...)` already branches simple/prism. GEPA adds a
third branch reusing `run_sweep_for_stage`, the mutator, and the judge. Add
a routing heuristic (example count) in `optimizer_runner.py`, not in core.

**D7 — Governance is last and depends on 4 + 5.**
Promotion gate needs seam + end-to-end regression (Phase 4). Drift daemon
needs contract entropy (Phase 5's NLI clustering). Feature-flag/rollback is
a self-contained table + endpoints that can be built any time but is only
*useful* once regression gates exist.

---

## 2. Phase 3 — Config Export  *(independent, ship first)*

**Goal:** one-click download of the winning migrated config — the migrated
prompt + params per stage, keyed by `Stage.source_id`, so a user can apply
the result to their own pipeline.

**Data model:** none. Pure read over existing `Candidate` rows (same
winner-selection logic as `get_migration_results`).

**API (`apps/api/src/reprompt_api/migrations.py`):**
- `GET /pipelines/{pid}/migrations/{mid}/export` → JSON body:
  ```json
  {
    "migration_id": 12,
    "pipeline_id": 3,
    "generated_at": "2026-07-22T...",
    "stages": [
      {
        "stage_source_id": "classify_risk_flag",
        "stage_name": "Risk Flag Classification",
        "winning_model": "gemini/gemini-2.0-flash-lite",
        "winning_prompt": "…",
        "params": {"temperature": 0.2, "format_mode": "plain"},
        "training_score": 0.91,
        "holdout_score": 0.72
      }
    ]
  }
  ```
- Reuse the exact winner query from `get_migration_results` (`max(candidates,
  key=final)` per `(migration_id, stage_id)`); join `Stage.source_id`.
- Return `Content-Disposition: attachment; filename="reprompt-config-{mid}.json"`
  so the browser downloads it. (FastAPI `Response`/`JSONResponse` with the
  header — no new dependency.)

**Frontend (`apps/web/src/routes/migration-detail.tsx`):**
- "Download winning config" button in the results header. On click, fetch
  the export endpoint and trigger a client-side blob download (no new lib —
  `URL.createObjectURL`). Disable/hide until the migration is terminal and
  has ≥1 result. Follow `saas-product-design` (no dead button on empty
  state).

**Tests:**
- API: export shape, keyed by `source_id`, winner selection matches
  `/results`, 404s for unknown pipeline/migration, empty `stages` when no
  candidates.
- Web: button renders only in terminal state; click calls the endpoint.

**Depends on:** nothing. **Unblocks:** nothing (leaf).

---

## 3. Phase 4 — Seam-Level Regression  *(build v1 before assertions)*

**Goal (PDF §2 Phase 4, §3, §7.4):** after a stage's prompt is migrated,
re-validate every **downstream** stage against the migrated stage's *new*
output — not just re-confirm the upstream stage in isolation. Catches the
"call 19 → call 20 dropped an implicit pre-tax convention" failure class.

**Core (new `packages/core/optimizer/seam.py`, headless):**
- `evaluate_seam(upstream_result, downstream_stage_input, *, call, judge_model, budget) -> SeamResult`
  1. Take the winning upstream prompt's produced output on a benchmark
     trace (re-render + call, or reuse the attempt output if available).
  2. Substitute that new upstream output into the downstream stage's input
     (the downstream stage consumed the *original* upstream output during
     baseline capture; now feed it the *migrated* one).
  3. Run the downstream stage on that seam input, score its output against
     the downstream stage's own baseline output using the **existing**
     `score_candidate` (det + embedding + judge). This is the "independent
     validator with isolated context" — the judge here shares no context
     with the upstream producing call.
  4. Return `SeamResult(upstream_stage_id, downstream_stage_id,
     parity_score, passed, reason)`.
- `SeamResult` / a `run_seam_regression(...)` that walks the dependency
  order (`stage.dependents`) and returns `list[SeamResult]`.
- **v1 metric:** composite parity ≥ `parity_threshold` on the downstream
  output. **v2 (after Phase 8):** also run the seam's executable assertions.

**Wiring: how downstream input gets the upstream output.**
The tricky part. During baseline capture, a `StageRecord` for the
downstream stage has an `input` that already embedded the upstream output.
For v1, the pragmatic approach: identify which `downstream_contract` fields
the downstream stage reads from the upstream stage, and swap those fields'
values in the downstream `input` with the migrated upstream output (or the
relevant extracted field). Document this as the known-approximate seam
model; the exact field-mapping precision improves with Phase 5's mined
field-level contracts. Keep v1 honest about the approximation in the result
`reason`.

**API (`migrations.py`):**
- Seam regression runs as part of the migration (in `optimizer_runner.py`
  after all stages optimize) and its results persist. **New table**
  `seam_results` (migration_id, upstream_stage_id, downstream_stage_id,
  parity_score, passed, reason, created_at) — or persist onto a JSON field
  on `Migration`. Recommend a small table for queryability.
- `GET /pipelines/{pid}/migrations/{mid}/seam-results` → `list[SeamResultOut]`.

**Frontend:** a "Seam checks" section on `migration-detail.tsx` — a small
matrix/list of upstream→downstream pairs with pass/fail + parity, so a
caught seam (à la PDF §7.4) is visible. No blank state: show "No downstream
dependencies for this pipeline" when the DAG is flat.

**Tests:**
- Core: seam pass when downstream output stays in-parity; seam fail when the
  migrated upstream output degrades the downstream output; flat DAG → empty
  result; budget exhaustion mid-walk handled.
- API: seam results persisted + returned; dependency-order traversal.

**Depends on:** DAG (exists), scoring/judge (exists). **Unblocks:** Phase 7
promotion gate (which requires seam pass).

---

## 4. Phase 5 — Contract Mining (NLI + semantic entropy + two-axis)  *(the big one)*

**Goal (PDF §2 Phase 1, §4.1, §4.4):** replace the single-LLM-call rubric
derivation with a sampled, clustered, noise-aware miner that extracts what a
call *invariantly* does, and encode those invariants as executable
assertions.

**5a — Local NLI cross-encoder (`packages/core/nli.py`, new, mirrors `embedding.py`):**
- `entails(premise: str, hypothesis: str) -> float` and/or
  `nli_label(premise, hypothesis) -> Literal["entailment","neutral","contradiction"]`
  using a DeBERTa-class MNLI cross-encoder (e.g.
  `cross-encoder/nli-deberta-v3-base` via `sentence-transformers`
  `CrossEncoder`, or `transformers` pipeline).
- Lazy-load; module-level `DEFAULT_NLI_MODEL`, overridable for tests (copy
  `embedding.py`'s override seam exactly). Optional heavy deps — guard the
  import so the suite runs without the model present (tests inject a fake
  entailment fn, same as embedding tests use a tiny model / monkeypatch).
- Zero FastAPI imports. Does **not** use the injected `call` (D4).

**5b — Semantic-entropy clustering (`packages/core/contract/cluster.py`, new):**
- `cluster_by_meaning(outputs: list[str], *, entails) -> list[Cluster]`:
  bidirectional-entailment clustering (two outputs are in the same cluster
  iff each entails the other, per Kuhn/Farquhar semantic entropy). Pure
  function taking the entailment callable → fully unit-testable with a fake.
- `semantic_entropy(clusters) -> float`: entropy over cluster probabilities
  — the drift signal Phase 7's daemon reads.

**5c — Two-axis sampling (`packages/core/contract/mine.py`, new):**
- `mine_contract(stage_input, *, call, entails, budget) -> MinedContract`:
  - **Axis A (vary context):** run the stage on N different real inputs →
    reveals what *should* vary (signal).
  - **Axis B (repeat identical context):** run the stage K times on the
    *same* input → establishes the noise floor (how much the model
    disagrees with itself when nothing changed).
  - Cluster each axis. An output property that stays invariant across Axis A
    clusters **and** is stable within Axis B (above the noise floor) becomes
    a **contract invariant**. A split that only appears in Axis B is noise,
    not a real branch — do not encode it.
  - Emit invariants as **assertion specs** (structured, executable —
    reusing `deterministic.py` check types where possible: `required_keys`,
    `enum_values`, `regex`, `no_hallucinated_ids`, plus a new
    `cited_figure`-style check if needed for the PDF's "always cites a
    number" example).
- `MinedContract`: `{invariants: list[AssertionSpec], noise_floor: float,
  entropy: float, samples_used: int}`.

**5d — Assertion registry (new table `assertions`, per D2):**
- Columns: `id, stage_id, kind` (deterministic check type or seam),
  `spec` (JSON predicate), `version` (int), `status`
  (`candidate`/`approved`/`retired`), `source`
  (`mined`/`manual`/`counterexample`), `counterexamples` (JSON list),
  `created_at`. Alembic migration.
- Mining writes `status="candidate"` rows; a human approves them (reuse the
  rubric-approval HITL pattern from `rubrics.py`).

**API + shell:**
- `packages/core` stays pure (mining functions take injected `call` +
  `entails`). New shell module `contract_miner.py` (analog of
  `rubric_generator` shell wiring): reads stage records, runs
  `mine_contract` with the workspace-credential closure, persists
  `assertions` rows.
- `POST /pipelines/{pid}/stages/{sid}/mine-contract` → runs mining, returns
  candidate assertions for review.
- `GET /pipelines/{pid}/stages/{sid}/assertions`, approve endpoints
  (mirror rubric approve/approve-all).

**Frontend:** a contract-review surface (extend the existing rubric-review
panel or a sibling): show mined invariants, the noise floor, per-invariant
"approve", so the HITL gate the PDF requires exists.

**Tests:**
- NLI module with a fake entailment fn (deterministic clustering assertions).
- `cluster_by_meaning`: equivalent-meaning outputs cluster together;
  contradictory ones split; entropy computed correctly.
- Two-axis: an Axis-B-only split is correctly classified as noise (not
  encoded); an Axis-A invariant is encoded.
- Assertion persistence + approval flow.

**Depends on:** scoring/deterministic (exists). **Unblocks:** Phase 8
(executable assertions consume these specs), Phase 7 drift daemon (reads
entropy).

---

## 5. Phase 6 — Lessons File  *(independent; wires into mutator)*

**Goal (PDF §5.6):** persist judge critiques as per-model-family "lessons"
and feed them to the mutator on future jobs, so the optimizer stops
rediscovering the same model-family quirks each run (GEPA's reflective-
evolution mechanic).

**Data model (new table `lessons`):**
- `id, model_family` (e.g. `"claude"`, `"gpt"`, `"gemini"` — derive from the
  model string, same family logic `model_card.py` already uses), `lesson`
  (text), `source_migration_id`, `stage_id` (nullable), `created_at`,
  `weight`/`hits` (optional, for ranking). Alembic migration.

**Core:**
- `optimizer/mutator.py`: `generate_prompt_mutations` and
  `critique_and_refine` gain an optional `lessons: list[str] = []` param,
  injected into the mutator system prompt ("Known lessons for this model
  family: …"). Keep it optional so existing callers/tests are unaffected.
- A pure `extract_lesson(judge_result, critique) -> str | None` helper that
  distills a durable, model-family-level rule from a critique (one strong-
  model call, or a heuristic condensation — start heuristic to avoid cost).

**Shell (`optimizer_runner.py`):**
- Before optimizing a stage, load lessons for the target model's family and
  thread them into the mutator calls.
- After a migration, extract lessons from the critiques produced during
  Prism rounds and persist them.

**API:** `GET /settings/lessons` (view/manage), optional delete — this is
memory the user may want to inspect/prune.

**Tests:**
- `extract_lesson` produces/omits sensibly.
- Mutator prompt includes lessons when supplied (assert on the rendered
  mutator prompt).
- Family derivation from model strings.
- Round-trip: a migration writes lessons; a later run reads them.

**Depends on:** mutator (exists). **Unblocks:** nothing hard; improves all
future optimizer runs.

---

## 6. Phase 7 — Governance Plane  *(last; depends on 4 + 5)*

**Goal (PDF §4.1 governance plane, §2 Phase 5):** three-level regression
gate → promotion behind a feature flag → drift daemon that re-triggers the
loop.

**7a — End-to-end regression (core `optimizer/e2e.py`):**
- After call-level (exists) and seam-level (Phase 4), run the *whole*
  pipeline on golden traces with the winning prompts swapped in, score the
  final output parity. `run_e2e_regression(...) -> E2EResult`.

**7b — Promotion gate + feature flags (new table `prompt_deployments`):**
- Columns: `id, pipeline_id, stage_id, migration_id, prompt, model, params,
  state` (`staged`/`live`/`rolled_back`), `flag_key`, `promoted_at`,
  `promoted_by`, `previous_deployment_id` (for rollback). Alembic migration.
- Gate logic: a migration result may be promoted **only** if call-level,
  seam-level, and e2e regression all pass (compliance-critical/pinned
  stages additionally require explicit human sign-off — mirror the rubric
  `approved` gate; PDF §7.1).
- API: `POST …/migrations/{mid}/promote` (stages behind a flag),
  `POST …/deployments/{id}/rollback` (one-click undo → restores
  `previous_deployment_id`), `GET …/deployments`.

**7c — Drift daemon (shell `drift_daemon.py`):**
- Samples live traffic (new `StageRecord`s / traces since last check),
  re-runs Phase 5 clustering against the mined contract, and re-triggers a
  migration job when semantic entropy rises above the mined noise floor.
- Runtime: a scheduled job. Given the current stack has no worker queue,
  start with an on-demand `POST …/check-drift` endpoint + a simple
  interval trigger (document the cron/worker as the productionization step);
  keep the detection logic pure and testable in core.

**Frontend:** deployments view (staged vs live, promote/rollback buttons),
drift status badge. Follow `saas-product-design` for the promotion
confirmation (irreversible-ish action → confirm).

**Tests:**
- E2E regression pass/fail.
- Promotion blocked when any regression level fails; allowed when all pass;
  pinned stage requires sign-off.
- Rollback restores the previous deployment.
- Drift: entropy above noise floor triggers; below does not.

**Depends on:** Phase 4 (seam), Phase 5 (entropy/contract). **Unblocks:**
closes the loop (PDF Phase 5).

---

## 7. Phase 8 — Executable Assertions + Backtracking  *(pairs with Phase 5)*

**Goal (PDF §2 Phase 1 "DSPy Assertions", §4.3):** the mined assertion
specs from Phase 5 become **runnable predicates** enforced inside the
optimizer loop: a failed predicate triggers backtracking (re-mutate with the
failure as context), and the failing case is stored as a counterexample for
future rounds.

**Core (`optimizer/assertions.py`):**
- `run_assertions(output, assertions, *, input) -> AssertionRunResult`:
  evaluate each `AssertionSpec` predicate against a candidate output (reuse
  `deterministic.evaluate_deterministic_checks` for the check-typed ones;
  add the new predicate kinds mined in Phase 5).
- Wire into `run_sweep_for_stage` / the Prism loop: on assertion failure,
  feed the failure into `critique_and_refine` (backtracking = an extra
  targeted refine round driven by the failed predicate), and record the
  failing `(input, output, assertion)` as a counterexample on the
  `assertions` row.
- Counterexamples become future few-shot / mutation context (bootstrapping,
  per PDF).

**API/DB:** append to `assertions.counterexamples`; expose counterexamples
in the contract-review UI.

**Tests:**
- Predicate pass/fail per kind.
- A failing assertion triggers exactly one backtrack refine round (bounded).
- Counterexample persisted and surfaced.
- Assertion enforcement integrates with the existing composite score
  without creating a second scoring path (D1).

**Depends on:** Phase 5 (produces the specs). **Unblocks:** upgrades Phase 4
seam v1 → v2 (seam assertions) and strengthens Phase 7's gate.

---

## 8. GEPA backend  *(optional third optimizer; flagged in PDF §4.3, not in the numbered phases)*

**Goal:** add GEPA (reflective, Pareto-frontier) as a third
`strategy="gepa"` for the example-scarce case (2–10 samples), where the PDF
says it beats MIPROv2/PromptWizard.

**Core (`optimizer/loop.py` + `optimizer/gepa.py`):**
- `_optimize_stage_gepa(...)`: sample trajectories → reflect in natural
  language on failures (reuse the judge for the eval signal, the mutator for
  the reflective update) → maintain a Pareto frontier of candidate prompts
  (score vs cost, or score vs a second objective) instead of a single best →
  final sweep via the shared `run_sweep_for_stage`.
- Add `"gepa"` to the `strategy` Literal and the `run_optimizer` branch.

**Routing (`optimizer_runner.py`):** pick the backend by example count —
GEPA when `len(examples) <= ~10`, Prism/simple otherwise (PDF §4.3
heuristic). Overridable by `OPTIMIZER_STRATEGY`.

**Tests:** frontier maintenance (non-dominated set kept); reflective update
uses the judge signal; example-count routing.

**Depends on:** mutator/judge/sweep (exist). Independent of 4–8; can land
whenever. Recommend **after** Phase 6 (lessons) since GEPA's reflection
benefits from the lessons file.

---

## 9. Recommended build order

1. **Phase 3 — Config export.** Trivial, independent, immediately useful.
2. **Phase 4 — Seam regression v1** (embedding+judge parity). Unblocks
   governance; visible product value.
3. **Phase 5 — Contract mining** (NLI + two-axis + assertion registry). The
   research core; everything downstream sharpens once this exists.
4. **Phase 8 — Executable assertions + backtracking.** Consumes Phase 5;
   upgrades seam v1→v2.
5. **Phase 6 — Lessons file.** Independent; improves every subsequent run
   (do before GEPA).
6. **GEPA backend.** Optional; benefits from lessons.
7. **Phase 7 — Governance plane** (e2e regression → promotion/flags →
   drift daemon). Last; depends on 4 + 5.

## 10. Invariants every phase must honor

- **Headless core:** `packages/core` never imports FastAPI/SQLAlchemy. New
  capability = pure core fn (injected `call`/`entails`) + a thin `apps/api`
  shell that persists. (`optimizer_runner.py` / `rubric_generator.py`
  pattern.)
- **One scoring path:** everything routes through `scoring.py`. No parallel
  evaluator (D1).
- **Additive schema:** new tables, not type changes to `downstream_contract`
  or `deterministic_checks` (D2, D3). One Alembic migration per phase,
  single head.
- **Test side-by-side:** each phase ships with core unit tests (fake
  `call`/`entails`, zero API cost) + API tests + web tests, all three suites
  green before moving on. Use the `.claude/skills` (`ponytail` for laziest
  correct solution, `spec-driven-planning` to map each claim to a real file,
  `saas-product-design` for no-blank-state UX, `webapp-testing` for
  Playwright).
- **Budget honored:** every new paid call records against `BudgetTracker`
  and checks `is_exhausted` (mirror `_evaluate_holdout`).
- **BYOK:** all paid calls go through
  `complete_with_workspace_credentials`.
