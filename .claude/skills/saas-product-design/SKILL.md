---
name: saas-product-design
description: Production-SaaS UX discipline for Reprompt — empty states, discoverability, live-status visualization, and settings/config screens. Use when building or reviewing any user-facing screen, not just when explicitly asked for "UI work".
---

# SaaS product design discipline (Reprompt-specific)

Reprompt is a real product, not a demo. A screen that is technically correct
but reads as broken to a real user is a bug, not a nitpick — this project has
hit this exact class of bug multiple times (an empty-looking Settings page
that was actually working but had no empty-state messaging; a live DAG that
had 100% correct data but a CSS layout bug made it render at `height:0px`;
rename that only worked via an undiscoverable click-the-text affordance with
no visible button). Treat "does this look broken" as seriously as "is this
correct."

## 1. No screen may render with zero explanation

Every state a screen can be in — no data yet, loading, zero results after a
real query, error, unauthenticated — must say what's happening and, where
possible, what to do about it. A blank `<div>` is never an acceptable end
state. Concretely for Reprompt:
- Zero BYOK keys configured → Settings' "Configured models" must say so and
  point at the add-key form, not just show an empty list.
- No migration run yet → the Migrations tab shows the wizard prominently,
  not a quiet empty area someone has to go looking for.
- A pipeline with no stages/traces yet → say so, don't render an empty grid.

## 2. Every destructive or identity-changing action needs an explicit, visible affordance

Click-to-edit-the-text-directly patterns are fine as a *shortcut* but must
never be the *only* way to trigger the action — pair every inline-edit with
a visible icon button (pencil next to trash, same size/spacing/icon-set
convention). A user should never have to already know a secret gesture to
find a feature that exists. This project's own home-list rename bug (added
inline-only, then had to be re-added with a real button) is the canonical
example — don't repeat it elsewhere (rubric edits, stage config, etc.).

## 3. Live/dynamic data must be dynamic everywhere it's shown, not just in one place

If a concept ("this migration is running, here's per-stage status") has a
live view built once, audit every OTHER place the same underlying entity
(the pipeline, the stage) is rendered and ask whether it should also reflect
live state. Reprompt's Canvas tab rendering a static DAG while the
Migrations tab's *embedded copy of the same component* showed live status
was exactly this gap — one canonical live-data source, wired into every
place that entity is displayed, not just the first place it was built.

## 4. Every user-facing config surface must expose what's actually happening internally

If the backend auto-selects something on the user's behalf (a model, a
default budget, a threshold), don't leave it invisible. A user who can't see
*what* was chosen and *why* has no way to trust it, no matter how correct
the backend logic is — invisible correctness reads as "nothing works." When
you build an auto-selection mechanism, budget UI time for a "here's what we
picked and why" surface in the same phase, not as a deferred follow-up.

## 5. Verify by driving the real app, not by reading the diff

A passing test suite proves the code does what the test asserts — it does
not prove a human looking at the rendered page sees something that looks
correct. `pipeline-workspace.test.tsx` passed unchanged both before and
after the flex-height DAG bug was fixed, because jsdom-based unit tests
don't lay out real CSS. Before calling a UI change "done," actually load the
page (Playwright if available, otherwise a careful curl + component-tree
trace) and look at what a user would see, not just what the code claims to
render.
