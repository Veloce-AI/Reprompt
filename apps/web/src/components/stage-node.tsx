import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ParityBeam } from "@/components/parity-beam";
import type { StageInfo } from "@/lib/api";

export type StageNodeData = { stage: StageInfo };
export type StageFlowNode = Node<StageNodeData, "stage">;

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
        <p className="font-mono text-12 tabular-nums text-ink-soft">
          {Math.round(stage.avg_tokens_in)}→{Math.round(stage.avg_tokens_out)} tok ·{" "}
          {Math.round(stage.avg_latency_ms)}ms
        </p>
        {/* No migration exists yet in M1 - ParityBeam's own no-score state
            is exactly right here, and becomes a real score once M4 lands. */}
        <ParityBeam />
      </CardContent>
      <Handle type="source" position={Position.Right} className="!bg-beam" />
    </Card>
  );
}
