import { useMemo } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ReactFlow, Background, Controls, type Edge } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { getPipelineDag } from "@/lib/api";
import { AppShell } from "@/components/app-shell";
import { StageNode, type StageFlowNode } from "@/components/stage-node";
import { Button } from "@/components/ui/button";

const LAYER_X_GAP = 280;
const NODE_Y_GAP = 160;

const nodeTypes = { stage: StageNode };

export default function PipelineDetail() {
  const { pipelineId } = useParams({ from: "/pipelines/$pipelineId" });
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["pipeline-dag", pipelineId],
    queryFn: () => getPipelineDag(Number(pipelineId)),
  });

  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [] as StageFlowNode[], edges: [] as Edge[] };

    const nodes: StageFlowNode[] = data.layers.flatMap((layer, layerIndex) =>
      layer.stage_ids.map((stageId, rowIndex) => ({
        id: String(stageId),
        type: "stage",
        position: { x: layerIndex * LAYER_X_GAP, y: rowIndex * NODE_Y_GAP },
        data: { stage: data.stages[String(stageId)] },
      }))
    );

    const edges: Edge[] = data.edges.map((edge) => ({
      id: `${edge.from_stage_id}-${edge.to_stage_id}`,
      source: String(edge.from_stage_id),
      target: String(edge.to_stage_id),
      style: { stroke: "var(--line)" },
    }));

    return { nodes, edges };
  }, [data]);

  return (
    <AppShell>
    <div className="flex h-full min-h-[calc(100vh-1px)] flex-col">
      <div className="flex items-center justify-between border-b border-line px-8 py-4">
        <div>
          <Link
            to="/"
            className="text-13 text-ink-soft hover:text-ink"
          >
            ← Pipelines
          </Link>
          <h1 className="font-display text-28 font-semibold leading-display text-ink">
            Pipeline canvas
          </h1>
        </div>
        <div className="flex gap-3">
          <Link to="/pipelines/$pipelineId/rubrics" params={{ pipelineId }}>
            <Button variant="secondary">Review rubrics</Button>
          </Link>
          <Link to="/pipelines/$pipelineId/migrations/new" params={{ pipelineId }}>
            <Button variant="primary">New migration</Button>
          </Link>
        </div>
      </div>

      {isLoading && (
        <p className="p-8 text-14 text-ink-soft" role="status">
          Loading pipeline…
        </p>
      )}

      {isError && (
        <div className="p-8">
          <p className="mb-4 text-14 text-parity-fail" role="alert">
            {error instanceof Error ? error.message : "Couldn't load pipeline"}
          </p>
          <Link to="/">
            <Button variant="secondary">Back to pipelines</Button>
          </Link>
        </div>
      )}

      {data && (
        <div className="flex-1">
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
      )}
    </div>
    </AppShell>
  );
}
