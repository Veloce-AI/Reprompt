import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ParityBeam } from "@/components/parity-beam";
import { cn } from "@/lib/utils";
import type { StageInfo, StagePhase, StageRunState } from "@/lib/api";
import type { CanvasOrientation } from "@/lib/canvas-layout";

export type StageNodeData = {
  stage: StageInfo;
  runState?: StageRunState;
  substep?: StagePhase | null;
  /** Flow direction of the canvas layout — decides which sides the edge
   * handles sit on. Defaults to horizontal (the original behavior). */
  orientation?: CanvasOrientation;
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
  const { stage, runState, substep, orientation } = data;
  const vertical = orientation === "vertical";

  return (
    <Card
      className={cn(
        "w-56 border-2 transition-colors duration-base ease-out",
        runState ? STATE_BORDER[runState] : "border-line",
        // Soft --beam halo while an LLM call is happening in this stage -
        // the "light is here right now" signal (pulse disabled under
        // prefers-reduced-motion, see globals.css).
        runState === "running" && "stage-node-glow"
      )}
    >
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
