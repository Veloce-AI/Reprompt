import { test, expect } from "@playwright/test";

// The API server this suite runs against is started manually (see
// docs/DEVELOPMENT.md) with REFRACT_DEV_MAGIC_LINKS left at its default
// (on) - there's no real email provider configured, so the API hands the
// magic link back directly in the /auth/request-link response, and this
// test reads it from there exactly like a user reading it off this page
// would (see login.tsx's dev-only fallback card).
const SESSION_TOKEN_STORAGE_KEY = "refract_session_token";

test.describe("magic-link auth", () => {
  test("request a link, follow it, and land on Pipelines home authenticated", async ({
    page,
  }) => {
    await page.goto("/login");

    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

    const email = `e2e-${Date.now()}@example.com`;
    await page.getByLabel("Email address").fill(email);
    await page.getByRole("button", { name: "Send magic link" }).click();

    await expect(page.getByText("Check your email for a link")).toBeVisible();
    await expect(page.getByText(/Dev-only fallback/)).toBeVisible();

    const magicLink = page.getByRole("link", { name: /\/auth\/verify\?token=/ });
    await expect(magicLink).toBeVisible();
    const href = await magicLink.getAttribute("href");
    expect(href).toBeTruthy();

    // No session token yet - this is the moment that should create one.
    const tokenBeforeVerify = await page.evaluate(
      (key) => localStorage.getItem(key),
      SESSION_TOKEN_STORAGE_KEY
    );
    expect(tokenBeforeVerify).toBeNull();

    // Follow the link exactly as a user clicking it from their inbox would.
    await page.goto(href!);

    // The verify route exchanges the token, stores the session, and
    // redirects straight to Pipelines home (screen 1).
    await expect(page.getByRole("heading", { name: "Pipelines" })).toBeVisible();

    const sessionToken = await page.evaluate(
      (key) => localStorage.getItem(key),
      SESSION_TOKEN_STORAGE_KEY
    );
    expect(sessionToken).toBeTruthy();
    expect(sessionToken).toContain(".");
  });

  test("visiting the verify link a second time is rejected (token already used)", async ({
    page,
  }) => {
    await page.goto("/login");
    const email = `e2e-reuse-${Date.now()}@example.com`;
    await page.getByLabel("Email address").fill(email);
    await page.getByRole("button", { name: "Send magic link" }).click();

    const magicLink = page.getByRole("link", { name: /\/auth\/verify\?token=/ });
    const href = await magicLink.getAttribute("href");

    await page.goto(href!);
    await expect(page.getByRole("heading", { name: "Pipelines" })).toBeVisible();

    // Second visit: the token was already marked used server-side.
    await page.goto(href!);
    await expect(page.getByText(/already been used|invalid or has expired/)).toBeVisible();
    await expect(page.getByRole("link", { name: "Back to sign in" })).toBeVisible();
  });
});
