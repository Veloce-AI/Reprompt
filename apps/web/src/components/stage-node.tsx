import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ParityBeam } from "@/components/parity-beam";
import type { StageInfo } from "@/lib/api";

export type StageNodeData = { stage: StageInfo };
export type StageFlowNode = Node<StageNodeData, "stage">;

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
  const { stage } = data;

  return (
    <Card className="w-56">
      <Handle type="target" position={Position.Left} className="!bg-beam" />
      <CardContent className="space-y-2 p-4">
        <p className="text-14 font-medium text-ink" title={stage.name}>
          {stage.name}
        </p>
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
      <Handle type="source" position={Position.Right} className="!bg-beam" />
    </Card>
  );
}
