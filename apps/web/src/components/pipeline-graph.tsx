import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ReactFlow,
  Background,
  Controls,
  Panel,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  getPipelineDag,
  listStageRecords,
  type StageInfo,
  type StageRecordOut,
} from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  computeCanvasLayout,
  type CanvasOrientation,
} from "@/lib/canvas-layout";
import { cn } from "@/lib/utils";

// ---- Dimensions ----
// Approximate rendered sizes. Dagre uses STAGE_NODE_H for stage-to-stage
// vertical spacing (via canvas-layout.ts's hardcoded NODE_HEIGHT=150, which
// underestimates our richer node — the 50px difference narrows the gap from
// 96px to ~46px at spacious spacing, still non-overlapping).
// Model and call nodes are positioned manually so their sizes only affect
// visual overlap, not the dagre layout.
const STAGE_NODE_W = 256;
const STAGE_NODE_H = 200;
const MODEL_NODE_H = 72;
const MODEL_V_GAP = 20;
const MODEL_COL_GAP = 100; // horizontal gap: rightmost stage right edge → model column left edge
const CALL_NODE_W = 240;
const CALL_NODE_H = 82;
const CALL_V_GAP = 10;
const CALL_FROM_STAGE = 28; // gap from stage bottom to first call node top

// ---- Node data types ----

type StageGraphNodeData = {
  stage: StageInfo;
  isExpanded: boolean;
  isHighlighted: boolean;
};
type StageGraphFlowNode = Node<StageGraphNodeData, "stageGraph">;

type ModelGraphNodeData = {
  model: string;
  stageCount: number;
  isHighlighted: boolean;
};
type ModelGraphFlowNode = Node<ModelGraphNodeData, "modelGraph">;

type CallGraphNodeData = {
  record: StageRecordOut;
  index: number;
};
type CallGraphFlowNode = Node<CallGraphNodeData, "callGraph">;

function modelNodeId(model: string) {
  // Replace non-word chars so the id is safe as a CSS selector / React key
  return `model-${model.replace(/\W/g, "_")}`;
}

// ---- StageGraphNode ----
// Richer than the canvas StageNode: trace_count, total_cost_usd, and an
// expand-calls toggle. Clicking the node is handled by ReactFlow's
// onNodeClick in the parent — the node itself is fully passive.

function StageGraphNode({ data }: NodeProps<StageGraphFlowNode>) {
  const { stage, isExpanded, isHighlighted } = data;
  const canExpand = (stage.trace_count ?? 0) > 0;

  return (
    <Card
      className={cn(
        "w-64 cursor-pointer border-2 select-none transition-colors duration-base ease-out",
        isHighlighted
          ? "border-beam shadow-[0_0_0_3px_var(--beam-soft)]"
          : isExpanded
            ? "border-beam/60"
            : "border-line hover:border-beam/40",
      )}
    >
      {/* target: left — incoming dep edges */}
      <Handle type="target" position={Position.Left} id="left" className="!bg-beam" />
      <CardContent className="space-y-2 p-4">
        <p className="truncate text-14 font-medium text-ink" title={stage.name}>
          {stage.name}
        </p>
        <Badge variant="neutral" className="max-w-full truncate">
          {stage.model}
        </Badge>
        <div className="space-y-1 font-mono text-12 tabular-nums text-ink-soft">
          <p>
            {canExpand
              ? `${stage.trace_count} trace${stage.trace_count === 1 ? "" : "s"}`
              : "No traces yet"}
          </p>
          {stage.avg_tokens_in != null && stage.avg_tokens_in > 0 && (
            <p>
              {Math.round(stage.avg_tokens_in)}→{Math.round(stage.avg_tokens_out ?? 0)}{" "}
              tok · {Math.round(stage.avg_latency_ms ?? 0)}ms avg
            </p>
          )}
          {stage.total_cost_usd != null && (
            <p>${stage.total_cost_usd.toFixed(4)} total</p>
          )}
        </div>
        {canExpand && (
          <p className={cn("text-12", isExpanded ? "text-beam" : "text-ink-soft")}>
            {isExpanded ? "▼ collapse calls" : "▶ expand calls"}
          </p>
        )}
      </CardContent>
      {/* source right — outgoing dep edges + model edges */}
      <Handle type="source" position={Position.Right} id="right" className="!bg-beam" />
      {/* source bottom — call edges (always rendered, hidden when no calls) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="bottom"
        className="!h-2 !w-2 !bg-ink-soft"
        style={{ opacity: canExpand && isExpanded ? 0.4 : 0 }}
      />
    </Card>
  );
}

// ---- ModelGraphNode ----
// Fixed-column node to the right of all stages. Clicking highlights the
// stages that use this model (sets highlightedModel via onNodeClick in
// PipelineGraph, not an internal handler). No source handles — only
// incoming edges from stages.

function ModelGraphNode({ data }: NodeProps<ModelGraphFlowNode>) {
  const { model, stageCount, isHighlighted } = data;
  return (
    <div
      className={cn(
        "w-48 cursor-pointer select-none rounded-card border-2 px-3 py-2.5 shadow-sm transition-colors duration-base ease-out",
        isHighlighted
          ? "border-beam bg-beam-soft shadow-[0_0_0_3px_var(--beam-soft)]"
          : "border-line bg-paper hover:border-beam/50",
      )}
    >
      <Handle type="target" position={Position.Left} id="left" className="!bg-beam/60" />
      <p
        className={cn(
          "truncate text-12 font-medium",
          isHighlighted ? "text-beam" : "text-ink",
        )}
        title={model}
      >
        {model}
      </p>
      <p className="text-11 text-ink-soft">
        {stageCount} stage{stageCount !== 1 ? "s" : ""}
      </p>
    </div>
  );
}

// ---- CallGraphNode ----
// Appears below its parent stage when expanded. Compact — just the key
// stats. Full input/output is in the Data tab's record browser.

function CallGraphNode({ data }: NodeProps<CallGraphFlowNode>) {
  const { record, index } = data;
  return (
    <div className="w-56 select-none rounded-control border border-line bg-paper px-3 py-2 shadow-sm">
      <Handle
        type="target"
        position={Position.Top}
        id="top"
        className="!h-1.5 !w-1.5 !bg-ink-soft"
        style={{ opacity: 0.4 }}
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-12 font-medium text-ink">Call #{index}</span>
        <div className="flex items-center gap-2 font-mono text-11 tabular-nums text-ink-soft">
          {record.tokens_in != null && (
            <span>
              {record.tokens_in}→{record.tokens_out ?? "?"} tok
            </span>
          )}
          {record.latency_ms != null && (
            <span>{Math.round(record.latency_ms)}ms</span>
          )}
        </div>
      </div>
      {record.cost != null && (
        <p className="mt-0.5 font-mono text-11 tabular-nums text-ink-soft">
          ${record.cost.toFixed(4)}
        </p>
      )}
    </div>
  );
}

const nodeTypes = {
  stageGraph: StageGraphNode,
  modelGraph: ModelGraphNode,
  callGraph: CallGraphNode,
};

// ---- RefitOnChange ----
// Same double-rAF pattern as pipeline-canvas.tsx: one rAF fires before the
// browser's layout pass, a second one fires after it, so fitView sees the
// real rendered positions of any newly-added call nodes.

function RefitOnChange({
  nodeCount,
  orientation,
}: {
  nodeCount: number;
  orientation: CanvasOrientation;
}) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    if (nodeCount === 0) return;
    let inner = () => {};
    const frame = requestAnimationFrame(() => {
      const frame2 = requestAnimationFrame(() =>
        fitView({ padding: 0.1, minZoom: 0.25 }),
      );
      inner = () => cancelAnimationFrame(frame2);
    });
    return () => {
      cancelAnimationFrame(frame);
      inner();
    };
  }, [nodeCount, orientation, fitView]);
  return null;
}

// ---- Orientation persistence (separate key from Canvas tab) ----

function loadGraphOrientation(pipelineId: number): CanvasOrientation {
  try {
    const raw = localStorage.getItem(`reprompt.graph-orient.${pipelineId}`);
    return raw === "vertical" ? "vertical" : "horizontal";
  } catch {
    return "horizontal";
  }
}

function saveGraphOrientation(pipelineId: number, o: CanvasOrientation): void {
  try {
    localStorage.setItem(`reprompt.graph-orient.${pipelineId}`, o);
  } catch {}
}

// ---- PipelineGraph ----

export function PipelineGraph({ pipelineId }: { pipelineId: number }) {
  const dagQuery = useQuery({
    queryKey: ["pipeline-dag", pipelineId],
    queryFn: () => getPipelineDag(pipelineId),
  });

  const [expandedStageIds, setExpandedStageIds] = useState(new Set<number>());
  // Map<stageId, records[]> — populated lazily on first expand, never evicted
  // (re-expanding uses the cached records without a second network request).
  const [stageRecordsMap, setStageRecordsMap] = useState(
    new Map<number, StageRecordOut[]>(),
  );
  const [highlightedModel, setHighlightedModel] = useState<string | null>(null);
  const [orientation, setOrientation] = useState<CanvasOrientation>(() =>
    loadGraphOrientation(pipelineId),
  );

  useEffect(() => {
    saveGraphOrientation(pipelineId, orientation);
  }, [pipelineId, orientation]);

  // Fetch records for any stage that's been expanded but not yet loaded.
  // Using an effect (not a query per stage) because we can't call hooks
  // conditionally — we don't know stage IDs until the dag loads.
  useEffect(() => {
    for (const stageId of expandedStageIds) {
      if (!stageRecordsMap.has(stageId)) {
        listStageRecords(pipelineId, { stageId, limit: 8 }).then((page) => {
          setStageRecordsMap((prev) => new Map(prev).set(stageId, page.records));
        });
      }
    }
  }, [expandedStageIds, stageRecordsMap, pipelineId]);

  const layout = useMemo(
    () => ({ orientation, spacing: "spacious" as const }),
    [orientation],
  );

  const { nodes, edges } = useMemo(() => {
    const dag = dagQuery.data;
    if (!dag)
      return {
        nodes: [] as (StageGraphFlowNode | ModelGraphFlowNode | CallGraphFlowNode)[],
        edges: [] as Edge[],
      };

    const stagePositions = computeCanvasLayout(dag.layers, dag.edges, layout);
    const stageList = Object.values(dag.stages);

    // ---- Stage nodes ----
    const stageNodes: StageGraphFlowNode[] = stageList.map((stage) => ({
      id: `stage-${stage.id}`,
      type: "stageGraph" as const,
      position: stagePositions[String(stage.id)] ?? { x: 0, y: 0 },
      data: {
        stage,
        isExpanded: expandedStageIds.has(stage.id),
        isHighlighted: highlightedModel === stage.model,
      },
    }));

    // ---- Model nodes (fixed column right of all stages) ----
    const stageRightEdges = stageList.map(
      (s) => (stagePositions[String(s.id)]?.x ?? 0) + STAGE_NODE_W,
    );
    const maxStageRight = stageRightEdges.length ? Math.max(...stageRightEdges) : 0;
    const modelColX = maxStageRight + MODEL_COL_GAP;

    const uniqueModels = [...new Set(stageList.map((s) => s.model))];
    const stageYValues = stageList.map((s) => stagePositions[String(s.id)]?.y ?? 0);
    const minStageY = stageYValues.length ? Math.min(...stageYValues) : 0;
    const maxStageY = stageYValues.length ? Math.max(...stageYValues) : 0;
    const totalModelH =
      uniqueModels.length * MODEL_NODE_H + (uniqueModels.length - 1) * MODEL_V_GAP;
    const modelStartY = (minStageY + maxStageY) / 2 - totalModelH / 2;

    const modelNodes: ModelGraphFlowNode[] = uniqueModels.map((model, i) => ({
      id: modelNodeId(model),
      type: "modelGraph" as const,
      position: {
        x: modelColX,
        y: modelStartY + i * (MODEL_NODE_H + MODEL_V_GAP),
      },
      data: {
        model,
        stageCount: stageList.filter((s) => s.model === model).length,
        isHighlighted: highlightedModel === model,
      },
    }));

    // ---- Call nodes (fan below their parent stage when expanded) ----
    const callNodes: CallGraphFlowNode[] = [];
    for (const stageId of expandedStageIds) {
      const records = stageRecordsMap.get(stageId) ?? [];
      const pos = stagePositions[String(stageId)];
      if (!pos) continue;
      records.forEach((record, i) => {
        callNodes.push({
          id: `call-${record.id}`,
          type: "callGraph" as const,
          position: {
            x: pos.x + (STAGE_NODE_W - CALL_NODE_W) / 2,
            y: pos.y + STAGE_NODE_H + CALL_FROM_STAGE + i * (CALL_NODE_H + CALL_V_GAP),
          },
          data: { record, index: i + 1 },
        });
      });
    }

    // ---- Dependency edges (solid) ----
    const depEdges: Edge[] = dag.edges.map((e) => ({
      id: `dep-${e.from_stage_id}-${e.to_stage_id}`,
      source: `stage-${e.from_stage_id}`,
      sourceHandle: "right",
      target: `stage-${e.to_stage_id}`,
      targetHandle: "left",
      style: { stroke: "var(--line)", strokeWidth: 2 },
    }));

    // ---- Model edges (dashed, stage → model node) ----
    const modelEdges: Edge[] = stageList.map((stage) => ({
      id: `model-edge-${stage.id}`,
      source: `stage-${stage.id}`,
      sourceHandle: "right",
      target: modelNodeId(stage.model),
      targetHandle: "left",
      style: {
        stroke: "var(--beam)",
        strokeWidth: 1.5,
        strokeDasharray: "5 3",
        opacity: highlightedModel === stage.model ? 0.9 : 0.3,
      },
    }));

    // ---- Call edges (straight, stage bottom → call top) ----
    const callEdges: Edge[] = [];
    for (const stageId of expandedStageIds) {
      const records = stageRecordsMap.get(stageId) ?? [];
      records.forEach((record) => {
        callEdges.push({
          id: `call-edge-${record.id}`,
          source: `stage-${stageId}`,
          sourceHandle: "bottom",
          target: `call-${record.id}`,
          targetHandle: "top",
          type: "straight",
          style: {
            stroke: "var(--ink-soft)",
            strokeWidth: 1,
            opacity: 0.4,
          },
        });
      });
    }

    return {
      nodes: [...stageNodes, ...modelNodes, ...callNodes],
      edges: [...depEdges, ...modelEdges, ...callEdges],
    };
  }, [dagQuery.data, layout, expandedStageIds, stageRecordsMap, highlightedModel]);

  if (dagQuery.isLoading) {
    return (
      <p className="p-8 text-14 text-ink-soft" role="status">
        Loading graph…
      </p>
    );
  }
  if (dagQuery.isError) {
    return (
      <p className="p-8 text-14 text-parity-fail" role="alert">
        {dagQuery.error instanceof Error
          ? dagQuery.error.message
          : "Couldn't load pipeline graph"}
      </p>
    );
  }

  return (
    <div className="h-full min-h-[480px] flex-1">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.1, minZoom: 0.25 }}
        minZoom={0.25}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_event, node) => {
          if (node.id.startsWith("stage-")) {
            const stageId = Number(node.id.slice(6));
            const stage = dagQuery.data?.stages[String(stageId)];
            if (!stage || (stage.trace_count ?? 0) === 0) return;
            setExpandedStageIds((prev) => {
              const next = new Set(prev);
              next.has(stageId) ? next.delete(stageId) : next.add(stageId);
              return next;
            });
          } else if (node.id.startsWith("model-")) {
            const model = (node.data as ModelGraphNodeData).model;
            setHighlightedModel((prev) => (prev === model ? null : model));
          }
        }}
      >
        <Background />
        <Controls />
        <Panel position="top-left">
          <div
            className="flex overflow-hidden rounded-control border border-line bg-paper"
            role="group"
            aria-label="Graph orientation"
          >
            {(["horizontal", "vertical"] as CanvasOrientation[]).map((o) => (
              <button
                key={o}
                type="button"
                title={
                  o === "horizontal"
                    ? "Horizontal (left to right)"
                    : "Vertical (top to bottom)"
                }
                aria-pressed={orientation === o}
                onClick={() => setOrientation(o)}
                className={cn(
                  "px-2.5 py-1 text-12 font-medium transition-colors duration-fast ease-out",
                  orientation === o
                    ? "bg-beam-soft text-beam"
                    : "text-ink-soft hover:bg-beam-soft/40 hover:text-ink",
                )}
              >
                {o === "horizontal" ? "→" : "↓"}
              </button>
            ))}
          </div>
        </Panel>
        <RefitOnChange nodeCount={nodes.length} orientation={orientation} />
      </ReactFlow>
    </div>
  );
}
