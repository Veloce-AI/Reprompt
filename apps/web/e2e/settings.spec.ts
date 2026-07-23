import { test, expect } from "@playwright/test";

// The API server this suite runs against is started manually against a
// throwaway SQLite DB (see docs/DEVELOPMENT.md) - same convention as the
// other specs in this directory.

test.describe("settings", () => {
  test("sign in via dev-mode magic link, add an API key, confirm only last-four shows, then delete it", async ({
    page,
  }) => {
    const email = `settings-e2e-${Date.now()}@example.com`;

    // Sign in via the dev-mode magic link flow (no real email provider is
    // configured in this environment - see reprompt_api/auth.py).
    await page.goto("/login");
    await page.getByLabel("Email address").fill(email);
    await page.getByRole("button", { name: "Send magic link" }).click();

    const devLink = page.getByRole("link", { name: /\/auth\/verify\?token=/ });
    await expect(devLink).toBeVisible();
    await devLink.click();

    // auth-verify.tsx redirects to "/pipelines" once the session token is stored.
    await expect(page).toHaveURL("/pipelines");

    await page.getByRole("link", { name: "Settings" }).click();
    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();

    // Workspace name loads (proves GET /settings/workspace works while
    // authenticated).
    await expect(page.getByLabel("Workspace name")).toHaveValue(/workspace/);

    // No keys yet.
    await expect(page.getByText("No API keys configured yet.")).toBeVisible();

    // Add a key for the default suggested provider (openai).
    const rawKey = "sk-e2e-test-key-a1b2c3";
    await page.getByLabel("API key").fill(rawKey);
    await page.getByRole("button", { name: "Add API key" }).click();

    // Appears in the list with only the last four characters visible - the
    // raw key never appears anywhere on the page after saving.
    await expect(page.getByRole("cell", { name: "openai", exact: true })).toBeVisible();
    await expect(page.getByText(`sk-…${rawKey.slice(-4)}`)).toBeVisible();
    await expect(page.getByText(rawKey)).toHaveCount(0);

    // The form cleared - the key input is empty again.
    await expect(page.getByLabel("API key")).toHaveValue("");

    // Delete it and confirm it's gone.
    await page.getByRole("button", { name: "Delete openai key" }).click();
    await expect(page.getByText("No API keys configured yet.")).toBeVisible();
    await expect(page.getByRole("cell", { name: "openai", exact: true })).toHaveCount(0);
  });
});
