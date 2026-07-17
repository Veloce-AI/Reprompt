import { test, expect, type Page } from "@playwright/test";

/**
 * Verifies the dagre-based canvas layout (see lib/canvas-layout.ts,
 * DEV_TRACKER.md's "Canvas: dagre-based auto layout") against the real
 * failure mode the product owner reported: a real, large pipeline (35
 * stages) going outside the viewport / overlapping under the old hand-rolled
 * grid/layered position math. Entirely network-mocked (no live API server,
 * no auth) — the router has no auth gate on `/pipelines/$id`
 * (router.tsx), and every fetch the workspace route makes is intercepted
 * below, so this only needs the Vite dev server (playwright.config.ts's
 * `webServer`) to be up, same as every other e2e spec here.
 *
 * A jsdom/Vitest unit test cannot stand in for this: DEV_TRACKER.md's
 * "Product owner report" section already documents a real case where a
 * layout bug was fully invisible to Vitest (jsdom doesn't run real CSS
 * layout/paint) but plainly visible in a screenshot - overlap and
 * out-of-viewport placement are exactly that class of bug.
 */

const PIPELINE_ID = 1;
const RUNNING_MIGRATION_ID = 99;

interface MockStage {
  id: number;
  name: string;
}

/** 35 stages across 6 layers, including two wide layers (12 nodes each) -
 * the shape DEV_TRACKER.md records as the owner's real pipeline (many
 * single/few-node layers) stress-tested further with genuinely wide layers,
 * since dagre must space an arbitrary-width rank correctly with no
 * special-casing (unlike the old "layered" preset's MAX_PER_LAYER_LINE
 * wrap). */
function buildMockDag() {
  const layerRanges: number[][] = [
    [1], // root
    [2, 3, 4],
    Array.from({ length: 12 }, (_, i) => i + 5), // 5..16 - wide layer
    Array.from({ length: 12 }, (_, i) => i + 17), // 17..28 - wide layer
    [29, 30, 31, 32, 33],
    [34, 35],
  ];

  const stages: Record<string, MockStage> = {};
  for (const layer of layerRanges) {
    for (const id of layer) {
      stages[String(id)] = { id, name: `Stage ${id}` };
    }
  }

  const edges: { from_stage_id: number; to_stage_id: number }[] = [];
  const connect = (from: number[], to: number[]) => {
    to.forEach((toId, i) => {
      edges.push({ from_stage_id: from[i % from.length], to_stage_id: toId });
    });
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
    pipeline_id: PIPELINE_ID,
    layers: layerRanges.map((stage_ids) => ({ stage_ids })),
    stages: dagStages,
    edges,
  };
}

const MOCK_DAG = buildMockDag();

async function mockPipelineApi(
  page: Page,
  options: { runningMigration?: boolean; stageStates?: Record<string, string> } = {}
) {
  await page.route("**/pipelines", (route) =>
    route.fulfill({
      json: [
        {
          id: PIPELINE_ID,
          name: "Big pipeline (35 stages)",
          stage_count: 35,
          models_used: ["gpt-4o-mini"],
          benchmark_query_count: 10,
        },
      ],
    })
  );

  await page.route(`**/pipelines/${PIPELINE_ID}/dag`, (route) => route.fulfill({ json: MOCK_DAG }));

  const migration = options.runningMigration
    ? {
        id: RUNNING_MIGRATION_ID,
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
        progress_total: 35,
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
    await page.route(`**/pipelines/${PIPELINE_ID}/migrations/${RUNNING_MIGRATION_ID}/status`, (route) =>
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

function boxInsideContainer(node: Box, container: Box, tolerance = 4): boolean {
  return (
    node.x >= container.x - tolerance &&
    node.y >= container.y - tolerance &&
    node.x + node.width <= container.x + container.width + tolerance &&
    node.y + node.height <= container.y + container.height + tolerance
  );
}

async function getNodeBoxes(page: Page): Promise<Box[]> {
  const nodes = page.locator(".react-flow__node");
  const count = await nodes.count();
  const boxes: Box[] = [];
  for (let i = 0; i < count; i++) {
    const box = await nodes.nth(i).boundingBox();
    expect(box, `node ${i} should have a bounding box`).not.toBeNull();
    if (box) boxes.push(box);
  }
  return boxes;
}

async function assertFitsAndNoOverlap(page: Page) {
  const container = await page.locator(".react-flow").boundingBox();
  expect(container).not.toBeNull();
  const boxes = await getNodeBoxes(page);
  expect(boxes).toHaveLength(35);

  for (const box of boxes) {
    expect(boxInsideContainer(box, container!)).toBe(true);
  }

  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      expect(boxesOverlap(boxes[i], boxes[j]), `nodes ${i} and ${j} should not overlap`).toBe(false);
    }
  }
}

test.describe("canvas dagre auto-layout — 35-stage pipeline", () => {
  test("fits every node on screen with zero overlaps, in both orientations", async ({ page }) => {
    await mockPipelineApi(page);

    await page.goto(`/pipelines/${PIPELINE_ID}?tab=canvas`);
    await expect(page.locator(".react-flow__node")).toHaveCount(35);

    // Horizontal is the default orientation.
    await assertFitsAndNoOverlap(page);

    // Switch to vertical - refit runs again (RefitOnChange in
    // pipeline-canvas.tsx), same guarantees must hold.
    await page.getByRole("button", { name: "↓", exact: true }).click();
    // Let the orientation state update, dagre recompute, and the
    // requestAnimationFrame-deferred fitView settle.
    await page.waitForTimeout(300);
    await assertFitsAndNoOverlap(page);
  });

  test("colors and animates a running migration's stages on the same 35-node layout", async ({
    page,
  }) => {
    const stageStates: Record<string, string> = {};
    for (let id = 1; id <= 16; id++) stageStates[String(id)] = "done";
    stageStates["17"] = "running";
    for (let id = 18; id <= 35; id++) stageStates[String(id)] = "idle";

    await mockPipelineApi(page, { runningMigration: true, stageStates });

    await page.goto(`/pipelines/${PIPELINE_ID}?tab=canvas`);
    await expect(page.locator(".react-flow__node")).toHaveCount(35);

    // The Canvas tab's live-migration pill (pipeline-workspace.tsx's
    // CanvasTabContent) shows once a running migration is found.
    await expect(page.getByText("Migration running — view in Migrations →")).toBeVisible();

    // Locate by the stage-node.tsx name element's `title` attribute (exact
    // match) rather than node text, since "Stage 1" is a substring of
    // "Stage 10".."Stage 19" and would otherwise match the wrong node.
    function nodeForStage(name: string) {
      return page.locator(".react-flow__node").filter({ has: page.locator(`p[title="${name}"]`) });
    }

    // The running node (17) shows its live sub-step label.
    const runningNode = nodeForStage("Stage 17");
    await expect(runningNode.getByText(/Running — critiquing weakest candidates/)).toBeVisible();

    // A finished node (Stage 1) shows the "Done" state dot, not a substep
    // line.
    const doneNode = nodeForStage("Stage 1");
    await expect(doneNode.getByRole("img", { name: "Stage done" })).toBeVisible();

    // Edges touching the running stage carry the beam-flow animation class;
    // edges between two finished stages settle into "passed".
    await expect(page.locator(".react-flow__edge.edge-beam")).not.toHaveCount(0);
    await expect(page.locator(".react-flow__edge.edge-passed")).not.toHaveCount(0);

    // Live coloring doesn't break the layout guarantee either.
    await assertFitsAndNoOverlap(page);
  });
});
