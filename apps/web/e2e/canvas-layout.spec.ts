import { test, expect, type Page } from "@playwright/test";

/**
 * Verifies the dagre-based canvas layout (see lib/canvas-layout.ts,
 * DEV_TRACKER.md's "Canvas: dagre-based auto layout" and the
 * "Canvas: legible zoom floor + spacing picker" entry that corrects it).
 *
 * The first dagre pass fixed node overlap and got everything technically
 * "inside the viewport" for a WIDE 35-stage mock (two 12-node-wide layers)
 * — but the product owner's real pipeline is the opposite shape: a long,
 * mostly-linear chain of ~30-40 single-node layers with a few 3-wide branch
 * points. "Shrink until it fits" crushes a TALL chain into an illegible
 * sliver long before it visually "fits" a short viewport — confirmed by
 * rendering this exact shape and measuring node boxes around 20x12px with
 * `fitView`'s old `minZoom: 0.05` floor. The fix replaces "everything
 * visible, no scroll" with a legible zoom floor (nodes never render below
 * ~0.5 zoom) plus panning for graphs too large to fit at that zoom, and adds
 * a real "Compact"/"Spacious" spacing picker alongside the existing
 * orientation toggle. This spec's primary suite below tests exactly that
 * shape; a second suite re-verifies the original wide-shape case still has
 * zero overlaps (its "fits inside the viewport" assertion is gone on
 * purpose — expecting a graph to shrink to fit was the bug).
 *
 * Entirely network-mocked (no live API server, no auth) — same pattern as
 * every other e2e spec here. A jsdom/Vitest unit test cannot stand in for
 * this: legibility and real pixel gaps are exactly the class of bug jsdom's
 * fake layout can't catch (see DEV_TRACKER.md's "Product owner report"
 * section for the precedent).
 */

const PIPELINE_ID = 1;

interface MockStage {
  id: number;
  name: string;
}

// ---- Shape 1: the real reported bug — tall, mostly-linear, narrow ----

/** ~38 stages across ~30 layers: a long single-node chain interrupted by
 * four 3-wide branch-and-immediately-merge points — modeled directly on the
 * product owner's screenshot ("a single, mostly-linear vertical column ...
 * a handful of 3-wide branch points, everything else is 1 node per row"),
 * not the wide shape the previous fix's own test happened to use. */
function buildTallNarrowDag() {
  const layerIds: number[][] = [];
  const edges: { from_stage_id: number; to_stage_id: number }[] = [];
  let nextId = 1;
  let prev: number[] | null = null;

  function addLayer(width: number) {
    const ids = Array.from({ length: width }, () => nextId++);
    layerIds.push(ids);
    if (prev) {
      const from = prev;
      ids.forEach((toId, i) => edges.push({ from_stage_id: from[i % from.length], to_stage_id: toId }));
    }
    prev = ids;
  }

  addLayer(1); // root
  for (let i = 0; i < 6; i++) addLayer(1);
  for (let branch = 0; branch < 4; branch++) {
    addLayer(3); // branch point
    addLayer(1); // immediate merge
    for (let i = 0; i < 5; i++) addLayer(1);
  }

  const stages: Record<string, MockStage & Record<string, unknown>> = {};
  for (const layer of layerIds) {
    for (const id of layer) {
      stages[String(id)] = {
        id,
        name: `Stage ${id} — classify_and_route`,
        model: "gpt-4o-mini",
        avg_tokens_in: 120,
        avg_tokens_out: 80,
        avg_latency_ms: 450,
      };
    }
  }

  return {
    dag: {
      pipeline_id: PIPELINE_ID,
      layers: layerIds.map((stage_ids) => ({ stage_ids })),
      stages,
      edges,
    },
    total: nextId - 1,
  };
}

// ---- Shape 2: the previous fix's wide shape — kept for regression ----

/** 35 stages across 6 layers, including two wide layers (12 nodes each) —
 * the shape the original dagre-layout fix's own test used. Kept to confirm
 * this task's changes (raising the zoom floor, adding spacing) don't
 * reintroduce overlap for a wide graph. */
function buildWideDag() {
  const layerRanges: number[][] = [
    [1],
    [2, 3, 4],
    Array.from({ length: 12 }, (_, i) => i + 5),
    Array.from({ length: 12 }, (_, i) => i + 17),
    [29, 30, 31, 32, 33],
    [34, 35],
  ];

  const stages: Record<string, MockStage> = {};
  for (const layer of layerRanges) {
    for (const id of layer) stages[String(id)] = { id, name: `Stage ${id}` };
  }

  const edges: { from_stage_id: number; to_stage_id: number }[] = [];
  const connect = (from: number[], to: number[]) => {
    to.forEach((toId, i) => edges.push({ from_stage_id: from[i % from.length], to_stage_id: toId }));
  };
  connect(layerRanges[0], layerRanges[1]);
  connect(layerRanges[1], layerRanges[2]);
  connect(layerRanges[2], layerRanges[3]);
  connect(layerRanges[3], layerRanges[4]);
  connect(layerRanges[4], layerRanges[5]);

  const dagStages = Object.fromEntries(
    Object.entries(stages).map(([id, s]) => [
      id,
      {
        id: s.id,
        name: s.name,
        model: "gpt-4o-mini",
        avg_tokens_in: 120,
        avg_tokens_out: 80,
        avg_latency_ms: 450,
      },
    ])
  );

  return {
    dag: {
      pipeline_id: PIPELINE_ID,
      layers: layerRanges.map((stage_ids) => ({ stage_ids })),
      stages: dagStages,
      edges,
    },
    total: 35,
  };
}

async function mockPipelineApi(
  page: Page,
  dag: ReturnType<typeof buildTallNarrowDag>["dag"],
  total: number,
  options: { runningMigration?: boolean; stageStates?: Record<string, string> } = {}
) {
  await page.route("**/pipelines", (route) =>
    route.fulfill({
      json: [
        {
          id: PIPELINE_ID,
          name: "Renamed via curl test",
          stage_count: total,
          models_used: ["gpt-4o-mini"],
          benchmark_query_count: 10,
        },
      ],
    })
  );

  await page.route(`**/pipelines/${PIPELINE_ID}/dag`, (route) => route.fulfill({ json: dag }));

  const migration = options.runningMigration
    ? {
        id: 99,
        pipeline_id: PIPELINE_ID,
        target_model_config: { models: ["gpt-4o-mini"] },
        budget: 10,
        parity_threshold: 0.9,
        status: "running",
        total_cost_usd: null,
        stopped_early: false,
        stop_reason: null,
        progress_stage_name: "Stage 17",
        progress_current: 17,
        progress_total: total,
        progress_substep: "critiquing",
        activity_log: [],
        completed_at: null,
        stage_states: options.stageStates ?? {},
      }
    : null;

  await page.route(`**/pipelines/${PIPELINE_ID}/migrations`, (route) =>
    route.fulfill({ json: migration ? [migration] : [] })
  );
  if (migration) {
    await page.route(`**/pipelines/${PIPELINE_ID}/migrations/99/status`, (route) =>
      route.fulfill({ json: migration })
    );
  }
}

interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

function boxesOverlap(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

async function getNodeBoxes(page: Page, selector = ".react-flow__node"): Promise<Box[]> {
  const nodes = page.locator(selector);
  const count = await nodes.count();
  const boxes: Box[] = [];
  for (let i = 0; i < count; i++) {
    const box = await nodes.nth(i).boundingBox();
    expect(box, `node ${i} should have a bounding box`).not.toBeNull();
    if (box) boxes.push(box);
  }
  return boxes;
}

// Since the Canvas/Graph merge, a pipeline with no migration running
// defaults to Analytics mode, which also renders one node per unique model
// in a fixed right column (see pipeline-canvas.tsx's ModelGraphNode). That
// node is deliberately more compact than a stage card (it holds a model
// name and a stage count, nothing else) — the legible-zoom-floor guarantee
// below is specifically about stage-node.tsx's Card (name/model badge/stats
// line all needing to stay readable), so legibility assertions are scoped
// to stage nodes only via React Flow's own `react-flow__node-<type>` class.
// Overlap checks stay on every node (stage *and* model) - nothing should
// ever overlap regardless of type.
async function getStageNodeBoxes(page: Page): Promise<Box[]> {
  return getNodeBoxes(page, ".react-flow__node.react-flow__node-stage");
}

function assertNoOverlap(boxes: Box[]) {
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      expect(boxesOverlap(boxes[i], boxes[j]), `nodes ${i} and ${j} should not overlap`).toBe(false);
    }
  }
}

// stage-node.tsx's Card renders at ~224px wide (w-56) at zoom 1. At the
// canvas's legible zoom floor (pipeline-canvas.tsx's CANVAS_MIN_ZOOM, 0.5,
// confirmed by screenshot to keep the stage name/model badge/stats line
// readable), a node box should render at roughly half that. This threshold
// sits comfortably below that expected value (tolerating layout/measurement
// slack) but well above the ~20px slivers the pre-fix bug produced —
// exactly the gap this regression check needs to catch.
const MIN_LEGIBLE_WIDTH = 90;
const MIN_LEGIBLE_HEIGHT = 50;

function assertLegible(boxes: Box[]) {
  for (const box of boxes) {
    expect(box.width, "node width should stay above the legible-zoom floor").toBeGreaterThanOrEqual(
      MIN_LEGIBLE_WIDTH
    );
    expect(box.height, "node height should stay above the legible-zoom floor").toBeGreaterThanOrEqual(
      MIN_LEGIBLE_HEIGHT
    );
  }
}

async function getZoomScale(page: Page): Promise<number> {
  const style = await page.locator(".react-flow__viewport").getAttribute("style");
  const match = style?.match(/scale\(([\d.]+)\)/);
  expect(match, `expected a scale(...) transform in "${style}"`).not.toBeNull();
  return Number(match![1]);
}

function nodeForStage(page: Page, name: string) {
  return page.locator(".react-flow__node").filter({ has: page.locator(`p[title="${name}"]`) });
}

test.describe("canvas dagre auto-layout — tall/narrow pipeline (~38 stages, mostly linear)", () => {
  test("renders every node at a legible size with zero overlap, in both orientations", async ({ page }) => {
    const { dag, total } = buildTallNarrowDag();
    await mockPipelineApi(page, dag, total);

    await page.goto(`/pipelines/${PIPELINE_ID}?tab=canvas`);
    // Scoped to stage-type nodes specifically (React Flow's own
    // `react-flow__node-<type>` class), not just `.react-flow__node` - since
    // the Canvas/Graph merge, this pipeline (no migration running) now
    // defaults to Analytics mode, which also renders one node per unique
    // model in a fixed right column. That's correct, expected behavior, not
    // something these layout/legibility assertions should trip on.
    await expect(page.locator(".react-flow__node.react-flow__node-stage")).toHaveCount(total);
    await page.waitForTimeout(300);

    let boxes = await getNodeBoxes(page);
    assertNoOverlap(boxes);
    assertLegible(await getStageNodeBoxes(page));
    // This shape is far taller than any reasonable viewport at a legible
    // zoom, so fitView should clamp to the floor exactly, not something
    // in between - proof the floor is actually being enforced.
    expect(await getZoomScale(page)).toBeCloseTo(0.5, 2);

    await page.getByRole("button", { name: "↓", exact: true }).click();
    await page.waitForTimeout(300);

    boxes = await getNodeBoxes(page);
    assertNoOverlap(boxes);
    assertLegible(await getStageNodeBoxes(page));
    expect(await getZoomScale(page)).toBeCloseTo(0.5, 2);
  });

  test("the spacing picker (Compact vs Spacious) measurably widens the real DOM gap between connected nodes, in both orientations, without ever going illegible", async ({
    page,
  }) => {
    const { dag, total } = buildTallNarrowDag();
    await mockPipelineApi(page, dag, total);

    await page.goto(`/pipelines/${PIPELINE_ID}?tab=canvas`);
    await expect(page.locator(".react-flow__node.react-flow__node-stage")).toHaveCount(total);
    await page.waitForTimeout(300);

    async function railGap(axis: "x" | "y"): Promise<number> {
      const a = await nodeForStage(page, "Stage 1 — classify_and_route").boundingBox();
      const b = await nodeForStage(page, "Stage 2 — classify_and_route").boundingBox();
      expect(a).not.toBeNull();
      expect(b).not.toBeNull();
      return Math.abs(b![axis] - a![axis]);
    }

    // Horizontal, compact is the default.
    const compactHorizontalGap = await railGap("x");
    let boxes = await getNodeBoxes(page);
    assertNoOverlap(boxes);
    assertLegible(await getStageNodeBoxes(page));

    await page.getByRole("button", { name: "Spacious", exact: true }).click();
    await page.waitForTimeout(300);
    const spaciousHorizontalGap = await railGap("x");
    boxes = await getNodeBoxes(page);
    assertNoOverlap(boxes);
    assertLegible(await getStageNodeBoxes(page));
    expect(spaciousHorizontalGap).toBeGreaterThan(compactHorizontalGap);

    // Switch to vertical while still on "Spacious".
    await page.getByRole("button", { name: "↓", exact: true }).click();
    await page.waitForTimeout(300);
    const spaciousVerticalGap = await railGap("y");
    boxes = await getNodeBoxes(page);
    assertNoOverlap(boxes);
    assertLegible(await getStageNodeBoxes(page));

    await page.getByRole("button", { name: "Compact", exact: true }).click();
    await page.waitForTimeout(300);
    const compactVerticalGap = await railGap("y");
    boxes = await getNodeBoxes(page);
    assertNoOverlap(boxes);
    assertLegible(await getStageNodeBoxes(page));
    expect(spaciousVerticalGap).toBeGreaterThan(compactVerticalGap);
  });

  test("orientation and spacing choices persist across a reload", async ({ page }) => {
    const { dag, total } = buildTallNarrowDag();
    await mockPipelineApi(page, dag, total);

    await page.goto(`/pipelines/${PIPELINE_ID}?tab=canvas`);
    await expect(page.locator(".react-flow__node.react-flow__node-stage")).toHaveCount(total);

    await page.getByRole("button", { name: "↓", exact: true }).click();
    await page.getByRole("button", { name: "Spacious", exact: true }).click();
    await page.waitForTimeout(300);

    await page.reload();
    await expect(page.locator(".react-flow__node.react-flow__node-stage")).toHaveCount(total);
    await page.waitForTimeout(300);

    await expect(page.getByRole("button", { name: "↓", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "Spacious", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true"
    );

    const boxes = await getNodeBoxes(page);
    assertNoOverlap(boxes);
    assertLegible(await getStageNodeBoxes(page));
  });

  test("zoom controls zoom in past the legible floor and never below it on zoom-out", async ({ page }) => {
    const { dag, total } = buildTallNarrowDag();
    await mockPipelineApi(page, dag, total);

    await page.goto(`/pipelines/${PIPELINE_ID}?tab=canvas`);
    await expect(page.locator(".react-flow__node.react-flow__node-stage")).toHaveCount(total);
    await page.waitForTimeout(300);

    const initialZoom = await getZoomScale(page);
    expect(initialZoom).toBeCloseTo(0.5, 2);

    for (let i = 0; i < 3; i++) {
      await page.locator(".react-flow__controls-zoomin").click();
    }
    await page.waitForTimeout(200);
    const zoomedInScale = await getZoomScale(page);
    expect(zoomedInScale).toBeGreaterThan(initialZoom);

    // A user zoomed in on one node should be able to actually read it - the
    // whole point of the fix.
    assertLegible(await getStageNodeBoxes(page));

    // React Flow disables its own Zoom Out button once minZoom is reached
    // (confirmed here, not assumed) - so "never below the floor" is proven
    // by the button becoming disabled, not by clicking indefinitely.
    const zoomOutButton = page.locator(".react-flow__controls-zoomout");
    for (let i = 0; i < 10; i++) {
      if (await zoomOutButton.isDisabled()) break;
      await zoomOutButton.click();
      await page.waitForTimeout(100);
    }
    await expect(zoomOutButton).toBeDisabled();
    const zoomedOutScale = await getZoomScale(page);
    expect(zoomedOutScale).toBeGreaterThanOrEqual(0.5 - 0.01);
  });

  test("fits exactly on a short-but-not-tiny window - no scrollbar, and nothing clipped either", async ({
    page,
  }) => {
    // Real repro: a 660px-tall window left ~462px available for the tab
    // content wrapper once the pipeline header/tabs/theme-toggle bar are
    // accounted for. PipelineCanvas used to carry a min-h-[480px] floor -
    // a few pixels taller than that 462px - which first showed up as a
    // scrollbar (confirmed live: scrollHeight 480 vs clientHeight 462 on
    // the wrapper), and after making that wrapper overflow-hidden instead
    // of overflow-y-auto, as a clipped sliver of the minimap/controls
    // instead. The floor is gone now (h-full alone is enough - the whole
    // ancestor chain gives this a real, definite height), so this
    // asserts the stronger property: the canvas box exactly matches its
    // container, nothing scrolled *or* clipped.
    await page.setViewportSize({ width: 1330, height: 660 });
    const { dag, total } = buildTallNarrowDag();
    await mockPipelineApi(page, dag, total);

    await page.goto(`/pipelines/${PIPELINE_ID}?tab=canvas`);
    await expect(page.locator(".react-flow__node.react-flow__node-stage")).toHaveCount(total);
    await page.waitForTimeout(300);

    const metrics = await page.evaluate(() => {
      const wrapper = document
        .querySelector(".react-flow__renderer")
        ?.closest("div.overflow-hidden, div.overflow-y-auto");
      if (!wrapper) return null;
      return { scrollHeight: wrapper.scrollHeight, clientHeight: wrapper.clientHeight };
    });
    expect(metrics).not.toBeNull();
    expect(metrics!.scrollHeight).toBe(metrics!.clientHeight);

    const isScrollable = await page.evaluate(() => {
      const wrapper = document
        .querySelector(".react-flow__renderer")
        ?.closest("div.overflow-hidden, div.overflow-y-auto");
      if (!wrapper) return null;
      return (
        wrapper.scrollHeight > wrapper.clientHeight &&
        getComputedStyle(wrapper).overflowY !== "hidden"
      );
    });
    expect(isScrollable).toBe(false);
  });
});

test.describe("canvas dagre auto-layout — wide pipeline (35 stages, two 12-wide layers) regression", () => {
  test("lays out with zero overlaps and a legible node size, in both orientations", async ({ page }) => {
    // Deliberately NOT asserting "every node fits inside the viewport"
    // anymore - that was the bug this task fixes. A wide graph clamped to
    // the legible zoom floor legitimately exceeds the viewport; a user
    // pans to see the rest, same as the tall/narrow shape above.
    const { dag, total } = buildWideDag();
    await mockPipelineApi(page, dag, total);

    await page.goto(`/pipelines/${PIPELINE_ID}?tab=canvas`);
    await expect(page.locator(".react-flow__node.react-flow__node-stage")).toHaveCount(35);
    await page.waitForTimeout(300);

    let boxes = await getNodeBoxes(page);
    assertNoOverlap(boxes);
    assertLegible(await getStageNodeBoxes(page));

    await page.getByRole("button", { name: "↓", exact: true }).click();
    await page.waitForTimeout(300);

    boxes = await getNodeBoxes(page);
    assertNoOverlap(boxes);
    assertLegible(await getStageNodeBoxes(page));
  });

  test("colors and animates a running migration's stages on the same 35-node layout", async ({ page }) => {
    const stageStates: Record<string, string> = {};
    for (let id = 1; id <= 16; id++) stageStates[String(id)] = "done";
    stageStates["17"] = "running";
    for (let id = 18; id <= 35; id++) stageStates[String(id)] = "idle";

    const { dag, total } = buildWideDag();
    await mockPipelineApi(page, dag, total, { runningMigration: true, stageStates });

    await page.goto(`/pipelines/${PIPELINE_ID}?tab=canvas`);
    await expect(page.locator(".react-flow__node.react-flow__node-stage")).toHaveCount(35);

    await expect(page.getByText("Migration running — view in Migrations →")).toBeVisible();

    const runningNode = nodeForStage(page, "Stage 17");
    await expect(runningNode.getByText(/Running — critiquing weakest candidates/)).toBeVisible();

    const doneNode = nodeForStage(page, "Stage 1");
    await expect(doneNode.getByRole("img", { name: "Stage done" })).toBeVisible();

    await expect(page.locator(".react-flow__edge.edge-beam")).not.toHaveCount(0);
    await expect(page.locator(".react-flow__edge.edge-passed")).not.toHaveCount(0);

    const boxes = await getNodeBoxes(page);
    assertNoOverlap(boxes);
    assertLegible(await getStageNodeBoxes(page));
  });
});
