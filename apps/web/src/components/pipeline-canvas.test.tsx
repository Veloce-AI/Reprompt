import { describe, it, expect } from "vitest";
import {
  computeMinimapSize,
  computeEdgeStrokeWidth,
  EDGE_STROKE_WIDTH_MIN,
  EDGE_STROKE_WIDTH_MAX,
} from "./pipeline-canvas";

/** Minimal duck-typed fixture — computeMinimapSize only reads
 * `position`/`initialWidth`/`initialHeight`, so a full PipelineFlowNode
 * (not exported from pipeline-canvas.tsx) isn't needed here. */
function node(x: number, y: number, w = 224, h = 127) {
  return { position: { x, y }, initialWidth: w, initialHeight: h } as Parameters<
    typeof computeMinimapSize
  >[0][number];
}

describe("computeMinimapSize", () => {
  it("returns the minimum box for an empty graph", () => {
    const result = computeMinimapSize([]);
    expect(result.width).toBeGreaterThan(0);
    expect(result.height).toBeGreaterThan(0);
  });

  it("scales a wide single-rank graph so height isn't letterboxed to near-zero", () => {
    // 15 stages side by side, one rank deep - the reported real-world shape.
    const nodes = Array.from({ length: 15 }, (_, i) => node(i * 260, 0));
    const result = computeMinimapSize(nodes);
    // Height must stay usable (not collapse toward the letterboxed sliver
    // a fixed-aspect box previously produced) while width is capped.
    expect(result.height).toBeGreaterThanOrEqual(60);
    expect(result.width).toBeLessThanOrEqual(300);
  });

  it("scales a tall single-column graph so width isn't letterboxed to near-zero", () => {
    const nodes = Array.from({ length: 15 }, (_, i) => node(0, i * 220));
    const result = computeMinimapSize(nodes);
    expect(result.width).toBeGreaterThanOrEqual(100);
    expect(result.height).toBeLessThanOrEqual(170);
  });

  it("preserves the graph's real aspect ratio (contain, not stretch)", () => {
    // A 2:1 wide-ish graph - the box's aspect ratio should roughly match.
    const nodes = [node(0, 0), node(400, 0), node(0, 200), node(400, 200)];
    const result = computeMinimapSize(nodes);
    const graphAspect = (400 + 224) / (200 + 127); // bbox width/height
    const boxAspect = result.width / result.height;
    expect(boxAspect).toBeCloseTo(graphAspect, 1);
  });

  it("never blows a tiny graph up past a sensible overview size", () => {
    const result = computeMinimapSize([node(0, 0)]);
    expect(result.width).toBeLessThanOrEqual(224 * 0.5 + 1);
    expect(result.height).toBeLessThanOrEqual(127 * 0.5 + 1);
  });
});

describe("computeEdgeStrokeWidth", () => {
  it("returns the minimum weight for an unknown (null) latency", () => {
    expect(computeEdgeStrokeWidth(null, 500, 2000)).toBe(EDGE_STROKE_WIDTH_MIN);
    expect(computeEdgeStrokeWidth(undefined, 500, 2000)).toBe(EDGE_STROKE_WIDTH_MIN);
  });

  it("returns the minimum weight when every known stage has the same latency", () => {
    // maxLatencyMs <= minLatencyMs - nothing to scale against.
    expect(computeEdgeStrokeWidth(800, 800, 800)).toBe(EDGE_STROKE_WIDTH_MIN);
  });

  it("returns the minimum weight for the fastest stage in the pipeline", () => {
    expect(computeEdgeStrokeWidth(500, 500, 2000)).toBe(EDGE_STROKE_WIDTH_MIN);
  });

  it("returns the maximum weight for the slowest stage in the pipeline", () => {
    expect(computeEdgeStrokeWidth(2000, 500, 2000)).toBe(EDGE_STROKE_WIDTH_MAX);
  });

  it("scales linearly between min and max for a stage in the middle", () => {
    // Exactly halfway between 500 and 2000.
    const result = computeEdgeStrokeWidth(1250, 500, 2000);
    const expected = (EDGE_STROKE_WIDTH_MIN + EDGE_STROKE_WIDTH_MAX) / 2;
    expect(result).toBeCloseTo(expected, 5);
  });
});
