import { test, type Page } from "@playwright/test";

/**
 * Portfolio screenshots (S10.6b).
 *
 * Not a test — a build artifact. This frontend is the first thing a recruiter or client
 * sees, and capturing states reproducibly beats remembering to take them by hand. Run with:
 *   pnpm exec playwright test e2e/screenshots.spec.ts --project=chromium
 * Output: docs/screenshots/
 */
const OUT = "../../docs/screenshots";

async function setTheme(page: Page, theme: "light" | "dark") {
  await page.addInitScript((t) => {
    localStorage.setItem("medbot.theme", t);
    document.documentElement.dataset.theme = t;
  }, theme);
}

async function answer(page: Page, question: string) {
  await page.goto("/chat");
  await page.getByLabel("Your question").fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.locator("[data-answer-kind]").waitFor({ state: "visible", timeout: 60_000 });
  // Let the caret animation settle so successive runs produce identical images.
  await page.waitForTimeout(300);
}

for (const theme of ["light", "dark"] as const) {
  test(`screenshots - ${theme} @live`, async ({ page }) => {
    await setTheme(page, theme);

    await page.goto("/chat");
    await page.screenshot({ path: `${OUT}/${theme}-01-landing.png`, fullPage: true });

    await answer(page, "What is cancer?");
    await page.screenshot({ path: `${OUT}/${theme}-02-grounded.png`, fullPage: true });

    await answer(page, "How does CRISPR gene editing work?");
    await page.screenshot({ path: `${OUT}/${theme}-03-no-answer.png`, fullPage: true });

    await answer(page, "How many mg of ibuprofen should I take for my back pain?");
    await page.screenshot({ path: `${OUT}/${theme}-04-refused-dosage.png`, fullPage: true });

    await answer(page, "I have crushing chest pain and my left arm is numb");
    await page.screenshot({ path: `${OUT}/${theme}-05-emergency.png`, fullPage: true });

    await page.goto("/design");
    await page.screenshot({ path: `${OUT}/${theme}-06-design-system.png`, fullPage: true });
  });
}
