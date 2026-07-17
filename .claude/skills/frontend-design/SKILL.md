---
name: frontend-design
description: Bold, distinctive frontend design that avoids generic AI-generated aesthetics — use whenever writing or reviewing apps/web UI, not just when a screen is explicitly a "design task".
---

# Frontend design discipline (Reprompt-specific)

Reprompt already has a real design identity: a serif display face for
headings ("Pipelines", pipeline names) against a clean sans-serif UI
typeface, a beam/prism visual metaphor (the logo, `ParityBeam`, the
`--beam` accent token used for "running" states), and a restrained neutral
palette with semantic `--parity-pass`/`--parity-fail` colors reserved
specifically for match/mismatch signal. Every new screen or component must
extend this identity, not invent a parallel one.

## 1. Reuse the existing token vocabulary before adding anything new

Check `apps/web/src/index.css` (or wherever `tokens.css` lives) and the
`Badge`/`Card`/`Drawer` primitives in `apps/web/src/components/ui/` before
reaching for a raw Tailwind color or a new component. This project has
already made real, deliberate choices — pulsing `--beam` for "in progress",
`--parity-pass`/`--parity-fail` for outcome, a specific serif for headings —
and every phase built so far has reused them rather than inventing
per-feature colors. A new "Recommended" badge on a scorecard, a new drawer
for reasoning text, a new activity-log entry: all of these should look like
they were designed in the same sitting as the original canvas, not bolted
on later.

## 2. Avoid generic "AI app" defaults

Default component-library looks — a plain white card grid with drop
shadows, default system-font body text with no hierarchy, purple-to-blue
gradients, centered hero sections with a stock icon — read as low-effort and
undermine trust in a product whose entire pitch is rigor (proving prompt
parity, not hand-waving it). Concretely: don't add a new gradient, don't add
a new "AI sparkle" icon, don't default to `rounded-2xl` everywhere just
because it's a common preset — match what's already here.

## 3. Motion and state should communicate meaning, not decorate

Every animation in this codebase currently means something specific: the
pulsing dot/border on a running stage node means "an LLM call is happening
right now," the word-diff's strikethrough/highlight means "removed/added,"
the activity log's auto-scroll means "this is live, not historical." Don't
add motion that doesn't map to a real state change — a spinner on a static
page, a hover-lift on a card that isn't clickable, a transition with no
underlying data change. If you can't say what state the animation
represents, it shouldn't exist.

## 4. Typography hierarchy carries the "serious tool" feel

The serif display face on page titles (`Pipelines`, a pipeline's name) next
to the clean sans body text is doing real work — it's what makes this read
as a rigorous engineering tool rather than a consumer app. Any new
top-level screen or drawer title should follow the same pattern (serif
title, sans body/labels/data), not default to a single uniform typeface.

## 5. Density over whitespace-for-its-own-sake

This is a data-dense product (stage graphs, cost/latency numbers, prompt
diffs, activity logs) — the Data tab's virtualized table and the DAG
canvas's compact node cards are the right model: real information visible
at a glance, not padded out with excess whitespace to look "clean." When
adding a new report/report-like surface (e.g. the scorecard), match that
density, don't default to one-fact-per-card sprawling layouts.
