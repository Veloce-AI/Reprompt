import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ReactFlow, Background, Controls, type Edge } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { getPipelineDag, type StageRunState } from "@/lib/api";
import { StageNode, type StageFlowNode } from "@/components/stage-node";

const LAYER_X_GAP = 280;
const NODE_Y_GAP = 160;

const nodeTypes = { stage: StageNode };

export interface PipelineCanvasProps {
  pipelineId: number;
  /** Live per-stage run state (keyed by stage DB id as a string) — pass a
   * migration's `stage_states` while it's running/just finished to color
   * and pulse the matching nodes. Omit for the static, read-only canvas. */
  stageStates?: Record<string, StageRunState>;
  className?: string;
}

/**
 * Shared React Flow DAG canvas for a pipeline's Stage[]. Used both by the
 * standalone pipeline-detail screen (no `stageStates` — static view) and by
 * the migration run screen (with `stageStates`, polled live — see Phase 2 /
 * DEV_TRACKER.md "Live DAG/run status view").
 */
export function PipelineCanvas({ pipelineId, stageStates, className }: PipelineCanvasProps) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["pipeline-dag", pipelineId],
    queryFn: () => getPipelineDag(pipelineId),
  });

  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [] as StageFlowNode[], edges: [] as Edge[] };

    const nodes: StageFlowNode[] = data.layers.flatMap((layer, layerIndex) =>
      layer.stage_ids.map((stageId, rowIndex) => ({
        id: String(stageId),
        type: "stage",
        position: { x: layerIndex * LAYER_X_GAP, y: rowIndex * NODE_Y_GAP },
        data: {
          stage: data.stages[String(stageId)],
          runState: stageStates?.[String(stageId)],
        },
      }))
    );

    const edges: Edge[] = data.edges.map((edge) => ({
      id: `${edge.from_stage_id}-${edge.to_stage_id}`,
      source: String(edge.from_stage_id),
      target: String(edge.to_stage_id),
      style: { stroke: "var(--line)" },
    }));

    return { nodes, edges };
  }, [data, stageStates]);

  if (isLoading) {
    return (
      <p className="p-8 text-14 text-ink-soft" role="status">
        Loading pipeline…
      </p>
    );
  }

  if (isError) {
    return (
      <p className="p-8 text-14 text-parity-fail" role="alert">
        {error instanceof Error ? error.message : "Couldn't load pipeline"}
      </p>
    );
  }

  return (
    <div className={className ?? "h-full min-h-[480px] flex-1"}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}
