import type { StageRunState } from "@/lib/api";

/**
 * Pure layout math for the pipeline DAG canvas (pipeline-canvas.tsx), kept
 * out of the component so it can be unit-tested without React Flow/jsdom
 * layout. Two presets, both orientation-aware, chosen to cover the two real
 * pipeline shapes we've seen:
 *
 * - "layered": classic topological columns (the canvas's original layout).
 *   Reads dependency structure best, but a mostly-sequential pipeline (the
 *   owner's 35-stage trace is 31 layers, 29 of them single-node) becomes a
 *   ~9,000px strip that fitView can only show as unreadable dust.
 * - "grid" (default): topological order snake-wrapped into rows of
 *   MAX_PER_LINE, so a 35-stage pipeline fits a laptop viewport at a
 *   readable zoom. Snaking (odd lines reversed) keeps consecutive stages
 *   adjacent, so most edges stay short.
 */

export type CanvasLayoutPreset = "grid" | "layered";
export type CanvasOrientation = "horizontal" | "vertical";

export interface CanvasLayoutChoice {
  preset: CanvasLayoutPreset;
  orientation: CanvasOrientation;
}

export const DEFAULT_CANVAS_LAYOUT: CanvasLayoutChoice = {
  preset: "grid",
  orientation: "horizontal",
};

/** Spacing along the flow direction (node card is w-56 = 224px). */
const MAIN_GAP = 280;
/**
 * Spacing across the flow direction. This has to be orientation-aware: in
 * "horizontal" orientation the cross axis runs top-to-bottom, so it only
 * needs to clear the card's ~150-175px height. In "vertical" orientation
 * the cross axis runs left-to-right, so it needs to clear the card's full
 * 224px width (w-56) instead - reusing the height-tuned gap there packed
 * cards 224px wide only 190px apart, overlapping them directly and making
 * their text collide across node boundaries (see DEV_TRACKER.md "Fix
 * overlapping stage node text").
 */
const CROSS_GAP_HORIZONTAL = 190;
const CROSS_GAP_VERTICAL = 280;

function crossGapFor(orientation: CanvasOrientation): number {
  return orientation === "vertical" ? CROSS_GAP_VERTICAL : CROSS_GAP_HORIZONTAL;
}
/** Grid preset: how many nodes per row (horizontal) / column (vertical). */
export const MAX_PER_LINE = 5;
/** Layered preset: a single layer wider than this wraps into extra lines. */
export const MAX_PER_LAYER_LINE = 6;

export interface XY {
  x: number;
  y: number;
}

interface LayerLike {
  stage_ids: number[];
}

function oriented(main: number, cross: number, orientation: CanvasOrientation): XY {
  return orientation === "horizontal" ? { x: main, y: cross } : { x: cross, y: main };
}

/** Positions keyed by stage id (string, matching React Flow node ids). */
export function computeCanvasLayout(
  layers: LayerLike[],
  choice: CanvasLayoutChoice
): Record<string, XY> {
  return choice.preset === "grid"
    ? computeGridLayout(layers, choice.orientation)
    : computeLayeredLayout(layers, choice.orientation);
}

function computeGridLayout(
  layers: LayerLike[],
  orientation: CanvasOrientation
): Record<string, XY> {
  const ordered = layers.flatMap((layer) => layer.stage_ids);
  const positions: Record<string, XY> = {};
  const crossGap = crossGapFor(orientation);
  ordered.forEach((stageId, index) => {
    const line = Math.floor(index / MAX_PER_LINE);
    const rawSlot = index % MAX_PER_LINE;
    // Snake: odd lines run backwards so stage n+1 sits next to (or right
    // below) stage n instead of a full line-width away.
    const slot = line % 2 === 1 ? MAX_PER_LINE - 1 - rawSlot : rawSlot;
    positions[String(stageId)] = oriented(slot * MAIN_GAP, line * crossGap, orientation);
  });
  return positions;
}

function computeLayeredLayout(
  layers: LayerLike[],
  orientation: CanvasOrientation
): Record<string, XY> {
  const positions: Record<string, XY> = {};
  const crossGap = crossGapFor(orientation);
  // A very wide layer wraps into multiple main-axis lines instead of one
  // endless cross-axis strip; later layers shift over by however many lines
  // the wrapped layer occupied.
  let mainLine = 0;
  for (const layer of layers) {
    const lines = Math.max(1, Math.ceil(layer.stage_ids.length / MAX_PER_LAYER_LINE));
    layer.stage_ids.forEach((stageId, index) => {
      const lineWithinLayer = Math.floor(index / MAX_PER_LAYER_LINE);
      const crossSlot = index % MAX_PER_LAYER_LINE;
      positions[String(stageId)] = oriented(
        (mainLine + lineWithinLayer) * MAIN_GAP,
        crossSlot * crossGap,
        orientation
      );
    });
    mainLine += lines;
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
    const preset: CanvasLayoutPreset = parsed.preset === "layered" ? "layered" : "grid";
    const orientation: CanvasOrientation =
      parsed.orientation === "vertical" ? "vertical" : "horizontal";
    return { preset, orientation };
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
