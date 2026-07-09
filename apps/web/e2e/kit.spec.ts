import { test, expect } from "@playwright/test";

test.describe("/dev/kit", () => {
  test("renders all sections and ParityBeam is visible", async ({ page }) => {
    await page.goto("/dev/kit");

    await expect(page.locator("h1")).toHaveText("Design kit");
    await expect(page.locator("text=ParityBeam")).toBeVisible();
    await expect(page.locator('[role="meter"]').first()).toBeVisible();
  });

  test("drawer opens and closes", async ({ page }) => {
    await page.goto("/dev/kit");

    await page.click("text=Open stage drawer");
    await expect(page.locator("text=Stage detail")).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(page.locator("text=Stage detail")).not.toBeVisible();
  });
});
