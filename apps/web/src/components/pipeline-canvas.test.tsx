import { describe, it, expect } from "vitest";
import { computeMinimapSize } from "./pipeline-canvas";

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
