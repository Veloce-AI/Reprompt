import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Verifies the Canvas/Graph merge (see DEV_TRACKER.md's Canvas/Graph merge
 * entry): the former separate "Graph" workspace tab (model nodes + inline
 * per-stage inference-call drilldown) is now an "Analytics" mode of the same
 * Canvas tab's `<PipelineCanvas>`, alongside the pre-existing "Live" mode
 * (per-stage run-state coloring while a migration executes). One toolbar,
 * one layout engine, one legible zoom floor, for both modes.
 *
 * Entirely network-mocked (no live API server, no auth) — same pattern as
 * canvas-layout.spec.ts. A realistic-scale mock (32 stages, 4 distinct
 * models, some stages with trace/cost data and some without) so the
 * Analytics-mode assertions (model stage counts, richer stats, call
 * drilldown) exercise something closer to a real pipeline than a handful of
 * fixture stages would.
 */

const PIPELINE_ID = 1;
const MODELS = ["gpt-4o-mini", "gpt-4o", "claude-3-5-sonnet-20241022", "gemini-1.5-flash"];

interface BuiltDag {
  dag: {
    pipeline_id: number;
    layers: { stage_ids: number[] }[];
    stages: Record<string, Record<string, unknown>>;
    edges: { from_stage_id: number; to_stage_id: number }[];
  };
  total: number;
}

/** A wide, shallow diamond (~32 stages across 9 layers, up to 6 wide) —
 * unlike canvas-layout.spec.ts's deliberately pathological tall/narrow mock
 * (which already covers that legibility edge case thoroughly), this shape
 * is closer to a typical branchy real pipeline and — usefully for this
 * file's interaction tests (clicking specific nodes) — comfortably fits a
 * normal viewport after `fitView` without needing to pan first. Stages
 * cycle through 4 models and about two-thirds carry trace_count/
 * total_cost_usd data (a real pipeline mixes stages that have and haven't
 * been run yet). */
function buildRealisticDag(): BuiltDag {
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

  for (const width of [1, 2, 4, 6, 6, 6, 4, 2, 1]) addLayer(width);

  const stages: Record<string, Record<string, unknown>> = {};
  let idx = 0;
  for (const layer of layerIds) {
    for (const id of layer) {
      const hasTraces = idx % 3 !== 0; // ~2/3 of stages have real trace data
      stages[String(id)] = {
        id,
        name: `stage_${id}_extract_and_route`,
        model: MODELS[idx % MODELS.length],
        avg_tokens_in: hasTraces ? 110 + idx : null,
        avg_tokens_out: hasTraces ? 60 + idx : null,
        avg_latency_ms: hasTraces ? 400 + idx * 5 : null,
        trace_count: hasTraces ? 10 + (idx % 5) : 0,
        total_cost_usd: hasTraces ? Number((0.01 + idx * 0.0007).toFixed(4)) : null,
      };
      idx++;
    }
  }

  return {
    dag: { pipeline_id: PIPELINE_ID, layers: layerIds.map((stage_ids) => ({ stage_ids })), stages, edges },
    total: nextId - 1,
  };
}

interface MutableMigrationState {
  running: boolean;
}

async function mockPipelineApi(
  page: Page,
  built: BuiltDag,
  migrationState: MutableMigrationState
) {
  await page.route("**/pipelines", (route: Route) =>
    route.fulfill({
      json: [
        {
          id: PIPELINE_ID,
          name: "Realistic mock pipeline",
          stage_count: built.total,
          models_used: MODELS,
          benchmark_query_count: 20,
        },
      ],
    })
  );

  await page.route(`**/pipelines/${PIPELINE_ID}/dag`, (route: Route) => route.fulfill({ json: built.dag }));

  // Read `migrationState.running` fresh on every call - the whole point is
  // that a test can flip it mid-run and the Canvas tab's 5s poll picks the
  // change up on its own (no page reload), proving the auto-select rule
  // reacts to a migration actually starting/ending, not just to initial
  // mount state.
  const migration = {
    id: 99,
    pipeline_id: PIPELINE_ID,
    target_model_config: { models: [MODELS[0]] },
    budget: 10,
    parity_threshold: 0.9,
    status: "running",
    total_cost_usd: null,
    stopped_early: false,
    stop_reason: null,
    progress_stage_name: "stage_5_extract_and_route",
    progress_current: 5,
    progress_total: built.total,
    progress_substep: "critiquing",
    activity_log: [],
    completed_at: null,
    stage_states: Object.fromEntries(
      Object.keys(built.dag.stages).map((id, i) => [id, i < 5 ? "done" : i === 5 ? "running" : "idle"])
    ),
  };

  await page.route(`**/pipelines/${PIPELINE_ID}/migrations`, (route: Route) =>
    route.fulfill({ json: migrationState.running ? [migration] : [] })
  );
  await page.route(`**/pipelines/${PIPELINE_ID}/migrations/99/status`, (route: Route) =>
    route.fulfill({ json: migration })
  );

  // Inference-call records for the drilldown - two records per stage,
  // regardless of which stage_id is requested (keeps the mock simple; the
  // test only cares that expanding fetches once and renders, and that a
  // second expand doesn't re-fetch).
  let stageRecordsCalls = 0;
  await page.route(`**/pipelines/${PIPELINE_ID}/stage-records*`, (route: Route) => {
    stageRecordsCalls++;
    const url = new URL(route.request().url());
    const stageId = Number(url.searchParams.get("stage_id"));
    route.fulfill({
      json: {
        records: [
          {
            id: stageId * 100 + 1,
            stage_id: stageId,
            stage_name: `stage_${stageId}_extract_and_route`,
            trace_id: 1,
            input: { text: "hello" },
            rendered_prompt: "Extract entities from: hello",
            output: '{"entities": []}',
            tokens_in: 112,
            tokens_out: 34,
            latency_ms: 420,
            cost: 0.0021,
          },
          {
            id: stageId * 100 + 2,
            stage_id: stageId,
            stage_name: `stage_${stageId}_extract_and_route`,
            trace_id: 2,
            input: { text: "world" },
            rendered_prompt: "Extract entities from: world",
            output: '{"entities": ["world"]}',
            tokens_in: 118,
            tokens_out: 40,
            latency_ms: 455,
            cost: 0.0023,
          },
        ],
        next_cursor: null,
      },
    });
  });

  return { getStageRecordsCallCount: () => stageRecordsCalls };
}

function stageNode(page: Page, name: string) {
  return page
    .locator(".react-flow__node.react-flow__node-stage")
    .filter({ has: page.locator(`p[title="${name}"]`) });
}

function modeButton(page: Page, label: "Live" | "Analytics") {
  return page.getByRole("toolbar", { name: "Canvas layout" }).getByRole("button", { name: label, exact: true });
}

function modelNode(page: Page, model: string) {
  return page
    .locator(".react-flow__node.react-flow__node-model")
    .filter({ has: page.locator(`p[title="${model}"]`) });
}

test.describe("Canvas tab — Live/Analytics mode (Canvas/Graph merge)", () => {
  // Comfortably fits the wide/shallow diamond mock after fitView without
  // needing to pan first - this file's interaction tests click specific
  // named nodes, unlike canvas-layout.spec.ts's layout-only assertions.
  test.use({ viewport: { width: 1600, height: 1000 } });


  test("Analytics mode: model nodes render with correct stage counts, click pins/unpins highlight, richer stats show on stage cards", async ({
    page,
  }) => {
    const built = buildRealisticDag();
    await mockPipelineApi(page, built, { running: false });

    await page.goto(`/pipelines/${PIPELINE_ID}?tab=canvas`);
    await expect(page.locator(".react-flow__node.react-flow__node-stage")).toHaveCount(built.total);

    // No migration running - Analytics is the auto-selected default.
    await expect(modeButton(page, "Analytics")).toHaveAttribute("aria-pressed", "true");
    await expect(modeButton(page, "Live")).toHaveAttribute("aria-pressed", "false");

    // One model node per unique model, each with the right stage count.
    const expectedCounts = new Map<string, number>();
    for (const model of MODELS) {
      const count = Object.values(built.dag.stages).filter((s) => s.model === model).length;
      expectedCounts.set(model, count);
    }
    await expect(page.locator(".react-flow__node.react-flow__node-model")).toHaveCount(MODELS.length);
    for (const [model, count] of expectedCounts) {
      await expect(modelNode(page, model)).toContainText(`${count} stage`);
    }

    // Richer stats (trace count / total cost) show on a stage that has
    // trace data - not present at all in Live mode's compact stats line.
    const tracedStage = stageNode(page, "stage_2_extract_and_route"); // idx=1, hasTraces
    await expect(tracedStage).toContainText("trace");
    await expect(tracedStage).toContainText("$");
    await expect(tracedStage).toContainText("View inference calls");

    // A stage with zero traces says so and offers no expand affordance.
    const untracedStage = stageNode(page, "stage_1_extract_and_route"); // idx=0, !hasTraces
    await expect(untracedStage).toContainText("No traces yet");
    await expect(untracedStage).not.toContainText("View inference calls");

    // Click-to-highlight is a pin/unpin (click), not hover - clicking a
    // model node highlights every stage using that model with a border glow
    // (checked via the model node's own pressed-looking highlight class on
    // its inner card div - React Flow's own `.react-flow__node` wrapper
    // doesn't carry it, the component's own root div does - since the stage
    // cards' highlight is a border color change that isn't easily asserted
    // as text).
    // Matched as a whole class token (word boundaries), not a substring -
    // the unhighlighted state's own `hover:border-beam/50` class would
    // otherwise false-match a plain `/border-beam/` regex.
    const PINNED_BORDER = /(^|\s)border-beam(\s|$)/;
    const firstModelNode = page.locator(".react-flow__node.react-flow__node-model").first();
    const firstModelCard = firstModelNode.locator("> div").first();
    await firstModelNode.click();
    await expect(firstModelCard).toHaveClass(PINNED_BORDER);
    // Clicking again unpins.
    await firstModelNode.click();
    await expect(firstModelCard).not.toHaveClass(PINNED_BORDER);
  });

  test("Analytics mode: call nodes expand/collapse with real data, cached so re-expanding doesn't re-fetch", async ({
    page,
  }) => {
    const built = buildRealisticDag();
    const api = await mockPipelineApi(page, built, { running: false });

    await page.goto(`/pipelines/${PIPELINE_ID}?tab=canvas`);
    await expect(page.locator(".react-flow__node.react-flow__node-stage")).toHaveCount(built.total);

    // A middle-layer stage (id 17, one of the diamond's widest/most central
    // layers), not an edge-of-the-diamond one - expanding calls grows the
    // graph's overall bounding box a lot (call nodes fan out well below
    // their parent), and fitView's re-center in response can push a stage
    // near the diamond's own top/bottom edge far enough off-screen that a
    // later click on it (even `force: true`) lands on whatever real page
    // element now occupies that point instead - a genuine, if edge-case,
    // consequence of this project's own established "legible zoom floor +
    // pan" design (see DEV_TRACKER.md), not a bug to paper over with
    // retries. A structurally central node doesn't have this problem.
    const TRACED_STAGE = "stage_17_extract_and_route";
    const callNodes = page.locator(".react-flow__node.react-flow__node-call");
    await expect(callNodes).toHaveCount(0);

    async function toggle() {
      await stageNode(page, TRACED_STAGE).click({ force: true });
      await page.waitForTimeout(300);
    }

    await toggle();
    await expect(callNodes).toHaveCount(2);
    await expect(stageNode(page, TRACED_STAGE)).toContainText("Hide inference calls");
    expect(api.getStageRecordsCallCount()).toBe(1);

    // Collapse.
    await toggle();
    await expect(callNodes).toHaveCount(0);

    // Re-expand - cached, no second fetch.
    await toggle();
    await expect(callNodes).toHaveCount(2);
    expect(api.getStageRecordsCallCount()).toBe(1);

    // Switching to Live mode collapses the drilldown (deliberate - not
    // preserved across mode switches per the merge plan).
    await modeButton(page, "Live").click();
    await page.waitForTimeout(300);
    await expect(callNodes).toHaveCount(0);
    await expect(page.locator(".react-flow__node.react-flow__node-model")).toHaveCount(0);

    // Back to Analytics - re-expanding is still instant (cache survived the
    // mode round-trip, only the expanded *set* was cleared).
    await modeButton(page, "Analytics").click();
    await page.waitForTimeout(300);
    await toggle();
    await expect(callNodes).toHaveCount(2);
    expect(api.getStageRecordsCallCount()).toBe(1);
  });

  test("Live mode: stage-state coloring, substep label, beam edges, and minimap all work exactly as before, at the shared legible zoom floor", async ({
    page,
  }) => {
    const built = buildRealisticDag();
    await mockPipelineApi(page, built, { running: true });

    await page.goto(`/pipelines/${PIPELINE_ID}?tab=canvas`);
    await expect(page.locator(".react-flow__node.react-flow__node-stage")).toHaveCount(built.total);

    // A running migration auto-selects Live.
    await expect(modeButton(page, "Live")).toHaveAttribute("aria-pressed", "true");
    // No Analytics-only content while in Live mode.
    await expect(page.locator(".react-flow__node.react-flow__node-model")).toHaveCount(0);

    await expect(page.getByText("Migration running — view in Migrations →")).toBeVisible();

    const runningNode = stageNode(page, "stage_6_extract_and_route");
    await expect(runningNode.getByText(/Running — critiquing weakest candidates/)).toBeVisible();

    const doneNode = stageNode(page, "stage_1_extract_and_route");
    await expect(doneNode.getByRole("img", { name: "Stage done" })).toBeVisible();

    await expect(page.locator(".react-flow__edge.edge-beam")).not.toHaveCount(0);
    await expect(page.locator(".react-flow__edge.edge-passed")).not.toHaveCount(0);

    // Minimap present (toggle defaults on) and the single shared zoom floor
    // (0.5, not the former Graph tab's laxer 0.25) is enforced here too.
    await expect(page.locator(".react-flow__minimap")).toBeVisible();
    const style = await page.locator(".react-flow__viewport").getAttribute("style");
    const scale = Number(style?.match(/scale\(([\d.]+)\)/)?.[1]);
    expect(scale).toBeGreaterThanOrEqual(0.5 - 0.01);
  });

  test("mode switching: auto-select tracks a migration starting/ending, manual toggle overrides it for the session, and a reload re-evaluates fresh", async ({
    page,
  }) => {
    const built = buildRealisticDag();
    const migrationState: MutableMigrationState = { running: true };
    await mockPipelineApi(page, built, migrationState);

    await page.goto(`/pipelines/${PIPELINE_ID}?tab=canvas`);
    await expect(page.locator(".react-flow__node.react-flow__node-stage")).toHaveCount(built.total);
    await expect(modeButton(page, "Live")).toHaveAttribute("aria-pressed", "true");

    // Migration ends - the Canvas tab's 5s listMigrations poll should pick
    // this up and auto-switch to Analytics with no user interaction.
    migrationState.running = false;
    await expect(modeButton(page, "Analytics")).toHaveAttribute("aria-pressed", "true", { timeout: 7000 });

    // Migration starts again - auto-switches back to Live.
    migrationState.running = true;
    await expect(modeButton(page, "Live")).toHaveAttribute("aria-pressed", "true", { timeout: 7000 });

    // Manual override: user picks Analytics while a migration is running,
    // opposing the auto-select rule.
    await modeButton(page, "Analytics").click();
    await expect(modeButton(page, "Analytics")).toHaveAttribute("aria-pressed", "true");

    // The migration keeps running (auto-select would still say Live) - the
    // manual choice must hold through further poll ticks this session.
    await page.waitForTimeout(6000);
    await expect(modeButton(page, "Analytics")).toHaveAttribute("aria-pressed", "true");
    await expect(modeButton(page, "Live")).toHaveAttribute("aria-pressed", "false");

    // Reload re-evaluates fresh - migration is still running, so Live wins
    // again (the manual override does not survive a reload).
    await page.reload();
    await expect(page.locator(".react-flow__node.react-flow__node-stage")).toHaveCount(built.total);
    await expect(modeButton(page, "Live")).toHaveAttribute("aria-pressed", "true");
  });
});
