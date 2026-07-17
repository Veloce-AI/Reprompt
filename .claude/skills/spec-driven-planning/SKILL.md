---
name: spec-driven-planning
description: Evidence-based architecture/spec writing before a big feature — read the real code first, ban hypothetical components, map every claim to an actual file. Use before any planning pass (a Plan-agent dispatch, a DEV_TRACKER.md phase writeup, a new feature's design doc), not just when explicitly asked to "write a spec".
---

# Spec-driven planning (Reprompt-specific)

This project already does a version of this discipline — every planning
agent dispatched this session was told "read the actual code, don't
assume the earlier summary is still accurate," and `DEV_TRACKER.md`
repeatedly documents cases where a spec's assumption drifted from reality
(line numbers, `TargetModelConfig`'s shape, `CompositeScore`'s fields) and
had to be corrected against the real file. This skill names that
discipline explicitly so it stays deliberate, not accidental.

## 1. Evidence over hypothesis — every claim traces to a real file

A spec/plan must only describe what's demonstrably true right now: read
the actual source before writing a sentence about what it does. Never
write "X probably handles Y" or "there's likely a Z here" — grep for it,
open the file, confirm it, or say explicitly "not verified, flag as an
open question." This project's own planning agents were repeatedly
instructed to ground findings in file:line references rather than
summaries — that's this rule in practice, not a one-off preference.

## 2. Ban hypothetical/idealized components in architecture write-ups

Don't describe the system as it "should" be or "ideally would" be —
describe what it actually is, including its rough edges. A design doc
that quietly upgrades a hand-rolled workaround into a clean abstraction
that doesn't exist yet misleads whoever reads it next. If a phase is
genuinely half-built, say so plainly (see `DEV_TRACKER.md`'s own
"Current state" sections, which routinely say things like "Not started"
or "superseded same day" rather than smoothing over the mess).

## 3. Map every component to where it actually lives in the repo

When describing an architectural piece (an evaluator, a layer, a data
flow), name the real file and function, not just the concept. "The
optimizer scores candidates" is weaker than "`scoring.py`'s
`compute_composite_score()` combines deterministic (0.25) + judge (0.45)
+ embedding (0.30)." The second version is falsifiable — a reader can go
check it — the first is just prose.

## 4. Quality over quantity — a handful of real findings beats an exhaustive list

A plan with 3-8 concrete, evidence-backed points is more useful than one
with 30 speculative ones. This project's own planning passes (the
Fable-style dispatches throughout `DEV_TRACKER.md`) work best when they
name ONE key decision per phase with a clear recommendation, not a menu
of options with no call made — see this project's own `system-design`
skill for the same principle applied to architecture decisions
specifically.

## 5. Treat the current repo state as the source of truth, not the last plan

Before extending or trusting an existing spec/plan, re-verify it against
the actual current code — plans go stale the moment code moves past them.
If a plan's assumption no longer holds (a file moved, a shape changed, a
phase that was "not started" is now done), fix the plan, don't build on
top of the stale version. This is exactly why `DEV_TRACKER.md` requires
its "Current state" paragraph be rewritten to match reality, not the
original plan, every time.

## When to use this explicitly

Before dispatching a planning-only agent (no code, just design) for a new
feature area — brief it with this discipline directly: read the real
code, ground every claim, make one clear recommendation per open
question, and flag what's genuinely unverified rather than guessing.
