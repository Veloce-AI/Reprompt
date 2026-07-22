import { test, expect, type Page } from "@playwright/test";

/**
 * Verifies the canvas MiniMap overview (see pipeline-canvas.tsx,
 * DEV_TRACKER.md's "Canvas: MiniMap overview" entry) — added so a large
 * (~50-stage) pipeline that now requires panning at the legible zoom floor
 * (see "Canvas: legible zoom floor + spacing picker") still has a way to
 * see the whole graph at once.
 *
 * This is deliberately an e2e spec, not a Vitest/jsdom unit test: the bug
 * this guards against (React Flow's <MiniMap> silently renders zero node
 * markers unless each node carries a `.measured`/`initialWidth`/
 * `initialHeight` size hint — this canvas is fully controlled, rebuilding
 * `nodes` via useMemo with no `onNodesChange` wired, so that hint never
 * lands without deliberately setting it) only reproduces against a real
 * ResizeObserver/SVG render, exactly the class of bug jsdom's fake layout
 * can't catch (same reasoning as canvas-layout.spec.ts). Entirely
 * network-mocked, no live API server.
 */

const PIPELINE_ID = 1;

function buildLinearDag(total: number) {
  const stages: Record<string, unknown> = {};
  const layers: { stage_ids: number[] }[] = [];
  const edges: { from_stage_id: number; to_stage_id: number }[] = [];
  let prev: number | null = null;
  for (let id = 1; id <= total; id++) {
    stages[String(id)] = {
      id,
      name: `Stage ${id} — classify_and_route`,
      model: "gpt-4o-mini",
      avg_tokens_in: 120,
      avg_tokens_out: 80,
      avg_latency_ms: 450,
    };
    layers.push({ stage_ids: [id] });
    if (prev) edges.push({ from_stage_id: prev, to_stage_id: id });
    prev = id;
  }
  return { pipeline_id: PIPELINE_ID, layers, stages, edges };
}

async function mockPipelineApi(
  page: Page,
  dag: ReturnType<typeof buildLinearDag>,
  total: number,
  stageStates: Record<string, string>
) {
  await page.route("**/pipelines", (route) =>
    route.fulfill({
      json: [
        {
          id: PIPELINE_ID,
          name: "MiniMap 50-stage pipeline",
          stage_count: total,
          models_used: ["gpt-4o-mini"],
          benchmark_query_count: 10,
        },
      ],
    })
  );
  await page.route(`**/pipelines/${PIPELINE_ID}/dag`, (route) => route.fulfill({ json: dag }));

  const migration = {
    id: 99,
    pipeline_id: PIPELINE_ID,
    target_model_config: { models: ["gpt-4o-mini"] },
    budget: 10,
    parity_threshold: 0.9,
    status: "running",
    total_cost_usd: null,
    stopped_early: false,
    stop_reason: null,
    progress_stage_name: "Stage 21",
    progress_current: 21,
    progress_total: total,
    progress_substep: "critiquing",
    activity_log: [],
    completed_at: null,
    stage_states: stageStates,
  };
  await page.route(`**/pipelines/${PIPELINE_ID}/migrations`, (route) =>
    route.fulfill({ json: [migration] })
  );
  await page.route(`**/pipelines/${PIPELINE_ID}/migrations/99/status`, (route) =>
    route.fulfill({ json: migration })
  );
}

test.describe("Canvas MiniMap overview", () => {
  test("renders one marker per stage, colored by live run state, on a 50-stage pipeline", async ({
    page,
  }) => {
    const total = 50;
    const dag = buildLinearDag(total);
    const stageStates: Record<string, string> = {};
    for (let i = 1; i <= total; i++) {
      if (i <= 20) stageStates[String(i)] = "done";
      else if (i === 21) stageStates[String(i)] = "running";
      else if (i === 35) stageStates[String(i)] = "failed";
      else stageStates[String(i)] = "idle";
    }
    await mockPipelineApi(page, dag, total, stageStates);

    await page.goto(`/pipelines/${PIPELINE_ID}?tab=canvas`);
    await page.waitForFunction(
      (n) => document.querySelectorAll(".react-flow__node").length === n,
      total
    );

    const minimap = page.locator(".react-flow__minimap");
    await expect(minimap).toBeVisible();

    // The regression this guards: React Flow's <MiniMap> silently renders
    // zero `.react-flow__minimap-node` markers unless each node carries a
    // measured-or-hinted size - assert the real count, not just "some".
    const markers = page.locator(".react-flow__minimap-node");
    await expect(markers).toHaveCount(total);

    // stageStates coloring reached the minimap too (not just the main
    // canvas nodes) - exact counts per DEV_TRACKER's state->color mapping
    // (idle/running/done/failed -> --line/--beam/--parity-pass/--parity-fail).
    const fillCounts = await page.evaluate(() => {
      const counts: Record<string, number> = {};
      document.querySelectorAll(".react-flow__minimap-node").forEach((el) => {
        const fill = getComputedStyle(el).fill;
        counts[fill] = (counts[fill] ?? 0) + 1;
      });
      return counts;
    });
    expect(fillCounts["rgb(14, 159, 110)"]).toBe(20); // --parity-pass, "done"
    expect(fillCounts["rgb(76, 95, 232)"]).toBe(1); // --beam, "running"
    expect(fillCounts["rgb(220, 38, 38)"]).toBe(1); // --parity-fail, "failed"
    expect(fillCounts["rgb(227, 232, 240)"]).toBe(28); // --line, "idle"

    // Small corner overview, not a large fixture competing with the zoom
    // controls (bottom-left) or layout toolbar (top-right). Sized
    // adaptively (computeMinimapSize in pipeline-canvas.tsx) rather than a
    // fixed box — a 50-stage LINEAR chain in the default horizontal
    // orientation is wide/shallow (one node's height, ~50 nodes' worth of
    // width), so it's expected to hit the width cap while height stays
    // near the floor, not the old hardcoded "always small" assumption a
    // fixed-box minimap made.
    const svgBox = await page.locator(".react-flow__minimap-svg").boundingBox();
    expect(svgBox?.width).toBeLessThanOrEqual(300);
    expect(svgBox?.height).toBeLessThanOrEqual(170);
    expect(svgBox?.height).toBeGreaterThanOrEqual(60);
  });

  test("the Map toggle hides and re-shows the minimap without affecting the canvas", async ({
    page,
  }) => {
    const total = 6;
    const dag = buildLinearDag(total);
    await mockPipelineApi(page, dag, total, {});

    await page.goto(`/pipelines/${PIPELINE_ID}?tab=canvas`);
    await page.waitForFunction(
      (n) => document.querySelectorAll(".react-flow__node").length === n,
      total
    );

    const minimap = page.locator(".react-flow__minimap");
    await expect(minimap).toBeVisible();

    const toggle = page.getByRole("button", { name: "Map", exact: true });
    await toggle.click();
    await expect(minimap).toHaveCount(0);
    await expect(page.locator(".react-flow__node")).toHaveCount(total);

    await toggle.click();
    await expect(minimap).toBeVisible();
  });
});
