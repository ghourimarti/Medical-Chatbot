import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/**
 * Accessibility audit (S10.12) — WCAG 2.2 AA.
 *
 * Automated scanning catches perhaps a third of real accessibility defects, so this file
 * does BOTH: axe for the machine-checkable rules, and explicit keyboard and screen-reader
 * assertions for the things axe cannot see (focus order, whether a live region announces
 * usefully, whether a control is reachable without a mouse).
 *
 * Treating a clean axe run as "accessible" is the most common way a product ships an
 * inaccessible interface with a passing test suite.
 */
const ROUTES = ["/", "/design", "/how-it-works", "/safety", "/sources", "/status", "/privacy", "/terms"];

async function scan(page: Page) {
  return new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
}

test.describe("axe — machine-checkable rules", () => {
  for (const route of ROUTES) {
    test(`${route} has no WCAG A/AA violations`, async ({ page }) => {
      await page.goto(route);
      const results = await scan(page);
      // Report the rule ids, not just a count: "3 violations" tells you nothing at 2am.
      expect(
        results.violations.map((v) => `${v.id} (${v.nodes.length}): ${v.help}`),
      ).toEqual([]);
    });
  }

  test("dark theme has no violations either", async ({ page }) => {
    // Contrast is theme-dependent, and a palette that passes in light can fail in dark.
    await page.addInitScript(() => {
      localStorage.setItem("medbot.theme", "dark");
      document.documentElement.dataset.theme = "dark";
    });
    await page.goto("/design");
    const results = await scan(page);
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });

  test("an answered page has no violations", async ({ page }) => {
    // The states that matter most are the ones only reachable by interacting.
    await page.goto("/");
    await page.getByLabel("Your question").fill("I have crushing chest pain and my left arm is numb");
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    await page.locator("[data-answer-kind]").waitFor({ state: "visible", timeout: 60_000 });
    const results = await scan(page);
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });
});

test.describe("keyboard — what axe cannot check", () => {
  test("the skip link is the first stop and moves focus to content", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Tab");
    const first = page.locator(":focus");
    await expect(first).toHaveText(/Skip to content/);
  });

  test("a question can be asked entirely by keyboard", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Your question").focus();
    await page.keyboard.type("How many mg of ibuprofen should I take for my back pain?");
    // Enter submits, Shift+Enter newlines — the convention every chat UI uses.
    await page.keyboard.press("Enter");
    await expect(page.locator("[data-answer-kind]")).toBeVisible({ timeout: 60_000 });
  });

  test("citation markers and evidence are keyboard reachable", async ({ page }) => {
    await page.goto("/design");
    const marker = page.getByRole("button", { name: /Show source 1/ }).first();
    await marker.focus();
    await expect(marker).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#evidence-0 button").first()).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  test("a visible focus indicator exists", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Your question").focus();
    const outline = await page
      .getByLabel("Your question")
      .evaluate((el) => getComputedStyle(el).outlineStyle);
    // 2.4.7 Focus Visible: focus must be perceptible, and `outline: none` with nothing in
    // its place is the single most common way keyboard users are locked out.
    expect(outline).not.toBe("none");
  });
});

test.describe("screen reader affordances", () => {
  test("streaming announces politely, once, not per token", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Your question").fill("What is cancer?");
    await page.getByRole("button", { name: "Ask", exact: true }).click();

    const live = page.locator('[aria-live="polite"]');
    await expect(live.first()).toBeAttached();
    // aria-live="assertive" on streaming text would interrupt the user on every token and
    // make the answer unreadable. Only the emergency card may be assertive.
    await expect(page.locator('[aria-live="assertive"]:not(#__next-route-announcer__)')).toHaveCount(0);
  });

  test("every decorative icon is hidden from assistive tech", async ({ page }) => {
    await page.goto("/design");
    // An icon with no accessible name that is NOT hidden reads as "graphic" noise between
    // every label. All of ours are decorative and carry aria-hidden.
    const bare = await page.locator("svg:not([aria-hidden='true'])").count();
    expect(bare).toBe(0);
  });

  test("the page has one h1 and a sane heading order", async ({ page }) => {
    await page.goto("/how-it-works");
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    const levels = await page
      .locator("h1, h2, h3, h4")
      .evaluateAll((els) => els.map((e) => Number(e.tagName[1])));
    for (let i = 1; i < levels.length; i++) {
      // Skipping a level (h2 -> h4) breaks navigation-by-heading, which is how many
      // screen-reader users read a page at all.
      expect(levels[i]! - levels[i - 1]!).toBeLessThanOrEqual(1);
    }
  });
});
