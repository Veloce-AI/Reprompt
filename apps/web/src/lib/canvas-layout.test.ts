import { describe, it, expect, beforeEach } from "vitest";
import {
  computeCanvasLayout,
  edgeKindFor,
  loadCanvasLayoutChoice,
  saveCanvasLayoutChoice,
  DEFAULT_CANVAS_LAYOUT,
  MAX_PER_LINE,
} from "./canvas-layout";

function chainLayers(count: number): { stage_ids: number[] }[] {
  // A mostly-sequential pipeline: one node per layer (the owner's real
  // 35-stage trace is 31 layers, 29 of them single-node).
  return Array.from({ length: count }, (_, i) => ({ stage_ids: [i + 1] }));
}

describe("computeCanvasLayout - grid preset", () => {
  it("wraps a long chain into rows of MAX_PER_LINE instead of one endless strip", () => {
    const positions = computeCanvasLayout(chainLayers(35), {
      preset: "grid",
      orientation: "horizontal",
    });

    const xs = Object.values(positions).map((p) => p.x);
    const ys = Object.values(positions).map((p) => p.y);
    // Width is capped at MAX_PER_LINE slots; height grows instead.
    expect(Math.max(...xs)).toBe((MAX_PER_LINE - 1) * 280);
    expect(Math.max(...ys)).toBe(Math.floor(34 / MAX_PER_LINE) * 190);
    // 7 x 5 grid is ~4x squarer than a 35-wide strip - fitView can show it
    // at a readable zoom on a laptop.
    expect(Math.max(...xs) / Math.max(...ys)).toBeLessThan(2);
  });

  it("snakes odd rows so consecutive stages stay adjacent", () => {
    const positions = computeCanvasLayout(chainLayers(12), {
      preset: "grid",
      orientation: "horizontal",
    });

    // Row 0 runs left-to-right...
    expect(positions["1"]).toEqual({ x: 0, y: 0 });
    expect(positions["5"]).toEqual({ x: 4 * 280, y: 0 });
    // ...row 1 runs right-to-left, so stage 6 sits directly under stage 5.
    expect(positions["6"]).toEqual({ x: 4 * 280, y: 190 });
    expect(positions["10"]).toEqual({ x: 0, y: 190 });
    // ...row 2 flips back.
    expect(positions["11"]).toEqual({ x: 0, y: 2 * 190 });
  });

  it("swaps axes in vertical orientation, widening the cross-axis gap to clear the card's width", () => {
    const vertical = computeCanvasLayout(chainLayers(7), {
      preset: "grid",
      orientation: "vertical",
    });

    // Main axis (now y) is unchanged: still MAIN_GAP-spaced per slot.
    expect(vertical["1"]).toEqual({ x: 0, y: 0 });
    expect(vertical["2"]).toEqual({ x: 0, y: 280 });
    expect(vertical["5"]).toEqual({ x: 0, y: 4 * 280 });
    // Cross axis (now x) uses the wider vertical cross gap (280, not 190)
    // so 224px-wide cards don't overlap when stacked side by side - this is
    // the fix for stage-node text overlapping in vertical orientation.
    expect(vertical["6"]).toEqual({ x: 280, y: 4 * 280 });
    expect(vertical["7"]).toEqual({ x: 280, y: 3 * 280 });
  });
});

describe("computeCanvasLayout - layered preset", () => {
  it("keeps the classic one-column-per-layer shape for narrow layers", () => {
    const positions = computeCanvasLayout(
      [{ stage_ids: [1] }, { stage_ids: [2, 3] }, { stage_ids: [4] }],
      { preset: "layered", orientation: "horizontal" }
    );

    expect(positions["1"]).toEqual({ x: 0, y: 0 });
    expect(positions["2"]).toEqual({ x: 280, y: 0 });
    expect(positions["3"]).toEqual({ x: 280, y: 190 });
    expect(positions["4"]).toEqual({ x: 2 * 280, y: 0 });
  });

  it("wraps a very wide layer into extra columns and shifts later layers over", () => {
    const wide = Array.from({ length: 8 }, (_, i) => i + 1); // > MAX_PER_LAYER_LINE
    const positions = computeCanvasLayout(
      [{ stage_ids: wide }, { stage_ids: [100] }],
      { preset: "layered", orientation: "horizontal" }
    );

    // First 6 stack in column 0, overflow continues in column 1...
    expect(positions["1"]).toEqual({ x: 0, y: 0 });
    expect(positions["6"]).toEqual({ x: 0, y: 5 * 190 });
    expect(positions["7"]).toEqual({ x: 280, y: 0 });
    expect(positions["8"]).toEqual({ x: 280, y: 190 });
    // ...and the next layer starts after the wrapped layer's two columns.
    expect(positions["100"]).toEqual({ x: 2 * 280, y: 0 });
  });

  it("swaps axes in vertical orientation, widening the cross-axis gap to clear the card's width", () => {
    const layers = [{ stage_ids: [1] }, { stage_ids: [2, 3] }];
    const vertical = computeCanvasLayout(layers, {
      preset: "layered",
      orientation: "vertical",
    });

    // Main axis (now y) is unchanged: still MAIN_GAP-spaced per layer.
    expect(vertical["1"]).toEqual({ x: 0, y: 0 });
    expect(vertical["2"]).toEqual({ x: 0, y: 280 });
    // Cross axis (now x) uses the wider vertical cross gap (280, not 190)
    // so 224px-wide cards don't overlap when stacked side by side.
    expect(vertical["3"]).toEqual({ x: 280, y: 280 });
  });
});

describe("edgeKindFor", () => {
  it("marks any edge touching the running stage as the beam", () => {
    expect(edgeKindFor("done", "running")).toBe("beam");
    expect(edgeKindFor("running", "idle")).toBe("beam");
  });

  it("settles edges between two finished stages into passed", () => {
    expect(edgeKindFor("done", "done")).toBe("passed");
  });

  it("keeps everything else plain, including the no-migration case", () => {
    expect(edgeKindFor(undefined, undefined)).toBe("plain");
    expect(edgeKindFor("done", "idle")).toBe("plain");
    expect(edgeKindFor("failed", "idle")).toBe("plain");
    expect(edgeKindFor("idle", "idle")).toBe("plain");
  });
});

describe("layout choice persistence", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("defaults to the grid preset when nothing is stored", () => {
    expect(loadCanvasLayoutChoice(42)).toEqual(DEFAULT_CANVAS_LAYOUT);
    expect(DEFAULT_CANVAS_LAYOUT.preset).toBe("grid");
  });

  it("round-trips a saved choice per pipeline", () => {
    saveCanvasLayoutChoice(42, { preset: "layered", orientation: "vertical" });

    expect(loadCanvasLayoutChoice(42)).toEqual({ preset: "layered", orientation: "vertical" });
    // A different pipeline keeps its own default.
    expect(loadCanvasLayoutChoice(7)).toEqual(DEFAULT_CANVAS_LAYOUT);
  });

  it("falls back to the default on corrupted storage", () => {
    localStorage.setItem("reprompt.canvas-layout.42", "{not json");
    expect(loadCanvasLayoutChoice(42)).toEqual(DEFAULT_CANVAS_LAYOUT);

    localStorage.setItem("reprompt.canvas-layout.42", JSON.stringify({ preset: "bogus" }));
    expect(loadCanvasLayoutChoice(42)).toEqual(DEFAULT_CANVAS_LAYOUT);
  });
});
