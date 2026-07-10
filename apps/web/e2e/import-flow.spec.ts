import { test, expect } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = path.resolve(
  __dirname,
  "../../../packages/core/tests/fixtures"
);

test.describe("pipeline import flow", () => {
  test("importing a fixture takes you from empty state through to the canvas", async ({
    page,
  }) => {
    await page.goto("/");

    // Empty state (assuming a clean DB - see README/CI notes: this test
    // expects to run against a freshly created database).
    await expect(
      page.getByRole("heading", { name: "Import your first pipeline" })
    ).toBeVisible();

    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(
      path.join(FIXTURES_DIR, "sequential_5stage.json")
    );

    // Step 2: validation report (success path) - stays here until the
    // user explicitly continues, so they actually get to read it.
    await expect(page.getByText(/validated - 5 stages/)).toBeVisible({
      timeout: 10_000,
    });
    await page.getByRole("button", { name: "Continue to DAG preview" }).click();

    // Step 3: DAG preview.
    await expect(page.getByText(/imported successfully/)).toBeVisible();
    await expect(page.getByText(/^Layer 0:/)).toBeVisible();
    await expect(page.getByText(/^Layer 4:/)).toBeVisible(); // 5-stage sequential = 5 layers, 0-4

    await page.getByRole("button", { name: "View pipeline canvas" }).click();

    // Screen 3: the canvas itself.
    await expect(
      page.getByRole("heading", { name: "Pipeline canvas" })
    ).toBeVisible();
    // React Flow renders nodes async after layout - wait for at least one
    // stage card (rendered via our StageNode, which always shows a model
    // badge) to appear.
    await expect(page.locator(".react-flow__node").first()).toBeVisible({
      timeout: 10_000,
    });
    const nodeCount = await page.locator(".react-flow__node").count();
    expect(nodeCount).toBe(5);

    // Back to pipelines: the table now shows the imported pipeline, not
    // the empty state.
    await page.getByRole("link", { name: "← Pipelines" }).click();
    await expect(page.getByRole("table")).toBeVisible();
    await expect(page.getByText("Support ticket response pipeline")).toBeVisible();
  });

  test("a malformed trace file shows a field-level validation error, not a crash", async ({
    page,
  }) => {
    await page.goto("/pipelines/import");

    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles({
      name: "broken.json",
      mimeType: "application/json",
      buffer: Buffer.from("{not valid json"),
    });

    await expect(
      page.getByText("Trace file failed validation")
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/not valid JSON/)).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Choose a different file" })
    ).toBeVisible();
  });
});
