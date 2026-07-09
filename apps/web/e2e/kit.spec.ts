import { test, expect } from "@playwright/test";

test.describe("/dev/kit", () => {
  test("renders all sections and ParityBeam is visible", async ({ page }) => {
    await page.goto("/dev/kit");

    await expect(page.locator("h1")).toHaveText("Design kit");
    await expect(
      page.getByRole("heading", { name: "ParityBeam", exact: true })
    ).toBeVisible();
    await expect(page.locator('[role="meter"]').first()).toBeVisible();
  });

  test("drawer opens and closes", async ({ page }) => {
    await page.goto("/dev/kit");

    await page.click("text=Open stage drawer");
    await expect(page.locator("text=Stage detail")).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(page.locator("text=Stage detail")).not.toBeVisible();
  });

  test("drawer opens from the right side, not the bottom", async ({ page }) => {
    await page.goto("/dev/kit");

    await page.click("text=Open stage drawer");
    const panel = page.locator('[data-vaul-drawer-direction="right"]');
    await expect(panel).toBeVisible();

    const box = await panel.boundingBox();
    const viewport = page.viewportSize();
    expect(box).not.toBeNull();
    expect(viewport).not.toBeNull();
    // Right-anchored panel: its right edge sits at (or very near) the
    // viewport's right edge, and it spans the full viewport height —
    // a bottom-anchored panel would instead span near-full width.
    expect(box!.x + box!.width).toBeGreaterThan(viewport!.width - 5);
    expect(box!.height).toBeGreaterThan(viewport!.height * 0.5);
  });
});
