import { describe, it, expect, beforeEach } from "vitest";
import {
  computeCanvasLayout,
  edgeKindFor,
  loadCanvasLayoutChoice,
  saveCanvasLayoutChoice,
  DEFAULT_CANVAS_LAYOUT,
  type XY,
} from "./canvas-layout";

/** Card footprint dagre lays out around — must match the constants inside
 * canvas-layout.ts (not exported, so re-declared here; a drift between the
 * two would only make this test's overlap margin wrong, never mask a real
 * regression, since dagre itself is still the one deciding positions). */
const NODE_WIDTH = 232;
const NODE_HEIGHT = 150;

function chain(count: number): { stage_ids: number[] }[] {
  return Array.from({ length: count }, (_, i) => ({ stage_ids: [i + 1] }));
}

function chainEdges(count: number): { from_stage_id: number; to_stage_id: number }[] {
  return Array.from({ length: count - 1 }, (_, i) => ({
    from_stage_id: i + 1,
    to_stage_id: i + 2,
  }));
}

/** True if two node boxes (top-left `positions[id]`, fixed NODE_WIDTH/
 * NODE_HEIGHT footprint) overlap at all. */
function boxesOverlap(a: XY, b: XY): boolean {
  return (
    a.x < b.x + NODE_WIDTH &&
    b.x < a.x + NODE_WIDTH &&
    a.y < b.y + NODE_HEIGHT &&
    b.y < a.y + NODE_HEIGHT
  );
}

function assertNoOverlaps(positions: Record<string, XY>) {
  const entries = Object.values(positions);
  for (let i = 0; i < entries.length; i++) {
    for (let j = i + 1; j < entries.length; j++) {
      expect(boxesOverlap(entries[i], entries[j])).toBe(false);
    }
  }
}

describe("computeCanvasLayout (dagre)", () => {
  it("lays out a long mostly-sequential chain (the owner's real 35-stage shape) with zero overlaps", () => {
    // 31 layers, 29 of them single-node - the same shape DEV_TRACKER.md
    // records as the real pipeline that used to overflow the viewport.
    const layers = chain(35);
    const edges = chainEdges(35);
    const positions = computeCanvasLayout(layers, edges, { orientation: "horizontal", spacing: "compact" });

    expect(Object.keys(positions)).toHaveLength(35);
    assertNoOverlaps(positions);
  });

  it("handles one very wide layer (many nodes with no edges between them) with zero overlaps", () => {
    // A single wide layer is exactly the shape the old hand-rolled
    // "layered" preset special-cased (MAX_PER_LAYER_LINE wrapping) - dagre
    // needs no special case, it just spaces same-rank nodes apart.
    const wideLayer = Array.from({ length: 12 }, (_, i) => i + 1);
    const layers = [{ stage_ids: wideLayer }, { stage_ids: [100] }];
    const edges = wideLayer.map((id) => ({ from_stage_id: id, to_stage_id: 100 }));

    const positions = computeCanvasLayout(layers, edges, { orientation: "horizontal", spacing: "compact" });

    expect(Object.keys(positions)).toHaveLength(13);
    assertNoOverlaps(positions);
  });

  it("places dependent stages in increasing order along the flow axis", () => {
    const layers = [{ stage_ids: [1] }, { stage_ids: [2] }, { stage_ids: [3] }];
    const edges = [
      { from_stage_id: 1, to_stage_id: 2 },
      { from_stage_id: 2, to_stage_id: 3 },
    ];

    const horizontal = computeCanvasLayout(layers, edges, { orientation: "horizontal", spacing: "compact" });
    expect(horizontal["1"].x).toBeLessThan(horizontal["2"].x);
    expect(horizontal["2"].x).toBeLessThan(horizontal["3"].x);

    const vertical = computeCanvasLayout(layers, edges, { orientation: "vertical", spacing: "compact" });
    expect(vertical["1"].y).toBeLessThan(vertical["2"].y);
    expect(vertical["2"].y).toBeLessThan(vertical["3"].y);
  });

  it("swaps the dominant axis between horizontal and vertical orientation", () => {
    const layers = [{ stage_ids: [1] }, { stage_ids: [2, 3] }, { stage_ids: [4] }];
    const edges = [
      { from_stage_id: 1, to_stage_id: 2 },
      { from_stage_id: 1, to_stage_id: 3 },
      { from_stage_id: 2, to_stage_id: 4 },
      { from_stage_id: 3, to_stage_id: 4 },
    ];

    const horizontal = computeCanvasLayout(layers, edges, { orientation: "horizontal", spacing: "compact" });
    const vertical = computeCanvasLayout(layers, edges, { orientation: "vertical", spacing: "compact" });

    // Horizontal: rank (dependency depth) drives x, same-rank siblings (2,3)
    // spread across y. Vertical: rank drives y, siblings spread across x.
    expect(horizontal["2"].x).toBe(horizontal["3"].x);
    expect(horizontal["2"].y).not.toBe(horizontal["3"].y);
    expect(vertical["2"].y).toBe(vertical["3"].y);
    expect(vertical["2"].x).not.toBe(vertical["3"].x);
  });

  it("places an isolated node with no edges without throwing", () => {
    const layers = [{ stage_ids: [1] }, { stage_ids: [2] }];
    const positions = computeCanvasLayout(layers, [], { orientation: "horizontal", spacing: "compact" });

    expect(Object.keys(positions)).toHaveLength(2);
    assertNoOverlaps(positions);
  });

  it("returns an empty map for an empty pipeline", () => {
    expect(computeCanvasLayout([], [], { orientation: "horizontal", spacing: "compact" })).toEqual({});
  });

  it("skips an edge referencing an unknown stage id instead of throwing", () => {
    const layers = [{ stage_ids: [1] }, { stage_ids: [2] }];
    const edges = [
      { from_stage_id: 1, to_stage_id: 2 },
      { from_stage_id: 1, to_stage_id: 999 }, // 999 isn't in `layers`
    ];

    expect(() => computeCanvasLayout(layers, edges, { orientation: "horizontal", spacing: "compact" })).not.toThrow();
  });

  it("'spacious' places ranks and same-rank siblings further apart than 'compact', still with zero overlaps", () => {
    // A long chain (rank spacing) plus one wide rank (sibling spacing), so
    // both `ranksep` and `nodesep` are actually exercised, not just one.
    const wideLayer = [10, 11, 12];
    const layers = [{ stage_ids: [1] }, { stage_ids: [2] }, { stage_ids: wideLayer }, { stage_ids: [3] }];
    const edges = [
      { from_stage_id: 1, to_stage_id: 2 },
      ...wideLayer.map((id) => ({ from_stage_id: 2, to_stage_id: id })),
      ...wideLayer.map((id) => ({ from_stage_id: id, to_stage_id: 3 })),
    ];

    const compact = computeCanvasLayout(layers, edges, { orientation: "horizontal", spacing: "compact" });
    const spacious = computeCanvasLayout(layers, edges, { orientation: "horizontal", spacing: "spacious" });
    assertNoOverlaps(compact);
    assertNoOverlaps(spacious);

    // Rank spacing (ranksep, the flow/x axis in horizontal orientation):
    // stage 1 to stage 2's gap must be strictly larger under "spacious".
    const compactRankGap = compact["2"].x - compact["1"].x;
    const spaciousRankGap = spacious["2"].x - spacious["1"].x;
    expect(spaciousRankGap).toBeGreaterThan(compactRankGap);

    // Sibling spacing (nodesep, the cross axis): the wide rank's outermost
    // two nodes' y-gap must also be strictly larger under "spacious".
    const compactYs = wideLayer.map((id) => compact[String(id)].y).sort((a, b) => a - b);
    const spaciousYs = wideLayer.map((id) => spacious[String(id)].y).sort((a, b) => a - b);
    const compactSiblingSpan = compactYs[compactYs.length - 1] - compactYs[0];
    const spaciousSiblingSpan = spaciousYs[spaciousYs.length - 1] - spaciousYs[0];
    expect(spaciousSiblingSpan).toBeGreaterThan(compactSiblingSpan);
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

  it("defaults to horizontal orientation and compact spacing when nothing is stored", () => {
    expect(loadCanvasLayoutChoice(42)).toEqual(DEFAULT_CANVAS_LAYOUT);
    expect(DEFAULT_CANVAS_LAYOUT.orientation).toBe("horizontal");
    expect(DEFAULT_CANVAS_LAYOUT.spacing).toBe("compact");
  });

  it("round-trips a saved choice (orientation and spacing) per pipeline", () => {
    saveCanvasLayoutChoice(42, { orientation: "vertical", spacing: "spacious" });

    expect(loadCanvasLayoutChoice(42)).toEqual({ orientation: "vertical", spacing: "spacious" });
    // A different pipeline keeps its own default.
    expect(loadCanvasLayoutChoice(7)).toEqual(DEFAULT_CANVAS_LAYOUT);
  });

  it("defaults spacing to 'compact' for a saved value that predates the spacing field", () => {
    localStorage.setItem("reprompt.canvas-layout.42", JSON.stringify({ orientation: "vertical" }));
    expect(loadCanvasLayoutChoice(42)).toEqual({ orientation: "vertical", spacing: "compact" });
  });

  it("falls back to the default on corrupted storage", () => {
    localStorage.setItem("reprompt.canvas-layout.42", "{not json");
    expect(loadCanvasLayoutChoice(42)).toEqual(DEFAULT_CANVAS_LAYOUT);

    localStorage.setItem("reprompt.canvas-layout.42", JSON.stringify({ orientation: "bogus" }));
    expect(loadCanvasLayoutChoice(42)).toEqual(DEFAULT_CANVAS_LAYOUT);
  });

  it("ignores a stale 'preset' field from before the dagre migration", () => {
    localStorage.setItem(
      "reprompt.canvas-layout.42",
      JSON.stringify({ preset: "layered", orientation: "vertical" })
    );
    expect(loadCanvasLayoutChoice(42)).toEqual({ orientation: "vertical", spacing: "compact" });
  });
});
