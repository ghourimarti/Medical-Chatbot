import { expect, test, type Page } from "@playwright/test";

/**
 * App shell: sidebar, drawer, palette, pin, filter (F1/F3/F5).
 *
 * These assert BEHAVIOUR that a screenshot cannot: that the drawer returns focus, that a
 * pin survives a reload, that the filter is honest about matching titles only. The visual
 * result is covered by screenshots.spec.ts; duplicating it here would be slower and would
 * fail for reasons unrelated to the subject.
 */

function sidebar(page: Page) {
  return page.getByRole("navigation", { name: "Saved conversations" });
}

async function openSidebar(page: Page) {
  const opener = page.getByRole("button", { name: "Open navigation" });
  if (await opener.isVisible()) await opener.click();
  await expect(sidebar(page)).toBeVisible({ timeout: 30_000 });
}

test.describe("command palette", () => {
  test("opens with the keyboard, filters, and closes on Escape", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("ControlOrMeta+k");

    const palette = page.getByRole("dialog", { name: "Command palette" });
    await expect(palette).toBeVisible();

    // Typing narrows to the matching command rather than listing everything.
    await page.keyboard.type("theme");
    await expect(palette.getByRole("button", { name: /Toggle light \/ dark/ })).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(palette).toBeHidden();
  });

  test("returns focus to wherever it was opened from", async ({ page }) => {
    // The failure this guards is invisible to a mouse user and total for a keyboard one:
    // a dialog that closes without restoring focus drops you at the top of the document.
    await page.goto("/");
    const box = page.getByLabel("Your question");
    await box.focus();

    await page.keyboard.press("ControlOrMeta+k");
    await expect(page.getByRole("dialog", { name: "Command palette" })).toBeVisible();
    await page.keyboard.press("Escape");

    await expect(box).toBeFocused();
  });

  test("toggling the theme from the palette actually changes the document", async ({ page }) => {
    await page.goto("/");
    const before = await page.evaluate(() => document.documentElement.dataset.theme ?? "system");

    await page.keyboard.press("ControlOrMeta+k");
    await page.keyboard.type("theme");
    await page.keyboard.press("Enter");

    const after = await page.evaluate(() => document.documentElement.dataset.theme ?? "system");
    expect(after).not.toBe(before);
    expect(["light", "dark"]).toContain(after);
  });
});

test.describe("sidebar filter and pin @live", () => {
  test("the filter matches titles and says so when nothing does", async ({ page }) => {
    await page.goto("/");
    await openSidebar(page);

    const created = page.waitForResponse(
      (r) => r.url().includes("/api/v1/conversations") && r.request().method() === "POST",
    );
    await sidebar(page).getByRole("button", { name: "New chat" }).click();
    await created;
    await openSidebar(page);

    await sidebar(page).getByRole("button", { name: /^Rename/ }).first().click();
    const field = sidebar(page).getByLabel("Conversation title");
    await field.fill("Liver questions");
    await field.press("Enter");

    const filter = sidebar(page).getByLabel("Filter conversations by title");
    await filter.fill("liver");
    await expect(
      sidebar(page).getByRole("button", { name: "Liver questions", exact: true }),
    ).toBeVisible();

    // The empty state EXPLAINS the limitation instead of implying the thread is gone.
    await filter.fill("zzzz-no-such-thread");
    await expect(sidebar(page).getByText(/Titles are set by you/)).toBeVisible();
  });

  test("a pinned conversation survives a reload", async ({ page }) => {
    await page.goto("/");
    await openSidebar(page);

    const created = page.waitForResponse(
      (r) => r.url().includes("/api/v1/conversations") && r.request().method() === "POST",
    );
    await sidebar(page).getByRole("button", { name: "New chat" }).click();
    await created;
    await openSidebar(page);

    await sidebar(page).getByRole("button", { name: /^Pin/ }).first().click();
    await expect(sidebar(page).getByRole("heading", { name: "Pinned" })).toBeVisible();

    // Persistence is the whole point of the feature — per-browser today, and a `pinned`
    // column later. Either way a pin that evaporates on reload is not a pin.
    await page.reload();
    await openSidebar(page);
    await expect(sidebar(page).getByRole("heading", { name: "Pinned" })).toBeVisible();
  });
});
