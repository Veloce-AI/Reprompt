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
  test("import a pipeline, walk the wizard, and confirm a Migration is created", async ({
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

    // Reachable from the pipeline canvas via "New migration" - go through
    // that link once to prove the wiring, then interact with the wizard.
    await page.goto(`/pipelines/${pipelineId}`);
    await page.getByRole("link", { name: "New migration" }).click();
    await expect(page.getByRole("heading", { name: "New migration" })).toBeVisible();

    // Step 1: target model. Continue is disabled until a default model is
    // picked; registry facts (cost / context / JSON mode) appear once one is.
    await expect(
      page.getByRole("button", { name: "Continue to budget & parity threshold" })
    ).toBeDisabled();

    await page.getByLabel("Default target model").selectOption("gpt-4o-mini");
    await expect(page.getByText(/Cost \/ 1M tokens:/).first()).toBeVisible();

    // Per-stage override: pick a different model for one stage.
    await expect(page.getByText("Classify ticket category")).toBeVisible();
    await page
      .getByLabel("Target model for Classify ticket category")
      .selectOption("claude-haiku-4-5");

    await page.getByRole("button", { name: "Continue to budget & parity threshold" }).click();

    // Step 2: budget + parity threshold.
    await page.getByLabel("Budget").fill("42");
    await page.getByLabel("Parity threshold").fill("90");
    await page.getByRole("button", { name: "Continue to review" }).click();

    // Step 3: confirm/review shows the full config before running.
    await expect(page.getByText("gpt-4o-mini").first()).toBeVisible();
    await expect(page.getByText(/claude-haiku-4-5/).first()).toBeVisible();
    await expect(page.getByText("$42.00").first()).toBeVisible();
    await expect(page.getByText("90%").first()).toBeVisible();

    await page.getByRole("button", { name: "Run migration" }).click();

    // Honest post-run state: a real Migration record was created (queued),
    // but the wizard is explicit that nothing actually runs yet.
    await expect(page.getByText(/Migration #\d+ created/)).toBeVisible();
    await expect(page.getByText("Pending")).toBeVisible();
    await expect(
      page.getByText(/optimizer that actually runs migrations hasn.t been built yet/)
    ).toBeVisible();

    // Confirm directly against the API that the Migration record is real,
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
    expect(migration.target_model_config.default).toBe("gpt-4o-mini");
    // The overridden stage's db id maps to "claude-haiku-4-5"; find it by value
    // rather than assuming a specific stage id.
    const overriddenModels = Object.values(migration.target_model_config.stages);
    expect(overriddenModels).toEqual(["claude-haiku-4-5"]);
  });
});
