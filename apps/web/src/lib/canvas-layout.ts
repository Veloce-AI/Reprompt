import dagre from "@dagrejs/dagre";
import type { StageRunState } from "@/lib/api";

/**
 * Pure layout math for the pipeline DAG canvas (pipeline-canvas.tsx), kept
 * out of the component so it can be unit-tested without React Flow/jsdom
 * layout.
 *
 * Node positions are computed by `@dagrejs/dagre` (the actively-maintained
 * fork, not the abandoned `dagre` package) — the standard pairing with React
 * Flow for hierarchical DAG layout. Two hand-rolled presets ("grid" wrap and
 * "layered" columns) used to live here instead; both were replaced because
 * neither generalized to arbitrary DAG shapes — the owner's real 35-stage
 * pipeline (31 layers, one of them wide) still overflowed the viewport or
 * overlapped nodes under both. Dagre computes real rank/order assignments
 * from the graph's actual edges (not just topological layer membership) and
 * sizes gaps to the node's real dimensions, so it handles an arbitrary wide
 * layer or a long chain the same way: correctly, with no preset to choose.
 */

export type CanvasOrientation = "horizontal" | "vertical";

export interface CanvasLayoutChoice {
  orientation: CanvasOrientation;
}

export const DEFAULT_CANVAS_LAYOUT: CanvasLayoutChoice = {
  orientation: "horizontal",
};

/** Must match stage-node.tsx's Card: `w-56` = 224px, plus a little slack for
 * the border. Dagre needs each node's real footprint to size gaps and avoid
 * overlap — an approximate constant is fine since every stage card renders
 * at the same width regardless of content. */
const NODE_WIDTH = 232;
/** Approximate rendered height of a stage-node.tsx Card (name row, optional
 * substep line, model badge, stats line, ParityBeam) — content-dependent in
 * the real DOM, but a fixed estimate gives dagre a stable box to lay out
 * around; a little extra `ranksep`/`nodesep` (below) absorbs the slack so
 * cards never actually touch even when a real one renders taller. */
const NODE_HEIGHT = 150;
/** Gap between adjacent ranks (the flow direction) and within a rank
 * (across the flow direction) — generous enough that two adjacent node
 * cards' real DOM boxes (which can render a bit taller/wider than the
 * NODE_WIDTH/NODE_HEIGHT estimate above) still never overlap. */
const RANK_SEP = 96;
const NODE_SEP = 48;

export interface XY {
  x: number;
  y: number;
}

interface LayerLike {
  stage_ids: number[];
}

interface EdgeLike {
  from_stage_id: number;
  to_stage_id: number;
}

/**
 * Positions keyed by stage id (string, matching React Flow node ids).
 * `layers` supplies the full set of stage ids to place (including any
 * isolated node with no edges at all, which dagre would otherwise still
 * place fine, but we iterate `layers` rather than `edges` to guarantee every
 * node gets a position even in a degenerate all-isolated-nodes DAG).
 */
export function computeCanvasLayout(
  layers: LayerLike[],
  edges: EdgeLike[],
  choice: CanvasLayoutChoice
): Record<string, XY> {
  const stageIds = layers.flatMap((layer) => layer.stage_ids);
  if (stageIds.length === 0) return {};

  const graph = new dagre.graphlib.Graph();
  graph.setGraph({
    rankdir: choice.orientation === "horizontal" ? "LR" : "TB",
    nodesep: NODE_SEP,
    ranksep: RANK_SEP,
  });
  graph.setDefaultEdgeLabel(() => ({}));

  for (const stageId of stageIds) {
    graph.setNode(String(stageId), { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    // Guard against an edge referencing a stage id outside `layers` (would
    // otherwise throw inside dagre) - shouldn't happen for real DAG
    // responses, but a defensive skip is cheap and keeps a malformed payload
    // from blanking the whole canvas.
    const from = String(edge.from_stage_id);
    const to = String(edge.to_stage_id);
    if (graph.hasNode(from) && graph.hasNode(to)) {
      graph.setEdge(from, to);
    }
  }

  dagre.layout(graph);

  const positions: Record<string, XY> = {};
  for (const stageId of stageIds) {
    const node = graph.node(String(stageId));
    // Dagre positions are node *centers*; React Flow positions nodes by
    // their top-left corner.
    positions[String(stageId)] = {
      x: node.x - NODE_WIDTH / 2,
      y: node.y - NODE_HEIGHT / 2,
    };
  }
  return positions;
}

/**
 * Visual kind for an edge, derived from its endpoints' live run states:
 * - "beam": touches the currently-running stage — light is flowing here.
 * - "passed": both endpoints are done — light has passed through.
 * - "plain": everything else (idle/failed/no live migration at all).
 */
export type EdgeKind = "beam" | "passed" | "plain";

export function edgeKindFor(
  sourceState: StageRunState | undefined,
  targetState: StageRunState | undefined
): EdgeKind {
  if (sourceState === "running" || targetState === "running") return "beam";
  if (sourceState === "done" && targetState === "done") return "passed";
  return "plain";
}

// ---- Per-pipeline persistence (localStorage) ----

function storageKey(pipelineId: number): string {
  return `reprompt.canvas-layout.${pipelineId}`;
}

export function loadCanvasLayoutChoice(pipelineId: number): CanvasLayoutChoice {
  try {
    const raw = localStorage.getItem(storageKey(pipelineId));
    if (!raw) return DEFAULT_CANVAS_LAYOUT;
    const parsed = JSON.parse(raw) as Partial<CanvasLayoutChoice>;
    const orientation: CanvasOrientation =
      parsed.orientation === "vertical" ? "vertical" : "horizontal";
    return { orientation };
  } catch {
    return DEFAULT_CANVAS_LAYOUT;
  }
}

export function saveCanvasLayoutChoice(pipelineId: number, choice: CanvasLayoutChoice): void {
  try {
    localStorage.setItem(storageKey(pipelineId), JSON.stringify(choice));
  } catch {
    // Storage full/unavailable - the choice just won't stick, not an error.
  }
}
