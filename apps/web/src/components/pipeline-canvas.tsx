import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ReactFlow,
  Background,
  Controls,
  Panel,
  useReactFlow,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { getPipelineDag, type StagePhase, type StageRunState } from "@/lib/api";
import { StageNode, type StageFlowNode } from "@/components/stage-node";
import {
  computeCanvasLayout,
  edgeKindFor,
  loadCanvasLayoutChoice,
  saveCanvasLayoutChoice,
  type CanvasLayoutChoice,
  type CanvasLayoutPreset,
  type CanvasOrientation,
} from "@/lib/canvas-layout";
import { cn } from "@/lib/utils";

const nodeTypes = { stage: StageNode };

export interface PipelineCanvasProps {
  pipelineId: number;
  /** Live per-stage run state (keyed by stage DB id as a string) — pass a
   * migration's `stage_states` while it's running/just finished to color
   * and pulse the matching nodes. Omit for the static, read-only canvas. */
  stageStates?: Record<string, StageRunState>;
  /** Live sub-step of whichever stage is currently "running" — a
   * migration-level field (not per-stage), so it only ever applies to the
   * one node whose stageStates entry is "running". Pass a migration's
   * `progress_substep` while it's running. */
  runningSubstep?: StagePhase | null;
  className?: string;
  /** Called with a stage's DB id when its node is clicked — used by
   * pipeline-workspace.tsx's Canvas tab to open the stage's rubric drawer.
   * Omit for the static/read-only or migration-run embeds, which don't
   * need node interaction. */
  onNodeClick?: (stageId: number) => void;
}

/**
 * Shared React Flow DAG canvas for a pipeline's Stage[]. Used both by the
 * standalone pipeline-detail screen (no `stageStates` — static view) and by
 * the migration run screen (with `stageStates`, polled live — see Phase 2 /
 * DEV_TRACKER.md "Live DAG/run status view").
 *
 * Layout is user-switchable (see lib/canvas-layout.ts for the presets and
 * why "grid" is the default) via the toolbar in the top-right corner, and
 * the choice is remembered per pipeline. During a live migration, edges
 * touching the running stage carry the animated "beam" treatment and edges
 * between finished stages settle into the pass color — the DAG reads as a
 * picture of how far the light has travelled, not just colored dots.
 */
export function PipelineCanvas({
  pipelineId,
  stageStates,
  runningSubstep,
  className,
  onNodeClick,
}: PipelineCanvasProps) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["pipeline-dag", pipelineId],
    queryFn: () => getPipelineDag(pipelineId),
  });

  const [layout, setLayout] = useState<CanvasLayoutChoice>(() =>
    loadCanvasLayoutChoice(pipelineId)
  );
  useEffect(() => {
    saveCanvasLayoutChoice(pipelineId, layout);
  }, [pipelineId, layout]);

  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [] as StageFlowNode[], edges: [] as Edge[] };

    const positions = computeCanvasLayout(data.layers, layout);

    const nodes: StageFlowNode[] = data.layers.flatMap((layer) =>
      layer.stage_ids.map((stageId) => {
        const runState = stageStates?.[String(stageId)];
        return {
          id: String(stageId),
          type: "stage" as const,
          position: positions[String(stageId)] ?? { x: 0, y: 0 },
          data: {
            stage: data.stages[String(stageId)],
            runState,
            // progress_substep is migration-level, not per-stage - only
            // ever attach it to the one node actually "running".
            substep: runState === "running" ? runningSubstep : undefined,
            orientation: layout.orientation,
          },
        };
      })
    );

    const edges: Edge[] = data.edges.map((edge) => {
      const kind = edgeKindFor(
        stageStates?.[String(edge.from_stage_id)],
        stageStates?.[String(edge.to_stage_id)]
      );
      return {
        id: `${edge.from_stage_id}-${edge.to_stage_id}`,
        source: String(edge.from_stage_id),
        target: String(edge.to_stage_id),
        className:
          kind === "beam" ? "edge-beam" : kind === "passed" ? "edge-passed" : undefined,
        style: kind === "plain" ? { stroke: "var(--line)" } : undefined,
      };
    });

    return { nodes, edges };
  }, [data, stageStates, runningSubstep, layout]);

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
        onNodeClick={onNodeClick ? (_event, node) => onNodeClick(Number(node.id)) : undefined}
      >
        <Background />
        <Controls />
        <Panel position="top-right">
          <CanvasLayoutToolbar layout={layout} onChange={setLayout} />
        </Panel>
        <RefitOnChange nodeCount={nodes.length} layout={layout} />
      </ReactFlow>
    </div>
  );
}

/** Re-run fitView whenever the layout choice or the stage count changes —
 * the `fitView` prop only applies on first mount, so without this a preset
 * switch (or a new run adding stages) leaves the graph half off-screen. */
function RefitOnChange({
  nodeCount,
  layout,
}: {
  nodeCount: number;
  layout: CanvasLayoutChoice;
}) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    if (nodeCount === 0) return;
    // Next frame: let React Flow measure the repositioned nodes first.
    const frame = requestAnimationFrame(() => {
      fitView({ padding: 0.1 });
    });
    return () => cancelAnimationFrame(frame);
  }, [nodeCount, layout, fitView]);
  return null;
}

const PRESET_OPTIONS: { value: CanvasLayoutPreset; label: string; title: string }[] = [
  { value: "grid", label: "Grid", title: "Compact wrap — fits big pipelines on screen" },
  { value: "layered", label: "Layered", title: "One column per dependency layer" },
];

const ORIENTATION_OPTIONS: { value: CanvasOrientation; label: string; title: string }[] = [
  { value: "horizontal", label: "→", title: "Horizontal (left to right)" },
  { value: "vertical", label: "↓", title: "Vertical (top to bottom)" },
];

function CanvasLayoutToolbar({
  layout,
  onChange,
}: {
  layout: CanvasLayoutChoice;
  onChange: (next: CanvasLayoutChoice) => void;
}) {
  return (
    <div className="flex items-center gap-2" role="toolbar" aria-label="Canvas layout">
      <SegmentedGroup
        ariaLabel="Layout preset"
        options={PRESET_OPTIONS}
        value={layout.preset}
        onSelect={(preset) => onChange({ ...layout, preset })}
      />
      <SegmentedGroup
        ariaLabel="Layout orientation"
        options={ORIENTATION_OPTIONS}
        value={layout.orientation}
        onSelect={(orientation) => onChange({ ...layout, orientation })}
      />
    </div>
  );
}

function SegmentedGroup<T extends string>({
  ariaLabel,
  options,
  value,
  onSelect,
}: {
  ariaLabel: string;
  options: { value: T; label: string; title: string }[];
  value: T;
  onSelect: (value: T) => void;
}) {
  return (
    <div
      className="flex overflow-hidden rounded-control border border-line bg-paper"
      role="group"
      aria-label={ariaLabel}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            title={option.title}
            aria-pressed={selected}
            onClick={() => onSelect(option.value)}
            className={cn(
              "px-2.5 py-1 text-12 font-medium transition-colors duration-fast ease-out",
              selected
                ? "bg-beam-soft text-beam"
                : "text-ink-soft hover:bg-beam-soft/40 hover:text-ink"
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
