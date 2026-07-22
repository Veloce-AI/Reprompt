import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
  useReactFlow,
  Handle,
  Position,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  getPipelineDag,
  listStageRecords,
  type StagePhase,
  type StageRecordOut,
  type StageRunState,
} from "@/lib/api";
import { StageNode, type StageFlowNode, type PipelineCanvasMode } from "@/components/stage-node";
import {
  computeCanvasLayout,
  edgeKindFor,
  loadCanvasLayoutChoice,
  saveCanvasLayoutChoice,
  type CanvasLayoutChoice,
  type CanvasOrientation,
  type CanvasSpacing,
} from "@/lib/canvas-layout";
import { cn } from "@/lib/utils";

// ---- Analytics-mode node types (folded in from the former Graph tab —
// see DEV_TRACKER.md's Canvas/Graph merge entry) ----

type ModelGraphNodeData = {
  model: string;
  stageCount: number;
  isHighlighted: boolean;
};
type ModelGraphFlowNode = Node<ModelGraphNodeData, "model">;

type CallGraphNodeData = {
  record: StageRecordOut;
  index: number;
};
type CallGraphFlowNode = Node<CallGraphNodeData, "call">;

type PipelineFlowNode = StageFlowNode | ModelGraphFlowNode | CallGraphFlowNode;

function modelNodeId(model: string) {
  // Replace non-word chars so the id is safe as a CSS selector / React key.
  return `model-${model.replace(/\W/g, "_")}`;
}

/** Fixed-column node to the right of all stages. Clicking highlights the
 * stages that use this model — pins/unpins, not hover (a deliberate
 * decision, see the merge plan). No per-model color-coding: an unbounded
 * categorical set of models would violate the "fixed hue order, never
 * cycled" dataviz rule, so this stays text + highlight only. */
function ModelGraphNode({ data }: NodeProps<ModelGraphFlowNode>) {
  const { model, stageCount, isHighlighted } = data;
  return (
    <div
      className={cn(
        "w-48 cursor-pointer select-none rounded-card border-2 px-3 py-2.5 shadow-sm transition-colors duration-base ease-out",
        isHighlighted
          ? "border-beam bg-beam-soft shadow-[0_0_0_3px_var(--beam-soft)]"
          : "border-line bg-paper hover:border-beam/50"
      )}
    >
      <Handle type="target" position={Position.Left} className="!bg-beam/60" />
      <p
        className={cn("truncate text-12 font-medium", isHighlighted ? "text-beam" : "text-ink")}
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

/** Appears below its parent stage when the "View inference calls" affordance
 * is clicked. Compact — just the key stats; full input/output stays in the
 * Data tab's record browser. */
function CallGraphNode({ data }: NodeProps<CallGraphFlowNode>) {
  const { record, index } = data;
  return (
    <div className="w-56 select-none rounded-control border border-line bg-paper px-3 py-2 shadow-sm">
      <Handle type="target" position={Position.Top} className="!h-1.5 !w-1.5 !bg-ink-soft" style={{ opacity: 0.4 }} />
      <div className="flex items-center justify-between gap-2">
        <span className="text-12 font-medium text-ink">Call #{index}</span>
        <div className="flex items-center gap-2 font-mono text-11 tabular-nums text-ink-soft">
          {record.tokens_in != null && (
            <span>
              {record.tokens_in}→{record.tokens_out ?? "?"} tok
            </span>
          )}
          {record.latency_ms != null && <span>{Math.round(record.latency_ms)}ms</span>}
        </div>
      </div>
      {record.cost != null && (
        <p className="mt-0.5 font-mono text-11 tabular-nums text-ink-soft">${record.cost.toFixed(4)}</p>
      )}
    </div>
  );
}

const nodeTypes = { stage: StageNode, model: ModelGraphNode, call: CallGraphNode };

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
  /** Whether a migration is *currently running* for this pipeline right
   * now — drives Live/Analytics auto-select (Live while running, Analytics
   * otherwise). Pass the exact signal `pipeline-workspace.tsx`'s
   * `CanvasTabContent` already computes; never derive a second polling
   * mechanism for this. **Important**: that signal must default to `true`
   * (not `false`) while its own "is anything running" query is still
   * loading — see `CanvasTabContent`'s own comment on `migrationRunning`
   * for why: guessing `false` during that brief window and then flipping to
   * `true` moments later (for a pipeline whose migration genuinely *is*
   * running) caused a real, repeatable bug - a mode flip immediately after
   * mount intermittently broke React Flow's edge rendering on this
   * fully-controlled canvas. When omitted, falls back to `stageStates !==
   * undefined` — this is what the Migrations tab's embedded run-view canvas
   * (migration-success-screen.tsx) relies on implicitly, preserving its
   * pre-existing "always live while mounted" behavior without needing its
   * own running-migration tracking. */
  migrationRunning?: boolean;
  className?: string;
  /** Called with a stage's DB id when its node is clicked in Live mode —
   * used by pipeline-workspace.tsx's Canvas tab to open the stage's rubric
   * drawer. Ignored in Analytics mode, where a stage click instead
   * expands/collapses that stage's call drilldown (self-contained, no prop
   * needed). Omit for the static/read-only or migration-run embeds that
   * don't need Live-mode node interaction. */
  onNodeClick?: (stageId: number) => void;
}

/**
 * Shared React Flow DAG canvas for a pipeline's Stage[]. Two modes, one
 * component, one toolbar, one layout engine (see DEV_TRACKER.md's Canvas/
 * Graph merge entry — this replaced the separate "Graph" workspace tab):
 *
 * - **Live**: the original Canvas view — per-stage run-state coloring/
 *   pulsing, sub-step labels, beam-flow edges while a migration executes.
 * - **Analytics**: the former Graph tab's view — a fixed right-hand column
 *   of model nodes (click to pin-highlight the stages using that model) and
 *   per-stage inference-call drilldown (click a stage's "View inference
 *   calls" affordance to fetch and show its individual records inline,
 *   cached per stage so re-expanding is instant).
 *
 * Mode auto-selects Live while a migration is running for this pipeline,
 * Analytics otherwise (see `migrationRunning` above) — but a manual toggle
 * holds for the rest of the session once touched (session-only React state,
 * deliberately NOT persisted to localStorage the way the Spacing/Orientation
 * choice below is, so a stale saved preference can never suppress the
 * auto-Live-during-a-run behavior after a reload).
 *
 * Node positions come from `@dagrejs/dagre` (see lib/canvas-layout.ts) —
 * both flow direction (horizontal/vertical) and card spacing (compact/
 * spacious) are user-switchable via the toolbar in the top-right corner, and
 * the choice is remembered per pipeline, shared by both modes. Layout never
 * shrinks nodes below a legible zoom floor (`CANVAS_MIN_ZOOM` below, the
 * same single floor for both modes) to force everything on screen — a graph
 * too large to fit at that zoom is pannable instead.
 */
export function PipelineCanvas({
  pipelineId,
  stageStates,
  runningSubstep,
  migrationRunning,
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

  // Session-only (not persisted like `layout` above) - a large pipeline
  // benefits from the overview by default, but nothing about hiding it is
  // worth remembering across visits the way flow direction/spacing is.
  const [showMiniMap, setShowMiniMap] = useState(true);

  // Mode: `null` until the user manually picks one this session, in which
  // case that choice wins from then on (until reload) regardless of
  // migrationRunning changing - see this component's own docstring above
  // for why. Effective mode is `modeOverride ?? autoMode`, so as long as the
  // user hasn't touched the toggle, it keeps tracking migrationRunning live
  // (switches the instant a migration starts/finishes), matching the "auto-
  // select fires correctly when a migration starts/ends" requirement.
  const [modeOverride, setModeOverride] = useState<PipelineCanvasMode | null>(null);
  const autoMode: PipelineCanvasMode =
    (migrationRunning ?? stageStates !== undefined) ? "live" : "analytics";
  const mode: PipelineCanvasMode = modeOverride ?? autoMode;

  // Analytics-mode-only state - model highlight (pin/unpin) and per-stage
  // call drilldown (expand/collapse + a fetch cache so re-expanding a stage
  // is instant). Kept here even while unused in Live mode rather than
  // unmounted/remounted, so it doesn't need its own reset logic beyond the
  // explicit "collapse expanded calls on mode switch" effect below.
  const [highlightedModel, setHighlightedModel] = useState<string | null>(null);
  const [expandedStageIds, setExpandedStageIds] = useState(new Set<number>());
  const [stageRecordsMap, setStageRecordsMap] = useState(new Map<number, StageRecordOut[]>());

  // "On mode switch (live→analytics or back), any expanded call-drilldown
  // collapses" - a deliberate simplification per the merge plan, not an
  // oversight. The fetch cache (stageRecordsMap) is NOT cleared here, so
  // re-expanding after switching back is still instant.
  useEffect(() => {
    setExpandedStageIds(new Set());
  }, [mode]);

  // Fetch records for any stage that's been expanded but not yet cached.
  // An effect (not a query per stage) because stage ids aren't known until
  // the DAG loads, so a fixed set of hooks can't be called per-stage.
  useEffect(() => {
    for (const stageId of expandedStageIds) {
      if (!stageRecordsMap.has(stageId)) {
        listStageRecords(pipelineId, { stageId, limit: 8 }).then((page) => {
          setStageRecordsMap((prev) => new Map(prev).set(stageId, page.records));
        });
      }
    }
  }, [expandedStageIds, stageRecordsMap, pipelineId]);

  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [] as PipelineFlowNode[], edges: [] as Edge[] };

    const positions = computeCanvasLayout(data.layers, data.edges, layout);
    const stageList = Object.values(data.stages);

    const stageNodes: StageFlowNode[] = data.layers.flatMap((layer) =>
      layer.stage_ids.map((stageId) => {
        const stage = data.stages[String(stageId)];
        const runState = stageStates?.[String(stageId)];
        return {
          id: String(stageId),
          type: "stage" as const,
          position: positions[String(stageId)] ?? { x: 0, y: 0 },
          // React Flow only draws a node in <MiniMap> once it has a size it
          // can trust (node.measured, populated by its own ResizeObserver -
          // see @xyflow/react's internal `nodeHasDimensions`/`tr()` gate).
          // That sync only happens for apps wired through `onNodesChange`;
          // this canvas is fully controlled (nodes rebuilt via useMemo from
          // query data, no change handler), so `.measured` never lands on
          // these objects and the minimap silently rendered zero nodes
          // until this was added (confirmed via Playwright: 50 canvas nodes
          // in the DOM, 0 `.react-flow__minimap-node` elements). `initialWidth`/
          // `initialHeight` is React Flow's documented escape hatch for
          // exactly this case — a size hint that satisfies the gate without
          // forcing an explicit CSS size (real ResizeObserver measurement
          // still drives the actual on-canvas layout/fitView, unaffected).
          // 224x127 matches stage-node.tsx's Card at its idle size (w-56,
          // measured via Playwright); a taller live "running" card with the
          // substep line (or an analytics-mode card with its extra stat
          // lines) renders slightly larger than this hint in the minimap -
          // an acceptable approximation for an overview map.
          initialWidth: STAGE_NODE_WIDTH,
          initialHeight: STAGE_NODE_HEIGHT,
          data: {
            stage,
            runState,
            // progress_substep is migration-level, not per-stage - only
            // ever attach it to the one node actually "running".
            substep: runState === "running" ? runningSubstep : undefined,
            orientation: layout.orientation,
            mode,
            isExpanded: expandedStageIds.has(stageId),
            canExpandCalls: (stage?.trace_count ?? 0) > 0,
            isModelHighlighted: highlightedModel !== null && stage?.model === highlightedModel,
          },
        };
      })
    );

    const depEdges: Edge[] = data.edges.map((edge) => {
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

    if (mode !== "analytics") {
      return { nodes: stageNodes, edges: depEdges };
    }

    // ---- Analytics-mode-only: model column + call drilldown ----

    const stageRightEdges = stageList.map(
      (s) => (positions[String(s.id)]?.x ?? 0) + STAGE_NODE_WIDTH
    );
    const maxStageRight = stageRightEdges.length ? Math.max(...stageRightEdges) : 0;
    const modelColX = maxStageRight + MODEL_COL_GAP;

    const uniqueModels = [...new Set(stageList.map((s) => s.model))];
    const stageYValues = stageList.map((s) => positions[String(s.id)]?.y ?? 0);
    const minStageY = stageYValues.length ? Math.min(...stageYValues) : 0;
    const maxStageY = stageYValues.length ? Math.max(...stageYValues) : 0;
    const totalModelH =
      uniqueModels.length * MODEL_NODE_H + Math.max(0, uniqueModels.length - 1) * MODEL_V_GAP;
    const modelStartY = (minStageY + maxStageY) / 2 - totalModelH / 2;

    const modelNodes: ModelGraphFlowNode[] = uniqueModels.map((model, i) => ({
      id: modelNodeId(model),
      type: "model" as const,
      position: { x: modelColX, y: modelStartY + i * (MODEL_NODE_H + MODEL_V_GAP) },
      initialWidth: MODEL_NODE_W,
      initialHeight: MODEL_NODE_H,
      data: {
        model,
        stageCount: stageList.filter((s) => s.model === model).length,
        isHighlighted: highlightedModel === model,
      },
    }));

    const callNodes: CallGraphFlowNode[] = [];
    for (const stageId of expandedStageIds) {
      const records = stageRecordsMap.get(stageId) ?? [];
      const pos = positions[String(stageId)];
      if (!pos) continue;
      records.forEach((record, i) => {
        callNodes.push({
          id: `call-${record.id}`,
          type: "call" as const,
          position: {
            x: pos.x + (STAGE_NODE_WIDTH - CALL_NODE_W) / 2,
            y: pos.y + ANALYTICS_STAGE_CARD_H + CALL_FROM_STAGE + i * (CALL_NODE_H + CALL_V_GAP),
          },
          initialWidth: CALL_NODE_W,
          initialHeight: CALL_NODE_H,
          data: { record, index: i + 1 },
        });
      });
    }

    // Model edges (dashed, stage → model node) — from the stage's single
    // shared source handle (same one dependency edges use, see
    // stage-node.tsx's own note on why this node only ever has one handle
    // per type: a dedicated per-edge-kind handle intermittently dropped
    // edges on a larger graph, a real regression only a repeated e2e run
    // caught). React Flow draws a perfectly good bezier from that shared
    // point to the fixed right-hand model column regardless of orientation.
    const modelEdges: Edge[] = stageList.map((stage) => ({
      id: `model-edge-${stage.id}`,
      source: String(stage.id),
      target: modelNodeId(stage.model),
      style: {
        stroke: "var(--beam)",
        strokeWidth: 1.5,
        strokeDasharray: "5 3",
        opacity: highlightedModel === stage.model ? 0.9 : 0.3,
      },
    }));

    // Call edges (straight, stage → call node) — same shared source handle.
    const callEdges: Edge[] = [];
    for (const stageId of expandedStageIds) {
      const records = stageRecordsMap.get(stageId) ?? [];
      records.forEach((record) => {
        callEdges.push({
          id: `call-edge-${record.id}`,
          source: String(stageId),
          target: `call-${record.id}`,
          type: "straight",
          style: { stroke: "var(--ink-soft)", strokeWidth: 1, opacity: 0.4 },
        });
      });
    }

    return {
      nodes: [...stageNodes, ...modelNodes, ...callNodes],
      edges: [...depEdges, ...modelEdges, ...callEdges],
    };
  }, [
    data,
    stageStates,
    runningSubstep,
    layout,
    mode,
    expandedStageIds,
    stageRecordsMap,
    highlightedModel,
  ]);

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
        onNodeClick={(_event, node) => {
          if (mode === "analytics") {
            if (node.type === "stage") {
              const stageId = Number(node.id);
              const stage = data?.stages[String(stageId)];
              if (!stage || (stage.trace_count ?? 0) === 0) return;
              setExpandedStageIds((prev) => {
                const next = new Set(prev);
                if (next.has(stageId)) next.delete(stageId);
                else next.add(stageId);
                return next;
              });
            } else if (node.type === "model") {
              const model = (node.data as ModelGraphNodeData).model;
              setHighlightedModel((prev) => (prev === model ? null : model));
            }
            return;
          }
          if (node.type === "stage" && onNodeClick) onNodeClick(Number(node.id));
        }}
      >
        <Background />
        <Controls />
        {showMiniMap && (
          <MiniMap
            // React Flow's own default (200x150) reads as a fairly large
            // fixed fixture next to the small zoom controls and toolbar
            // already in this canvas's corners - `style.width`/`.height`
            // (not just CSS) drive the minimap's actual SVG pixel size, so
            // this shrinks it to a genuinely small corner overview instead.
            style={{ width: 160, height: 120 }}
            nodeColor={minimapNodeColor}
            nodeStrokeColor="var(--paper)"
            nodeStrokeWidth={2}
            nodeBorderRadius={2}
            bgColor="var(--paper)"
            maskColor="color-mix(in srgb, var(--beam) 10%, transparent)"
            maskStrokeColor="var(--beam)"
            maskStrokeWidth={1.5}
            pannable
            zoomable
            className="!border !border-line !shadow-none"
            ariaLabel="Pipeline overview map"
          />
        )}
        <Panel position="top-right">
          <CanvasLayoutToolbar
            mode={mode}
            onModeChange={setModeOverride}
            layout={layout}
            onChange={setLayout}
            showMiniMap={showMiniMap}
            onToggleMiniMap={() => setShowMiniMap((v) => !v)}
          />
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
          mode={mode}
        />
      </ReactFlow>
    </div>
  );
}

// A first pass at this canvas (see DEV_TRACKER.md's "dagre-based auto
// layout" entry) lowered this to 0.05 so `fitView` could always shrink the
// *entire* graph onto screen at once, no matter how large. That was wrong
// for the shape that actually matters most here: the product owner's real
// pipeline is a long, mostly-linear chain of ~30 single-node layers, and
// "shrink until the whole chain fits in the viewport" crushes every node
// into an illegible sliver (confirmed by rendering that exact shape in a
// real browser — a node card shrank to ~20x12px, no text readable) long
// before it actually "fits". Real diagram tools (Figma, Miro, Linear's own
// graph views) don't chase that goal — they hold a legible zoom floor and
// let the user pan/scroll to the part they want, so that's the model here
// too: 0.5 is React Flow's own conventional default floor, and was
// confirmed by screenshot (not guessed) to keep the stage name, model
// badge, and stats line on stage-node.tsx's Card fully readable. If the
// laid-out graph doesn't fit the viewport at this zoom, `fitView` clamps to
// it and centers on the graph's overall bounds — the excess is simply
// off-screen, reachable by panning (React Flow's own drag-to-pan, no extra
// wiring needed) or by the zoom controls in the corner, not shrunk further.
// This single floor is now shared by both Live and Analytics mode - the
// former Graph tab used its own laxer `minZoom: 0.25`, which was the actual
// root cause of that tab's reported illegibility; it does not survive this
// merge.
const CANVAS_MIN_ZOOM = 0.5;
const FIT_VIEW_OPTIONS = { padding: 0.1, minZoom: CANVAS_MIN_ZOOM };

// stage-node.tsx's Card at its idle size (w-56 = 224px, plus its typical
// content height) - see the `initialWidth`/`initialHeight` comment on the
// node objects above for why this exists at all (unblocking <MiniMap>'s
// render gate, not driving real on-canvas layout).
const STAGE_NODE_WIDTH = 224;
const STAGE_NODE_HEIGHT = 127;

// ---- Analytics-mode-only layout constants (ported from the former Graph
// tab's pipeline-graph.tsx) — model column + call-node placement math only;
// dagre's own stage positions (computeCanvasLayout, shared with Live mode)
// are unaffected by any of these. ----
const MODEL_NODE_W = 192; // w-48
const MODEL_NODE_H = 72;
const MODEL_V_GAP = 20;
const MODEL_COL_GAP = 100; // horizontal gap: rightmost stage right edge → model column left edge
const CALL_NODE_W = 240;
const CALL_NODE_H = 82;
const CALL_V_GAP = 10;
const CALL_FROM_STAGE = 28; // gap from stage bottom to first call node top
// Analytics-mode stage cards render taller than STAGE_NODE_HEIGHT's live-
// mode idle estimate (a few extra stat lines + the expand affordance) -
// this is only used to position call nodes below the card, not to drive
// dagre's own spacing (which uses canvas-layout.ts's own fixed per-mode-
// agnostic estimate, same tolerance the former Graph tab's own
// STAGE_NODE_H already documented).
const ANALYTICS_STAGE_CARD_H = 230;

// Same run-state vocabulary as STATE_BORDER/STATE_DOT in stage-node.tsx
// (idle/running/done/failed -> line/beam/pass/fail), just as raw CSS color
// values instead of Tailwind classes - the MiniMap's `nodeColor` prop sets
// an SVG rect's fill directly, it can't consume a Tailwind class. This is
// the same reason a 50-stage pipeline's live state is worth showing here at
// all: a user watching a big migration should be able to spot which region
// is still running/done/failed from the overview alone, not just the one
// node currently in the viewport. No new tokens - only --beam/--parity-pass/
// --parity-fail/--line, referenced directly since CSS custom properties
// resolve fine inside inline SVG style attributes.
const MINIMAP_NODE_COLOR: Record<StageRunState, string> = {
  idle: "var(--line)",
  running: "var(--beam)",
  done: "var(--parity-pass)",
  failed: "var(--parity-fail)",
};

function minimapNodeColor(node: PipelineFlowNode): string {
  if (node.type !== "stage") return "var(--ink-soft)";
  const runState = node.data.runState;
  return runState ? MINIMAP_NODE_COLOR[runState] : "var(--ink-soft)";
}

/** Re-run fitView whenever the layout choice, mode, or the node count
 * changes — the `fitView` prop only applies on first mount, so without this
 * an orientation switch, a Live/Analytics mode switch (a substantially
 * different node/edge set — the model column alone changes the graph's
 * overall bounds), or a new run adding stages would leave the graph half
 * off-screen. */
function RefitOnChange({
  nodeCount,
  layout,
  hasLiveOverlay,
  mode,
}: {
  nodeCount: number;
  layout: CanvasLayoutChoice;
  hasLiveOverlay: boolean;
  mode: PipelineCanvasMode;
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
  }, [nodeCount, layout, hasLiveOverlay, mode, fitView]);
  return null;
}

const MODE_OPTIONS: { value: PipelineCanvasMode; label: string; title: string }[] = [
  { value: "live", label: "Live", title: "Live run status while a migration executes" },
  { value: "analytics", label: "Analytics", title: "Model breakdown and per-stage inference calls" },
];

const ORIENTATION_OPTIONS: { value: CanvasOrientation; label: string; title: string }[] = [
  { value: "horizontal", label: "→", title: "Horizontal (left to right)" },
  { value: "vertical", label: "↓", title: "Vertical (top to bottom)" },
];

// The old hand-rolled "Grid" vs. "Layered" preset picker (both existed only
// to work around the previous hand-rolled layout math's own failure modes)
// is gone for good — dagre computes real, non-overlapping spacing from the
// graph's own edges regardless of preset. What replaced it is a genuinely
// different choice: how much breathing room dagre leaves between cards
// (`nodesep`/`ranksep`, see lib/canvas-layout.ts's `SPACING` map) — real for
// a long chain specifically, where "Compact" packs stages tightly and
// "Spacious" gives each one more room to read comfortably. Flow direction
// remains its own, orthogonal, real choice (a wide pipeline often reads
// better top-to-bottom), so both toggles sit side by side. Shared by both
// Live and Analytics mode — one layout engine, not two.
const SPACING_OPTIONS: { value: CanvasSpacing; label: string; title: string }[] = [
  { value: "compact", label: "Compact", title: "Compact spacing (tight)" },
  { value: "spacious", label: "Spacious", title: "Spacious spacing (more room between cards)" },
];

function CanvasLayoutToolbar({
  mode,
  onModeChange,
  layout,
  onChange,
  showMiniMap,
  onToggleMiniMap,
}: {
  mode: PipelineCanvasMode;
  onModeChange: (next: PipelineCanvasMode) => void;
  layout: CanvasLayoutChoice;
  onChange: (next: CanvasLayoutChoice) => void;
  showMiniMap: boolean;
  onToggleMiniMap: () => void;
}) {
  return (
    <div className="flex items-center gap-2" role="toolbar" aria-label="Canvas layout">
      <SegmentedGroup ariaLabel="Canvas mode" options={MODE_OPTIONS} value={mode} onSelect={onModeChange} />
      <SegmentedGroup
        ariaLabel="Node spacing"
        options={SPACING_OPTIONS}
        value={layout.spacing}
        onSelect={(spacing) => onChange({ ...layout, spacing })}
      />
      <SegmentedGroup
        ariaLabel="Layout orientation"
        options={ORIENTATION_OPTIONS}
        value={layout.orientation}
        onSelect={(orientation) => onChange({ ...layout, orientation })}
      />
      {/* Own control, not a SegmentedGroup - this is a single on/off switch
          (show/hide the overview map), not a choice between mutually
          exclusive options like mode/spacing/orientation above. */}
      <button
        type="button"
        title={showMiniMap ? "Hide overview map" : "Show overview map"}
        aria-pressed={showMiniMap}
        onClick={onToggleMiniMap}
        className={cn(
          "flex overflow-hidden rounded-control border border-line bg-paper px-2.5 py-1 text-12 font-medium transition-colors duration-fast ease-out",
          showMiniMap
            ? "bg-beam-soft text-beam"
            : "text-ink-soft hover:bg-beam-soft/40 hover:text-ink"
        )}
      >
        Map
      </button>
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
