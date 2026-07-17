---
name: design-references
description: Real SaaS product DESIGN.md specs (Linear, Stripe, PostHog) for comparison when making visual/UX decisions on Reprompt's own screens. Use when unsure how a data-dense, serious-tool SaaS product should look/feel — read these as reference points, not templates to copy.
license: MIT (see LICENSE)
---

# Design references — comparable SaaS products

Three real, extracted design specs from products in the same rough
category as Reprompt (data-dense developer/analytics tools, not consumer
apps): `linear/DESIGN.md`, `stripe/DESIGN.md`, `posthog/DESIGN.md`.

## How to use these

Read the relevant one when facing a concrete design decision — not as
inspiration to browse idly, and never to copy verbatim. Reprompt already
has its own identity (see the `frontend-design` skill: serif display
headings, `--beam` accent, restrained neutral palette, data density over
whitespace) — these references are for *checking your instinct* against a
real, shipped product that solved a similar problem, not for replacing
that identity.

- **Linear** — closest analog for information density + a single accent
  color used sparingly + a "serious tool" typographic feel. Check this one
  first for: dashboard layouts, status/badge conventions, how much
  whitespace a data-dense screen can actually afford before it reads as
  sparse rather than clean.
- **Stripe** — check for: how a company that lives-and-dies on user trust
  in numbers/data presents tables, diffs, and financial-adjacent figures
  (Reprompt's cost/latency/score reporting is the same category of
  "numbers the user needs to trust at a glance").
- **PostHog** — check for: analytics-product conventions specifically
  (charts, comparison views, filter toolbars) — the closest direct analog
  to Reprompt's Data tab and the planned scorecard/comparison work.

## What NOT to do with these

Don't lift a specific component's exact visual treatment (a specific
gradient, a specific icon set, a specific font pairing) — that's
imitation, not reference, and works against Reprompt's own stated
"avoid generic AI-app defaults" discipline (see `frontend-design`). The
right use is: "how did a comparable serious product solve this class of
problem," then solve it Reprompt's own way with Reprompt's own tokens.
