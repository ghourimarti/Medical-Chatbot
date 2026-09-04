import { test, expect, type Page } from "@playwright/test";

/** Temporary verification of the three reported UI behaviours. Not part of the suite. */

function sidebar(page: Page) {
  return page.getByRole("navigation", { name: "Saved conversations" });
}
async function openSidebar(page: Page) {
  const opener = page.getByRole("button", { name: "Open navigation" });
  if (await opener.isVisible()) await opener.click();
  await expect(sidebar(page)).toBeVisible({ timeout: 30_000 });
}
async function askAndWait(page: Page, q: string) {
  await page.getByLabel("Your question").fill(q);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  // Wait for the answer text to land anywhere on the page (transcript or live card).
  await page.waitForFunction(
    () => !!document.querySelector("main")?.innerText.match(/\[1\]|\[2\]|reliable information/),
    undefined,
    { timeout: 120_000 },
  );
}

test("verify all three reported behaviours", async ({ page }) => {
  const R: string[] = [];

  // ---------- #2 : does the query box clear after the answer? ----------
  await page.goto("/chat");
  await askAndWait(page, "What is bronchitis?");
  const boxValue = await page.getByLabel("Your question").inputValue();
  R.push(`#2 composer cleared after answer : ${boxValue === "" ? "PASS" : `FAIL (still holds "${boxValue}")`}`);

  const urlAfterAsk = page.url();
  R.push(`   (url after asking: ${urlAfterAsk.replace(/^.*:5008/, "")})`);

  // ---------- #3 : is the open conversation highlighted in the sidebar? ----------
  await openSidebar(page);
  const current = await sidebar(page).locator('[aria-current="true"]').count();
  R.push(`#3 sidebar marks open convo    : ${current === 1 ? "PASS" : `FAIL (${current} rows marked)`}`);

  // ---------- #1 : does /chat start a NEW conversation? ----------
  await page.goto("/chat");
  await page.waitForTimeout(3000);
  const mainText = (await page.locator("main").innerText()).replace(/\s+/g, " ");
  const inherited = mainText.includes("What is bronchitis?");
  R.push(`#1 /chat starts a NEW convo    : ${inherited ? "FAIL (inherited the previous thread)" : "PASS"}`);
  R.push(`   (main begins: "${mainText.slice(0, 70)}")`);

  console.log("\n===== VERIFICATION =====\n" + R.join("\n") + "\n========================\n");
});
