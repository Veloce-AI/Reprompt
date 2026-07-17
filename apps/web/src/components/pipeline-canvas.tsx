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
 * Node positions come from `@dagrejs/dagre` (see lib/canvas-layout.ts) —
 * flow direction (horizontal/vertical) is user-switchable via the toolbar in
 * the top-right corner, and the choice is remembered per pipeline. During a
 * live migration, edges touching the running stage carry the animated
 * "beam" treatment and edges between finished stages settle into the pass
 * color — the DAG reads as a picture of how far the light has travelled,
 * not just colored dots.
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

    const positions = computeCanvasLayout(data.layers, data.edges, layout);

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
        fitViewOptions={FIT_VIEW_OPTIONS}
        minZoom={CANVAS_MIN_ZOOM}
        proOptions={{ hideAttribution: true }}
        onNodeClick={onNodeClick ? (_event, node) => onNodeClick(Number(node.id)) : undefined}
      >
        <Background />
        <Controls />
        <Panel position="top-right">
          <CanvasLayoutToolbar layout={layout} onChange={setLayout} />
        </Panel>
        {/* `stageStates !== undefined` (not its contents) as a refit
            trigger: pipeline-workspace.tsx's Canvas tab overlay mounts its
            "Migration running" pill as a sibling *above* this whole
            component once a live migration is found - a real layout change
            (the canvas's available height shrinks) that isn't captured by
            nodeCount/layout alone, and arrives on a later render than this
            component's own mount (the migrations-list/status queries
            resolve asynchronously), so the initial `fitView` already
            measured the taller, pre-pill height. Deliberately not keyed on
            `stageStates`'s contents/identity - that changes every 2s poll
            while running, and refitting that often would yank a user's pan/
            zoom out from under them while they're watching the live view. */}
        <RefitOnChange
          nodeCount={nodes.length}
          layout={layout}
          hasLiveOverlay={stageStates !== undefined}
        />
      </ReactFlow>
    </div>
  );
}

// React Flow's own default minZoom is 0.5 — plenty for a small DAG, but a
// real wide pipeline (many parallel stages at the same dependency depth, or
// a long chain) can need a far smaller zoom to fit the whole graph in the
// viewport at once. Without lowering this, fitView silently clamps at 0.5
// and nodes past that point render off-screen even though "fitView ran" -
// React Flow's own fitView implementation reads its call-site `minZoom`
// option ahead of the instance-wide prop, so both are set here for
// belt-and-suspenders (the prop also raises the ceiling a user's own manual
// zoom-out can reach).
const CANVAS_MIN_ZOOM = 0.05;
const FIT_VIEW_OPTIONS = { padding: 0.1, minZoom: CANVAS_MIN_ZOOM };

/** Re-run fitView whenever the layout choice or the stage count changes —
 * the `fitView` prop only applies on first mount, so without this an
 * orientation switch (or a new run adding stages) leaves the graph half
 * off-screen. */
function RefitOnChange({
  nodeCount,
  layout,
  hasLiveOverlay,
}: {
  nodeCount: number;
  layout: CanvasLayoutChoice;
  hasLiveOverlay: boolean;
}) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    if (nodeCount === 0) return;
    // Two nested frames, not one: React Flow measures each node's real
    // rendered size via ResizeObserver (nodes here have no explicit
    // width/height, so fitView's bounds are only as good as that
    // measurement) and ResizeObserver callbacks land *after* a frame's
    // layout/style pass, i.e. one frame later than a same-frame
    // requestAnimationFrame callback can see. A single rAF was measured
    // (Playwright, real DOM) to occasionally fit against a not-yet-updated
    // size for a node whose height depends on its live run state (the
    // "running" node's extra sub-step line) - one frame short. Waiting an
    // extra frame gives that observer time to fire first.
    let cleanupInner = () => {};
    const frame = requestAnimationFrame(() => {
      const frame2 = requestAnimationFrame(() => {
        fitView(FIT_VIEW_OPTIONS);
      });
      cleanupInner = () => cancelAnimationFrame(frame2);
    });
    return () => {
      cancelAnimationFrame(frame);
      cleanupInner();
    };
  }, [nodeCount, layout, hasLiveOverlay, fitView]);
  return null;
}

const ORIENTATION_OPTIONS: { value: CanvasOrientation; label: string; title: string }[] = [
  { value: "horizontal", label: "→", title: "Horizontal (left to right)" },
  { value: "vertical", label: "↓", title: "Vertical (top to bottom)" },
];

// Dagre computes real, non-overlapping spacing from the graph's own edges,
// so the old hand-rolled "Grid" (compact wrap) vs. "Layered" (one column per
// dependency layer) preset picker no longer has a job to do — both existed
// only to work around the previous hand-rolled layout math's failure modes.
// Flow direction is still a real, user-meaningful choice (a wide pipeline
// often reads better top-to-bottom), so that toggle stays.
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
