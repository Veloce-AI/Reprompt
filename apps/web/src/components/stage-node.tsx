import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ParityBeam } from "@/components/parity-beam";
import { cn } from "@/lib/utils";
import type { StageInfo, StagePhase, StageRunState } from "@/lib/api";
import type { CanvasOrientation } from "@/lib/canvas-layout";

/** Live = the original Canvas tab (per-stage run status while a migration
 * executes). Analytics = the former Graph tab's model/call drill-down view,
 * folded into this same component — see DEV_TRACKER.md's Canvas/Graph merge
 * entry. Owned here (not pipeline-canvas.tsx) since StageNodeData is the
 * thing that actually branches on it. */
export type PipelineCanvasMode = "live" | "analytics";

export type StageNodeData = {
  stage: StageInfo;
  runState?: StageRunState;
  substep?: StagePhase | null;
  /** Flow direction of the canvas layout — decides which sides the edge
   * handles sit on. Defaults to horizontal (the original behavior). */
  orientation?: CanvasOrientation;
  /** Defaults to "live" when omitted so every pre-existing caller (and
   * stage-node.test.tsx, which never sets this) keeps rendering exactly as
   * before — analytics-only content below is opt-in, not a behavior change
   * for live mode. */
  mode?: PipelineCanvasMode;
  /** Analytics mode only: whether this stage's call-drilldown is currently
   * expanded (pins/unpins on click, driven by pipeline-canvas.tsx). */
  isExpanded?: boolean;
  /** Analytics mode only: whether this stage has any traces to expand
   * (stage.trace_count > 0) — ported from the former Graph tab's
   * StageGraphNode `canExpand` check. */
  canExpandCalls?: boolean;
  /** Analytics mode only: whether this stage's model is the currently
   * pinned/highlighted model node — same border/edge highlight treatment
   * the former Graph tab's ModelGraphNode click drove. */
  isModelHighlighted?: boolean;
};
export type StageFlowNode = Node<StageNodeData, "stage">;

// Human-readable labels for reprompt_core.optimizer.loop.StagePhase — never
// render the raw enum value in the UI. Exported for reuse by the activity
// log list (migration-success-screen.tsx) — same phase vocabulary, same
// "never show the raw enum" rule applies there too.
export const SUBSTEP_LABEL: Record<StagePhase, string> = {
  mutating: "Generating prompt variants",
  cheap_scoring: "Ranking candidates",
  critiquing: "Critiquing weakest candidates",
  refining: "Refining prompt",
  sweeping: "Running parameter sweep",
  scoring: "Scoring candidates",
};

// Same semantic colors ParityBeam/Badge already use for pass/near/fail, plus
// --beam (the "active/running" accent used elsewhere, e.g. the migration
// progress dot in new-migration.tsx) for "running" and a plain hairline
// border for "idle" (nothing has touched this stage yet). No new tokens
// introduced — this only recombines the existing vocabulary.
const STATE_BORDER: Record<StageRunState, string> = {
  idle: "border-line",
  running: "border-beam",
  done: "border-parity-pass",
  failed: "border-parity-fail",
};

const STATE_DOT: Record<StageRunState, string> = {
  idle: "bg-ink-soft/40",
  running: "bg-beam animate-pulse",
  done: "bg-parity-pass",
  failed: "bg-parity-fail",
};

const STATE_LABEL: Record<StageRunState, string> = {
  idle: "Not started",
  running: "Running",
  done: "Done",
  failed: "Failed",
};

// Trace format v1.1 makes StageRecord.tokens/latency_ms optional (a trace
// recorder may not capture them), so the DAG's per-stage averages can come
// back null instead of a fake 0.0 - see docs/trace-format.md. Render an
// honest "not tracked" label in that case rather than "0→0 tok", which
// would misread as the stage actually costing nothing.
function statsLabel(stage: StageInfo): string {
  const hasTokens = stage.avg_tokens_in != null && stage.avg_tokens_out != null;
  const hasLatency = stage.avg_latency_ms != null;

  const tokensPart = hasTokens
    ? `${Math.round(stage.avg_tokens_in!)}→${Math.round(stage.avg_tokens_out!)} tok`
    : "tokens not tracked";
  const latencyPart = hasLatency ? `${Math.round(stage.avg_latency_ms!)}ms` : "latency not tracked";

  return `${tokensPart} · ${latencyPart}`;
}

export function StageNode({ data }: NodeProps<StageFlowNode>) {
  const {
    stage,
    runState,
    substep,
    orientation,
    mode = "live",
    isExpanded,
    canExpandCalls,
    isModelHighlighted,
  } = data;
  const vertical = orientation === "vertical";
  const analytics = mode === "analytics";

  return (
    <Card
      className={cn(
        "w-56 border-2 transition-colors duration-base ease-out",
        // Model-highlight (analytics mode) takes visual priority over the
        // idle/done/failed border - a pinned model's stages should read as
        // "selected" the same way a running stage reads as "active".
        isModelHighlighted
          ? "border-beam shadow-[0_0_0_3px_var(--beam-soft)]"
          : runState
            ? STATE_BORDER[runState]
            : "border-line",
        // Soft --beam halo while an LLM call is happening in this stage -
        // the "light is here right now" signal (pulse disabled under
        // prefers-reduced-motion, see globals.css).
        runState === "running" && "stage-node-glow"
      )}
    >
      {/* Single target handle, shared by every kind of incoming edge in
          every mode (dependency edges in both Live and Analytics) -
          orientation-aware, unchanged from before this merge. Deliberately
          NOT split into several named handles per edge kind: this canvas is
          fully controlled (nodes/edges rebuilt from query data via useMemo,
          no onNodesChange wiring - see the `initialWidth`/`initialHeight`
          comment in pipeline-canvas.tsx for the same underlying fragility),
          and React Flow's handle-bounds lookup for a *named* handle
          requires that exact id to already be registered; with only ever
          one handle of each type here, React Flow always resolves it
          immediately regardless of timing (its own `bounds.length === 1`
          fast path) - confirmed the hard way: giving each edge kind its own
          named handle intermittently dropped edges on a larger (35-node)
          graph, a real regression caught by re-running the same e2e spec
          repeatedly, not by a single green run. Model and call edges (see
          pipeline-canvas.tsx) reuse this same source handle rather than a
          dedicated one. */}
      <Handle
        type="target"
        position={vertical ? Position.Top : Position.Left}
        className="!bg-beam"
      />
      <CardContent className="space-y-2 p-4">
        <div className="flex items-center justify-between gap-2">
          <p className="min-w-0 truncate text-14 font-medium text-ink" title={stage.name}>
            {stage.name}
          </p>
          {runState && (
            <span
              role="img"
              aria-label={`Stage ${STATE_LABEL[runState].toLowerCase()}`}
              title={STATE_LABEL[runState]}
              className={cn("h-2 w-2 shrink-0 rounded-full", STATE_DOT[runState])}
            />
          )}
        </div>
        {runState === "running" && substep && (
          <p className="truncate text-12 text-beam" title={SUBSTEP_LABEL[substep]}>
            Running — {SUBSTEP_LABEL[substep].toLowerCase()}
          </p>
        )}
        <Badge variant="neutral" className="max-w-full truncate">
          {stage.model}
        </Badge>
        {/* Same slot regardless of whether stats are present, so node
            sizing doesn't jump around across stages within a DAG. */}
        <p className="font-mono text-12 tabular-nums text-ink-soft">{statsLabel(stage)}</p>
        {/* Analytics-mode-only richer stats - ported from the former Graph
            tab's StageGraphNode, gated to this mode per the merge plan
            (never shown in live mode, which already has its own compact
            stats line above). */}
        {analytics && (
          <div className="space-y-1 font-mono text-12 tabular-nums text-ink-soft">
            <p>
              {canExpandCalls
                ? `${stage.trace_count} trace${stage.trace_count === 1 ? "" : "s"}`
                : "No traces yet"}
            </p>
            {stage.total_cost_usd != null && <p>${stage.total_cost_usd.toFixed(4)} total</p>}
          </div>
        )}
        {analytics && canExpandCalls && (
          <p className={cn("text-12", isExpanded ? "text-beam" : "text-ink-soft")}>
            {isExpanded ? "▼ Hide inference calls" : "▶ View inference calls"}
          </p>
        )}
        {/* No migration exists yet in M1 - ParityBeam's own no-score state
            is exactly right here, and becomes a real score once M4 lands. */}
        <ParityBeam />
      </CardContent>
      <Handle
        type="source"
        position={vertical ? Position.Bottom : Position.Right}
        className="!bg-beam"
      />
    </Card>
  );
}
