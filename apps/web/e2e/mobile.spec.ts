import { expect, test } from "@playwright/test";

/**
 * Mobile (S10.12).
 *
 * Mobile-first is a requirement, not a nice-to-have: this is used on phones, at night, by
 * worried people. These run under the `mobile` project (Pixel 7) as well as desktop, so a
 * layout that only works at 1280px fails here.
 */
test.describe("mobile layout", () => {
  test("the page never scrolls sideways", async ({ page }) => {
    await page.goto("/");
    // Horizontal overflow is the classic mobile defect: a single wide element (a table, a
    // long unbroken string) drags the whole document sideways and makes reading painful.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test("an answered page never scrolls sideways either @live", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Your question").fill("What is cancer?");
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    await page.locator("[data-answer-kind]").waitFor({ state: "visible", timeout: 60_000 });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test("the design gallery table scrolls INSIDE its own container", async ({ page }) => {
    await page.goto("/design");
    // A wide table is legitimate; dragging the page sideways is not. It gets its own
    // overflow-x container so the body stays put.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test("primary controls meet the 24px minimum target size (WCAG 2.5.8)", async ({ page }) => {
    await page.goto("/");
    for (const name of ["Ask"]) {
      const box = await page.getByRole("button", { name, exact: true }).boundingBox();
      expect(box, `${name} has no box`).not.toBeNull();
      expect(box!.height).toBeGreaterThanOrEqual(24);
      expect(box!.width).toBeGreaterThanOrEqual(24);
    }
  });

  test("the emergency treatment is fully visible without horizontal scrolling @live", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByLabel("Your question").fill("I have crushing chest pain and my left arm is numb");
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    const alert = page.locator('[data-answer-kind="emergency"]');
    await expect(alert).toBeVisible({ timeout: 60_000 });
    const box = await alert.boundingBox();
    const width = page.viewportSize()!.width;
    expect(box!.width).toBeLessThanOrEqual(width);
  });
});
