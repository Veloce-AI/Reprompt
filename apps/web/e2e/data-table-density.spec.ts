import { test, expect, type Page } from "@playwright/test";

/**
 * Regression coverage for a real product-owner-reported bug: the Data tab's
 * table (data-table.tsx) rendered stage names, input JSON previews, and
 * rendered-prompt text visually smashed together within cells, illegible.
 *
 * Root cause: the "Stage" column's Badge had no width constraint or
 * truncation of its own, and its wrapping grid cell div had no
 * `overflow-hidden`/`min-w-0` either. CSS Grid items default to
 * `min-width: auto`, so a long, space-free stage name (e.g.
 * "extract_entities_and_classify_intent" — underscores aren't wrap points)
 * rendered at its full intrinsic width, overflowing the Stage column's grid
 * track directly into the Input column. Because the "outline" badge variant
 * has no background fill, the overflowing badge text painted right on top
 * of the Input cell's text instead of being clipped — exactly the
 * "overlapping/illegible" look in the screenshot. The other cells (Input,
 * Rendered prompt, Output) already had Tailwind's `truncate` applied
 * directly and were unaffected.
 *
 * jsdom-based unit tests (data-table.test.tsx) cannot catch this class of
 * bug — jsdom has no real layout engine, so CSS Grid track overflow simply
 * doesn't happen there (see saas-product-design skill's precedent: the DAG
 * flex-height bug that a passing jsdom suite missed). This spec drives a
 * real browser, same pattern as canvas-layout.spec.ts's overlap checks.
 */

const PIPELINE_ID = 1;

async function mockPipelineApi(page: Page) {
  await page.route("**/pipelines", (route) =>
    route.fulfill({
      json: [
        {
          id: PIPELINE_ID,
          name: "Support ticket triage",
          stage_count: 3,
          models_used: ["gpt-4o"],
          benchmark_query_count: 10,
        },
      ],
    })
  );

  await page.route(`**/pipelines/${PIPELINE_ID}/dag`, (route) =>
    route.fulfill({
      json: {
        pipeline_id: PIPELINE_ID,
        layers: [{ stage_ids: [10, 20, 30] }],
        stages: {
          "10": {
            id: 10,
            name: "extract_entities_and_classify_intent",
            model: "gpt-4o",
            avg_tokens_in: 120,
            avg_tokens_out: 80,
            avg_latency_ms: 450,
            trace_count: 10,
            total_cost_usd: 0.5,
          },
          "20": {
            id: 20,
            name: "summarize_customer_context_and_history",
            model: "gpt-4o",
            avg_tokens_in: 120,
            avg_tokens_out: 80,
            avg_latency_ms: 450,
            trace_count: 10,
            total_cost_usd: 0.5,
          },
          "30": {
            id: 30,
            name: "route_to_appropriate_support_queue",
            model: "gpt-4o",
            avg_tokens_in: 120,
            avg_tokens_out: 80,
            avg_latency_ms: 450,
            trace_count: 10,
            total_cost_usd: 0.5,
          },
        },
        edges: [],
      },
    })
  );

  await page.route(`**/pipelines/${PIPELINE_ID}/migrations`, (route) => route.fulfill({ json: [] }));

  const stageNames = [
    "extract_entities_and_classify_intent",
    "summarize_customer_context_and_history",
    "route_to_appropriate_support_queue",
  ];

  const longPrompt =
    'You are a support triage assistant. Given the following customer message, classify the intent, extract key entities (customer id, product area, urgency), and summarize the relevant account history for the next agent. Customer message: "Hi, I\'ve been trying to reset my password for the last hour and the reset link keeps expiring." Respond in structured JSON with fields: intent, entities, urgency, summary.';

  const records = Array.from({ length: 30 }, (_, i) => ({
    id: i + 1,
    stage_id: 10 + (i % 3) * 10,
    stage_name: stageNames[i % 3],
    trace_id: 1000 + i,
    input: {
      customer_message:
        "Hi, I've been trying to reset my password for the last hour and the reset link in the email keeps expiring before I can click it. I've tried on both Chrome and Safari, cleared my cache, and still nothing works.",
      customer_id: `cust_${1000 + i}`,
      account_tier: "enterprise",
      previous_tickets: 3,
    },
    rendered_prompt: longPrompt,
    output:
      '{"intent": "account_access", "entities": {"issue": "password_reset", "product_area": "auth"}, "urgency": "high", "summary": "Customer unable to complete password reset due to expiring links across multiple browsers."}',
    tokens_in: 145,
    tokens_out: 92,
    latency_ms: 512,
    cost: 0.0087,
  }));

  await page.route(`**/pipelines/${PIPELINE_ID}/stage-records*`, (route) =>
    route.fulfill({ json: { records, next_cursor: null } })
  );

  return { longPrompt };
}

/** Every direct child (cell) of a row must not visually extend past the
 * start of the next cell - the exact failure mode of the reported bug
 * (a cell's rendered content, not just its grid track box, bleeding into
 * its neighbor). Checks the cell's own content element (its first child,
 * where truncation classes actually live) rather than the outer grid-item
 * div, since the outer div's box always matches the grid track regardless
 * of overflowing content. */
async function assertNoRowCellOverlap(page: Page, rowLocator: ReturnType<Page["locator"]>) {
  const rows = await rowLocator.all();
  for (const row of rows) {
    const overlap = await row.evaluate((el) => {
      const cells = Array.from(el.children) as HTMLElement[];
      for (let i = 0; i < cells.length - 1; i++) {
        const contentEl = (cells[i].firstElementChild as HTMLElement) ?? cells[i];
        const contentRight = contentEl.getBoundingClientRect().right;
        const nextLeft = cells[i + 1].getBoundingClientRect().left;
        if (contentRight > nextLeft + 0.5) {
          return { index: i, contentRight, nextLeft, text: contentEl.textContent };
        }
      }
      return null;
    });
    expect(overlap, `row cell overlap: ${JSON.stringify(overlap)}`).toBeNull();
  }
}

test.describe("Data tab table — cell truncation (product owner overlap report)", () => {
  test("long stage names, input JSON, and rendered prompts truncate cleanly with no overlap between cells", async ({
    page,
  }) => {
    await mockPipelineApi(page);
    await page.goto(`/pipelines/${PIPELINE_ID}?tab=data`);

    const rows = page.locator('[data-testid="data-table-scroll"] > div > button');
    await expect(rows.first()).toBeVisible();

    await assertNoRowCellOverlap(page, rows);

    // The long, underscore-joined stage name (no natural wrap point) must be
    // visually clipped (CSS text-overflow: ellipsis truncates rendering,
    // not the DOM text node, so this checks scrollWidth > clientWidth -
    // proof the badge is actually narrower than its full content, not
    // rendered at full intrinsic width like the regression did).
    const badge = rows.first().locator("[class*='rounded-control']").first();
    const isTruncated = await badge.evaluate((el) => el.scrollWidth > el.clientWidth);
    expect(isTruncated).toBe(true);
  });

  test("row height stays consistent and content stays on one line across all visible rows", async ({ page }) => {
    await mockPipelineApi(page);
    await page.goto(`/pipelines/${PIPELINE_ID}?tab=data`);

    const rows = page.locator('[data-testid="data-table-scroll"] > div > button');
    await expect(rows.first()).toBeVisible();

    const heights = await rows.evaluateAll((els) => els.map((el) => el.getBoundingClientRect().height));
    const distinctHeights = new Set(heights.map((h) => Math.round(h)));
    expect(distinctHeights.size, `row heights should all match, got: ${[...distinctHeights]}`).toBe(1);
  });

  test("clicking a row still opens the drawer with the full untruncated content", async ({ page }) => {
    const { longPrompt } = await mockPipelineApi(page);
    await page.goto(`/pipelines/${PIPELINE_ID}?tab=data`);

    const rows = page.locator('[data-testid="data-table-scroll"] > div > button');
    await rows.first().click();

    await expect(
      page.getByRole("heading", { name: "extract_entities_and_classify_intent" })
    ).toBeVisible();
    const prompt = page.locator("pre", { hasText: "You are a support triage assistant" });
    await expect(prompt).toHaveText(longPrompt);
  });

  test("stays overlap-free at a narrow viewport width", async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 800 });
    await mockPipelineApi(page);
    await page.goto(`/pipelines/${PIPELINE_ID}?tab=data`);

    const rows = page.locator('[data-testid="data-table-scroll"] > div > button');
    await expect(rows.first()).toBeVisible();
    await assertNoRowCellOverlap(page, rows);
  });
});
