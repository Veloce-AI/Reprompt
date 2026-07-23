# ADR-001: Merge Canvas and Graph tabs into one mode-switched DAG view

## Status
Accepted — Phase 1 (mechanical merge) in implementation as of 2026-07-22.

## Context

**Problem**: Reprompt's pipeline workspace had two separate tabs both rendering
the same pipeline as a DAG, using the same data (`getPipelineDag`, identical
`["pipeline-dag", pipelineId]` cache key) and the same layout engine
(`computeCanvasLayout` in `apps/web/src/lib/canvas-layout.ts`):

- **Canvas** (`pipeline-canvas.tsx`) — live-run-status focused: per-stage
  running/done/failed coloring, sub-step labels, beam-pulse animation on the
  active stage, a minimap, Compact/Spacious spacing picker, orientation
  toggle, and a hard-won legible zoom floor (`CANVAS_MIN_ZOOM = 0.5`,
  arrived at after two earlier rounds of illegibility bugs this project
  actually shipped and had to fix).
- **Graph** (`pipeline-graph.tsx`) — added later via an external contribution
  (PR #8): a static analytics/drill-down view with a fixed-column "model"
  node per unique model (click-to-highlight which stages share it) and
  expandable per-stage call nodes showing individual inference records.

Because Graph was a separate component built independently, it never
received Canvas's legibility fixes. It shipped with `minZoom: 0.25` (looser
than Canvas's `0.5`) and its own header comment admitted its node-height
estimate (200px) didn't match the shared layout engine's estimate (150px),
"narrowing the gap... to ~46px at spacious spacing" — a self-documented
near-overlap. The product owner reported this concretely, with a real
screenshot showing Graph rendering a real ~30-stage pipeline as a tall,
illegible column with dense overlapping edges — the identical failure mode
Canvas had already been through and fixed.

**Constraints**: this project's own `system-design` skill already states the
underlying principle — "one canonical live-status source, not per-screen
duplicates" — for backend state; the same reasoning applies to frontend DAG
renderers of the same entity. Sunk cost in Canvas's React Flow (`@xyflow/react`)
integration (zoom-floor tuning, minimap, animation, layout picker) is
substantial and already proven correct; a rendering-library swap was
explicitly out of scope (decided earlier this session).

## Decision

Merge Graph's capabilities into Canvas as a `mode: "live" | "analytics"`
toggle within one tab. Retire the separate "Graph" tab and delete
`pipeline-graph.tsx` entirely, rather than bringing Graph up to Canvas's
quality bar as a second, independently-maintained component.

## Options considered

| Option | Pros | Cons | Complexity | When valid |
|---|---|---|---|---|
| A. Fix Graph in place to match Canvas's legibility bar | Smaller diff per-fix; keeps tab separation the PR author intended | Two DAG renderers of the same data will drift again the next time either gets a fix (exactly what already happened once) | Low now, recurring cost later | If the two views' capabilities were genuinely divergent enough to justify separate maintenance |
| B. Merge into one tab, mode-switched (chosen) | One renderer, one layout engine, one zoom floor, one toolbar, one place to fix a bug once | Larger one-time migration; requires folding two node-type sets into one ReactFlow instance | Medium, one-time | When both views render the same entity from the same data source, as confirmed here |
| C. Rewrite both using a different graph library (three.js/D3) | Could look more distinctive | Throws away proven, hard-won React Flow integration work; new failure surface; explicitly rejected earlier this session | High | Not applicable here — no capability gap React Flow can't serve |

## Rationale

1. Both tabs already query identical data through an identical cache key and
   lay it out with an identical engine — they were never two views of
   different data, Graph was a fork of Canvas's rendering approach that
   diverged the moment it was added as a separate component.
2. That divergence is the actual, demonstrated bug. Keeping them separate
   doesn't fix the root cause, it just re-fixes the symptom on whichever
   component happens to be reported broken this time — the next Canvas
   change would again leave Graph behind, or vice versa.
3. Product owner's own framing — "the graph and canvas are same... some
   modular approach" — independently arrived at the same conclusion this
   ADR reaches from the code.
4. A dedicated planning pass (evidence-based, five project skills applied:
   `frontend-design`, `saas-product-design`, `design-references`,
   `system-design`, `spec-driven-planning`) read both components in full,
   confirmed every distinct capability on each side, and recommended this
   merge with file:line evidence rather than preference.

## Trade-offs accepted

- A larger one-time migration diff than a narrow Graph-only fix would have
  been — accepted because it's the only option that removes the recurrence
  risk, not just the current instance of the bug.
- Model nodes carry no per-model color-coding (a real capability Graph could
  have grown into) — deliberately excluded: the `dataviz` skill's palette
  validator was run against this project's actual status colors and passed,
  but an unbounded, growing set of models is exactly the "9th series becomes
  a cycled hue" anti-pattern the same skill warns against. Text + click-to-
  highlight stays the mechanism instead.
- Mode choice is session-only (not persisted to localStorage, unlike the
  Spacing/Orientation pickers) — a deliberate asymmetry, not an oversight:
  a stale saved "Analytics" preference must never silently suppress the
  auto-switch-to-Live-during-a-running-migration behavior.

## Consequences

- **Positive**: one zoom floor, one toolbar, one localStorage key, one
  layout engine consumer to fix when a future layout bug appears — the
  specific failure class that caused this ADR becomes structurally
  impossible to reintroduce via "the other tab" drifting.
- **Negative**: the merge touches a wide surface (`pipeline-canvas.tsx`,
  `stage-node.tsx`, `pipeline-workspace.tsx`, deletes `pipeline-graph.tsx`)
  in one migration, larger than this project's own standing preference for
  small, single-concern agent tasks — mitigated by splitting the actual
  implementation into a phased build order (Phase 1: mechanical merge only,
  zero new capability; Phase 2: toggle UI polish + a real accessibility gap
  the same planning pass found — done/failed states are currently
  color+dot only, no persistent text label; Phase 3: a Contracts-tab status
  indicator on stage nodes, deferred since it needs a real backend field
  that doesn't exist yet).
- **Mitigation for the negative**: each phase ships and is verified
  (Playwright-driven, not just `tsc`/unit tests — this project has twice
  shipped DAG regressions invisible to jsdom) independently before the next
  starts.

## Revisit trigger

If Reprompt ever needs a fundamentally different visualization paradigm for
one of the two modes (e.g., Analytics mode growing into a genuinely
different layout shape than a DAG — a table, a timeline), split them back
into separate routes at that point rather than forcing a mismatched paradigm
into one ReactFlow instance. Not expected currently; noted so a future
session doesn't have to re-derive this reasoning from scratch.
