import { test, expect } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = path.resolve(__dirname, "../../../packages/core/tests/fixtures");

// The API server this suite runs against is started manually against
// http://localhost:8000 (see docs/DEVELOPMENT.md) - hit it directly here to
// confirm the wizard actually persisted a Migration record, not just that
// the UI shows a success message.
const API_BASE_URL = "http://localhost:8000";

test.describe("new migration wizard", () => {
  test("import a pipeline, discover the wizard via the tab CTA, walk it (including an advanced per-stage override), and confirm the Migration record is real", async ({
    page,
    request,
  }) => {
    await page.goto("/pipelines/import");

    const fileInput = page.locator('input[type="file"]');
    const [importResponse] = await Promise.all([
      page.waitForResponse(
        (res) => res.url().includes("/pipelines/import") && res.request().method() === "POST"
      ),
      fileInput.setInputFiles(path.join(FIXTURES_DIR, "sequential_5stage.json")),
    ]);
    const importBody = await importResponse.json();
    const pipelineId = importBody.pipeline_id as number;
    expect(pipelineId).toBeGreaterThan(0);

    // Lands on the pipeline workspace's Canvas tab (the default) - with no
    // Migration yet for this pipeline, the "Migrations" tab renders as an
    // obvious "+ Start a migration" call-to-action rather than a plain tab
    // label (see pipeline-workspace.tsx and DEV_TRACKER.md's "Migration
    // wizard discoverability" note) - click that, not a plain tab label.
    await page.goto(`/pipelines/${pipelineId}`);
    await page.getByRole("button", { name: "+ Start a migration" }).click();
    await expect(page.getByText("Target models")).toBeVisible();

    // Step 1: target model. Continue is disabled until at least one model
    // is picked; registry facts (cost / context / JSON mode) appear once
    // one is checked.
    await expect(
      page.getByRole("button", { name: "Continue to budget & parity threshold" })
    ).toBeDisabled();

    await page.getByLabel("gpt-4o-mini").check();
    await expect(page.getByText(/per 1M tokens/).first()).toBeVisible();

    // Advanced: customize per stage (optional, collapsed by default) -
    // override just the first stage to use a different model than the
    // global selection.
    await page.getByRole("button", { name: "Advanced: customize per stage" }).click();
    await expect(page.getByText("Classify ticket category")).toBeVisible();
    await page.getByLabel("claude-haiku-4-5 for Classify ticket category").check();
    // A stage left untouched still just mirrors the global pick, and isn't
    // flagged as customized - only the one stage actually changed is.
    await expect(page.getByText("Customized")).toHaveCount(1);

    await page.getByRole("button", { name: "Continue to budget & parity threshold" }).click();

    // Step 2: budget + parity threshold.
    await page.getByLabel("Budget").fill("42");
    await page.getByLabel("Parity threshold").fill("90");
    await page.getByRole("button", { name: "Continue to review" }).click();

    // Step 3: confirm/review shows the full config before running,
    // including the per-stage override summary.
    await expect(page.getByText("gpt-4o-mini").first()).toBeVisible();
    await expect(page.getByText("Per-stage overrides")).toBeVisible();
    await expect(page.getByText(/Classify ticket category:/)).toBeVisible();
    await expect(page.getByText("$42.00").first()).toBeVisible();
    await expect(page.getByText("90%").first()).toBeVisible();

    await page.getByRole("button", { name: "Run migration" }).click();

    // A real Migration record was created (M3/M4's optimizer wiring means
    // it doesn't auto-run - the success screen offers an explicit "Start
    // migration" action instead).
    await expect(page.getByText(/Migration #\d+ created/)).toBeVisible();
    await expect(page.getByText("Pending")).toBeVisible();
    await expect(page.getByRole("button", { name: "Start migration" })).toBeVisible();

    // Confirm directly against the API that the Migration record is real
    // and carries both the global model list and the per-stage override,
    // not just a UI-only success message.
    const migrationsResponse = await request.get(
      `${API_BASE_URL}/pipelines/${pipelineId}/migrations`
    );
    expect(migrationsResponse.ok()).toBeTruthy();
    const migrations = await migrationsResponse.json();
    expect(migrations).toHaveLength(1);
    const migration = migrations[0];
    expect(migration.status).toBe("pending");
    expect(migration.budget).toBe(42);
    expect(migration.parity_threshold).toBe(0.9);
    expect(migration.target_model_config.models).toEqual(["gpt-4o-mini"]);

    // The overridden stage's db id maps to ["claude-haiku-4-5"]; find it by
    // value rather than assuming a specific stage id, and confirm no other
    // stage was included (only the one actually customized).
    const overrides = migration.target_model_config.stage_overrides;
    expect(Object.keys(overrides)).toHaveLength(1);
    expect(Object.values(overrides)).toEqual([["claude-haiku-4-5"]]);
  });

  test("skipping the advanced section entirely creates a Migration with no stage_overrides key at all", async ({
    page,
    request,
  }) => {
    await page.goto("/pipelines/import");
    const fileInput = page.locator('input[type="file"]');
    const [importResponse] = await Promise.all([
      page.waitForResponse(
        (res) => res.url().includes("/pipelines/import") && res.request().method() === "POST"
      ),
      fileInput.setInputFiles(path.join(FIXTURES_DIR, "sequential_5stage.json")),
    ]);
    const pipelineId = (await importResponse.json()).pipeline_id as number;

    await page.goto(`/pipelines/${pipelineId}`);
    await page.getByRole("button", { name: "+ Start a migration" }).click();
    await expect(page.getByText("Target models")).toBeVisible();

    await page.getByLabel("gpt-4o-mini").check();
    // Advanced section never opened - this is the common/simple path.
    await page.getByRole("button", { name: "Continue to budget & parity threshold" }).click();

    await page.getByLabel("Budget").fill("10");
    await page.getByRole("button", { name: "Continue to review" }).click();
    // No "Per-stage overrides" section when nothing was customized.
    await expect(page.getByText("Per-stage overrides")).not.toBeVisible();

    await page.getByRole("button", { name: "Run migration" }).click();
    await expect(page.getByText(/Migration #\d+ created/)).toBeVisible();

    const migrationsResponse = await request.get(
      `${API_BASE_URL}/pipelines/${pipelineId}/migrations`
    );
    const migrations = await migrationsResponse.json();
    const migration = migrations[migrations.length - 1];
    expect(migration.target_model_config).toEqual({ models: ["gpt-4o-mini"] });
  });
});
