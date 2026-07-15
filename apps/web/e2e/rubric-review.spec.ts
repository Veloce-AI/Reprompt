import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = path.resolve(__dirname, "../../../packages/core/tests/fixtures");
const API_DIR = path.resolve(__dirname, "../../api");

// The API server this suite runs against is started manually (see
// docs/DEVELOPMENT.md / the task runbook) with
// DATABASE_URL="sqlite:///./e2e_test.db" from apps/api - point the seed
// helper at the exact same file so it's writing into the DB the running
// server actually reads from.
const E2E_DATABASE_URL = "sqlite:///./e2e_test.db";

/**
 * Seeds rubrics for `pipelineId` using the real dev/test seed helper
 * (reprompt_api.seed_rubrics - see that module for what it writes and why:
 * there's no rubric GENERATOR yet, this is hand-authored fixture data shaped
 * like the real deterministic-check types). Run out-of-band as a subprocess
 * rather than through an HTTP endpoint, since seeding isn't a product
 * feature - it's a test fixture, same spirit as a pytest fixture but
 * reachable from Playwright's Node process.
 */
function seedRubricsForPipeline(pipelineId: number) {
  execFileSync(
    "uv",
    ["run", "python", "-m", "reprompt_api.seed_rubrics", "--pipeline-id", String(pipelineId)],
    {
      cwd: API_DIR,
      env: { ...process.env, DATABASE_URL: E2E_DATABASE_URL },
      stdio: "inherit",
      shell: true,
    }
  );
}

test.describe("rubric review", () => {
  test("import a pipeline, seed rubrics, review, edit, and approve", async ({ page }) => {
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

    seedRubricsForPipeline(pipelineId);

    // Reachable from the pipeline canvas via "Review rubrics" - go through
    // that link once to prove the wiring, then navigate directly for the
    // rest of the test.
    await page.goto(`/pipelines/${pipelineId}`);
    await page.getByRole("link", { name: "Review rubrics" }).click();
    await expect(page.getByRole("heading", { name: "Rubric review" })).toBeVisible();

    // Grouped, plain-English checklist - never raw check types or "json
    // schema" jargon.
    await expect(page.getByText("Format checks").first()).toBeVisible();
    await expect(page.getByText("Content criteria").first()).toBeVisible();
    await expect(page.getByText("Downstream contract").first()).toBeVisible();
    await expect(page.getByText("Must include: currency, revenue").first()).toBeVisible();
    await expect(page.getByText(/Length must be between 20 and 800 characters/).first()).toBeVisible();
    await expect(page.getByText("Next stage reads: currency").first()).toBeVisible();
    await expect(page.getByText("required_keys")).toHaveCount(0);

    // All 5 stages from the fixture got a seeded rubric.
    await expect(page.getByText("Classify ticket category")).toBeVisible();
    await expect(page.getByText("Finalize and format response")).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve", exact: true })).toHaveCount(5);

    // Edit: add a new downstream contract field on the first stage card.
    const firstCard = page
      .locator("section", { hasText: "Downstream contract" })
      .first();
    await firstCard
      .getByLabel("Add a downstream contract field")
      .fill("ticket_id");
    await firstCard.getByRole("button", { name: "Add criterion" }).click();
    await expect(page.getByText("Next stage reads: ticket_id")).toBeVisible();

    // Delete: remove the seeded length_bounds check from the first stage.
    // All 5 seeded stages share this same check text, so assert the count
    // drops from 5 to 4 rather than checking global absence.
    await expect(page.getByText(/Length must be between 20 and 800 characters/)).toHaveCount(5);
    const lengthCheckRow = page
      .locator("li", { hasText: /Length must be between 20 and 800 characters/ })
      .first();
    await lengthCheckRow.getByRole("button", { name: "Delete" }).click();
    await expect(page.getByText(/Length must be between 20 and 800 characters/)).toHaveCount(4);

    // Approve one stage, then approve the rest via "Approve all".
    await page.getByRole("button", { name: "Approve", exact: true }).first().click();
    await expect(page.getByText("Approved").first()).toBeVisible();

    await page.getByRole("button", { name: "Approve all" }).click();
    await expect(page.getByRole("button", { name: "All stages approved" })).toBeVisible();
    await expect(page.getByRole("button", { name: "All stages approved" })).toBeDisabled();
    await expect(page.getByText("Needs review")).toHaveCount(0);
  });
});
