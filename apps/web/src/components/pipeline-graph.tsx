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
  DrawerRoot,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
  DrawerBody,
} from "@/components/ui/drawer";
import {
  computeCanvasLayout,
  type CanvasOrientation,
} from "@/lib/canvas-layout";
import { cn } from "@/lib/utils";

// ---- Node data / types ----

type StageGraphNodeData = {
  stage: StageInfo;
  isHighlighted: boolean;
  orientation: CanvasOrientation;
};

type StageGraphFlowNode = Node<StageGraphNodeData, "stageGraph">;

// ---- StageGraphNode ----
// Richer than the Canvas tab's StageNode: shows trace_count + total_cost_usd
// from the extended /dag response, and a "View inference calls →" affordance
// that triggers the calls drawer via the ReactFlow onNodeClick handler.

function StageGraphNode({ data }: NodeProps<StageGraphFlowNode>) {
  const { stage, isHighlighted, orientation } = data;
  const vertical = orientation === "vertical";
  return (
    <Card
      className={cn(
        "w-64 cursor-pointer border-2 select-none transition-colors duration-base ease-out",
        isHighlighted
          ? "border-beam shadow-[0_0_0_3px_var(--beam-soft)]"
          : "border-line hover:border-beam/50",
      )}
    >
      <Handle
        type="target"
        position={vertical ? Position.Top : Position.Left}
        className="!bg-beam"
      />
      <CardContent className="space-y-2 p-4">
        <p className="truncate text-14 font-medium text-ink" title={stage.name}>
          {stage.name}
        </p>
        <Badge variant="neutral" className="max-w-full truncate">
          {stage.model}
        </Badge>
        <div className="space-y-1 font-mono text-12 tabular-nums text-ink-soft">
          <p>
            {(stage.trace_count ?? 0) > 0
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
        <p className="text-12 text-beam">View inference calls →</p>
      </CardContent>
      <Handle
        type="source"
        position={vertical ? Position.Bottom : Position.Right}
        className="!bg-beam"
      />
    </Card>
  );
}

const nodeTypes = { stageGraph: StageGraphNode };

// ---- ModelPanel ----
// Floating panel (React Flow <Panel>) that lists each unique model used in
// the pipeline. Clicking a model highlights the stage nodes that use it,
// giving the Obsidian-style "see which nodes share a resource" insight
// without requiring model nodes in the React Flow graph itself (which would
// complicate the dagre layout when stages are expanded).

function ModelPanel({
  stages,
  highlightedModel,
  onHighlight,
}: {
  stages: StageInfo[];
  highlightedModel: string | null;
  onHighlight: (model: string | null) => void;
}) {
  const byModel = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const s of stages) {
      const names = map.get(s.model) ?? [];
      names.push(s.name);
      map.set(s.model, names);
    }
    return [...map.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [stages]);

  return (
    <div className="w-56 rounded-card border border-line bg-paper p-3 shadow-sm">
      <p className="mb-2 text-12 font-medium text-ink">Models in pipeline</p>
      <div className="space-y-1">
        {byModel.map(([model, stageNames]) => {
          const active = highlightedModel === model;
          return (
            <button
              key={model}
              type="button"
              onClick={() => onHighlight(active ? null : model)}
              className={cn(
                "w-full rounded-control px-2 py-1.5 text-left transition-colors duration-fast ease-out",
                active ? "bg-beam-soft" : "hover:bg-beam-soft/50",
              )}
            >
              <p
                className={cn(
                  "truncate text-12 font-medium",
                  active ? "text-beam" : "text-ink",
                )}
              >
                {model}
              </p>
              <p className="truncate text-11 text-ink-soft">
                {stageNames.length} stage{stageNames.length !== 1 ? "s" : ""} —{" "}
                {stageNames.join(", ")}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ---- CallsDrawer ----
// Slides in when a stage node is clicked — shows that stage's individual
// StageRecord rows (one per benchmark trace) as expandable call cards.

function CallsDrawer({
  pipelineId,
  stageId,
  stageName,
  model,
  onClose,
}: {
  pipelineId: number;
  stageId: number | null;
  stageName: string;
  model: string;
  onClose: () => void;
}) {
  const recordsQuery = useQuery({
    queryKey: ["stage-graph-calls", pipelineId, stageId],
    queryFn: () => listStageRecords(pipelineId, { stageId: stageId!, limit: 20 }),
    enabled: stageId !== null,
  });

  return (
    <DrawerRoot open={stageId !== null} onOpenChange={(open) => !open && onClose()}>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle>{stageName || "Inference calls"}</DrawerTitle>
          <DrawerDescription>
            {model} · individual benchmark calls for this stage
          </DrawerDescription>
        </DrawerHeader>
        <DrawerBody>
          {recordsQuery.isLoading && (
            <p className="text-13 text-ink-soft" role="status">
              Loading calls…
            </p>
          )}
          {recordsQuery.isError && (
            <p className="text-13 text-parity-fail" role="alert">
              Couldn't load calls.
            </p>
          )}
          {recordsQuery.data?.records.length === 0 && (
            <p className="text-13 text-ink-soft">
              No inference records for this stage yet.
            </p>
          )}
          {recordsQuery.data && recordsQuery.data.records.length > 0 && (
            <div className="space-y-3">
              {recordsQuery.data.records.map((record, i) => (
                <CallCard key={record.id} record={record} index={i + 1} />
              ))}
            </div>
          )}
        </DrawerBody>
      </DrawerContent>
    </DrawerRoot>
  );
}

function CallCard({ record, index }: { record: StageRecordOut; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const inputStr = (() => {
    try {
      return JSON.stringify(record.input, null, 2);
    } catch {
      return String(record.input);
    }
  })();
  const isLong = inputStr.length > 160 || record.output.length > 160;

  return (
    <div className="rounded-control border border-line p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-13 font-medium text-ink">Call #{index}</span>
        <div className="flex items-center gap-3 font-mono text-12 tabular-nums text-ink-soft">
          {record.tokens_in != null && (
            <span>
              {record.tokens_in}→{record.tokens_out ?? "?"} tok
            </span>
          )}
          {record.latency_ms != null && (
            <span>{Math.round(record.latency_ms)}ms</span>
          )}
          {record.cost != null && <span>${record.cost.toFixed(4)}</span>}
        </div>
      </div>
      <div className="space-y-2">
        <div>
          <p className="mb-1 text-12 font-medium text-ink-soft">Input</p>
          <pre className="whitespace-pre-wrap rounded-control bg-beam-soft/30 p-2 font-mono text-11 leading-normal text-ink">
            {expanded ? inputStr : truncateStr(inputStr, 160)}
          </pre>
        </div>
        <div>
          <p className="mb-1 text-12 font-medium text-ink-soft">Output</p>
          <pre className="whitespace-pre-wrap rounded-control bg-beam-soft/30 p-2 font-mono text-11 leading-normal text-ink">
            {expanded ? record.output : truncateStr(record.output, 160)}
          </pre>
        </div>
      </div>
      {isLong && (
        <button
          type="button"
          className="mt-2 text-12 text-beam hover:underline"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Show less" : "Show full text"}
        </button>
      )}
    </div>
  );
}

function truncateStr(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

// ---- RefitOnChange ----
// Same double-requestAnimationFrame pattern as pipeline-canvas.tsx: we need
// React Flow to measure the new node positions before calling fitView, and a
// single rAF fires before layout/paint; two rAFs guarantee one layout pass
// has already completed.

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
        fitView({ padding: 0.12, minZoom: 0.3 }),
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

// ---- Orientation persistence (separate key from canvas) ----

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

  const [highlightedModel, setHighlightedModel] = useState<string | null>(null);
  const [openStageId, setOpenStageId] = useState<number | null>(null);
  const [orientation, setOrientation] = useState<CanvasOrientation>(() =>
    loadGraphOrientation(pipelineId),
  );

  useEffect(() => {
    saveGraphOrientation(pipelineId, orientation);
  }, [pipelineId, orientation]);

  const layout = useMemo(
    () => ({ orientation, spacing: "spacious" as const }),
    [orientation],
  );

  const { nodes, edges } = useMemo(() => {
    const dag = dagQuery.data;
    if (!dag) return { nodes: [] as StageGraphFlowNode[], edges: [] as Edge[] };

    const positions = computeCanvasLayout(dag.layers, dag.edges, layout);
    const stageList = Object.values(dag.stages);

    const nodes: StageGraphFlowNode[] = stageList.map((stage) => ({
      id: String(stage.id),
      type: "stageGraph" as const,
      position: positions[String(stage.id)] ?? { x: 0, y: 0 },
      data: {
        stage,
        isHighlighted: highlightedModel === stage.model,
        orientation,
      },
    }));

    const edges: Edge[] = dag.edges.map((e) => ({
      id: `${e.from_stage_id}-${e.to_stage_id}`,
      source: String(e.from_stage_id),
      target: String(e.to_stage_id),
      style: { stroke: "var(--line)", strokeWidth: 2 },
    }));

    return { nodes, edges };
  }, [dagQuery.data, layout, highlightedModel, orientation]);

  const openStage = dagQuery.data?.stages[String(openStageId)] ?? null;
  const stages = Object.values(dagQuery.data?.stages ?? {});

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
        fitViewOptions={{ padding: 0.12, minZoom: 0.3 }}
        minZoom={0.3}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_event, node) => setOpenStageId(Number(node.id))}
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
        {stages.length > 0 && (
          <Panel position="top-right">
            <ModelPanel
              stages={stages}
              highlightedModel={highlightedModel}
              onHighlight={setHighlightedModel}
            />
          </Panel>
        )}
        <RefitOnChange nodeCount={nodes.length} orientation={orientation} />
      </ReactFlow>

      <CallsDrawer
        pipelineId={pipelineId}
        stageId={openStageId}
        stageName={openStage?.name ?? ""}
        model={openStage?.model ?? ""}
        onClose={() => setOpenStageId(null)}
      />
    </div>
  );
}
