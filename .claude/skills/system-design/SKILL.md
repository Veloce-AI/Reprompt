---
name: system-design
description: Architecture principles specific to Reprompt's engine/API/UI split — headless core, additive schema evolution, and decoupling user-facing config from internal harness config. Use when making any backend/data-model decision, not just when explicitly asked for "architecture".
---

# System design discipline (Reprompt-specific)

Reprompt is a 3-layer system — `packages/core` (headless optimization
engine), `apps/api` (FastAPI/SQLAlchemy persistence + orchestration),
`apps/web` (React UI) — and its real architectural decisions are recorded in
`DEV_TRACKER.md`. Read that file's "Current state" and relevant dated
sections before making a design call this skill doesn't cover; don't
re-derive a decision that's already been made and justified there.

## 1. `packages/core` never learns about persistence, HTTP, or the DB

Every optimizer/rubric/judge function in `packages/core` takes plain data in
and returns plain data out, with side effects (LLM calls) happening through
an injected `call` closure the caller controls. `apps/api` is the only layer
allowed to know about SQLAlchemy models, FastAPI routes, or the database.
When a new capability needs "the engine to know X," the actual fix is
almost always "thread X through as a new parameter," never "import a DB
model into `packages/core`." This is not a style preference — every
strategy in `packages/core` is tested standalone, with zero DB/FastAPI
fixtures, and that test discipline breaks the moment the layer boundary
does.

## 2. Schema changes are additive by default

New columns are nullable (or have a safe default) and new JSON-shaped config
fields are optional keys layered onto an existing dict shape, not a
breaking rename or a required field with no migration path for existing
rows. `TargetModelConfig`'s evolution — `{"default", "stages"}` →
`{"models": [...]}` → `{"models": [...], "judge_model": ..., "mutator_model": ...,
"stage_overrides": ...}` — is the model to follow: each step kept every
previously-valid config shape readable (`_get_target_models()`'s
backward-compat branch), so no existing `Migration` row in the DB was ever
silently broken by a later phase. Prefer this over a hard cutover + data
migration unless there's a real reason the old shape must stop existing.

## 3. Decouple "what the user is testing" from "what we use to test it"

This is a hard-learned lesson from a real bug in this codebase: the judge
and mutator (Reprompt's own internal harness — the thing deciding whether a
candidate prompt is good and how to improve it) must never default to
whatever model the user picked as their migration *target*. If the
selection logic for an internal-infrastructure role can silently resolve to
"whatever the user is configuring for their own purposes," that's a
correctness bug waiting to happen, not just here — the same shape of
mistake (an evaluator implicitly depending on the thing it's evaluating)
recurs anywhere a system both configures a user-facing choice and needs an
independent judgment about it. When adding a new "auto-select a model/
resource for internal purpose X," always resolve it from the workspace's
own available-resources pool, explicitly separate from whatever the user
configured for their own comparison/target — and always leave an explicit
override path that "always wins," so an operator can still force a specific
choice when they need to.

## 4. One canonical live-status source, not per-screen duplicates

`Migration.progress_stage_name`/`progress_substep`/`stage_states`/
`activity_log` are computed once, server-side, from the same sequential
optimizer progress fields — every frontend surface (the Migrations tab's
embedded canvas, and now the main Canvas tab too) polls the *same*
`GET .../status` endpoint and derives its view from the *same* payload
shape. Don't invent a second derivation of "is this stage running" in a new
screen — extend the existing status payload if a screen needs one more
field, don't compute a parallel signal.

## 5. Verify a fix against the actual failure mode, not just "tests still pass"

The two most consequential bugs found this project (a divergent Alembic
migration chain that broke the whole app; a CSS flex-height bug that made a
correctly-populated DAG render invisible) were both invisible to their
respective test suites — one because migrations aren't exercised by
`pytest`, one because jsdom doesn't lay out real CSS. When a bug report
contradicts "but the tests pass," the right response is to actually run the
system end-to-end (start the real servers, drive the real UI) before
concluding the report is wrong — not to trust the test suite over a live
reproduction.
