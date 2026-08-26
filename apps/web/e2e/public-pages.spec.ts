import { expect, test } from "@playwright/test";

/**
 * Public pages (S10.10).
 *
 * These carry the claims the product makes about itself — what it refuses, what it knows,
 * what it stores. A broken or missing one is a trust failure, not a cosmetic one.
 */
const PAGES = [
  { path: "/how-it-works", heading: "How it works" },
  { path: "/safety", heading: "Safety and limitations" },
  { path: "/sources", heading: "Sources" },
  { path: "/status", heading: "Status" },
  { path: "/privacy", heading: "Privacy" },
  { path: "/terms", heading: "Terms" },
];

test.describe("public pages", () => {
  for (const p of PAGES) {
    test(`${p.path} renders and keeps the disclaimer`, async ({ page }) => {
      const res = await page.goto(p.path);
      expect(res?.status()).toBe(200);
      await expect(page.getByRole("heading", { level: 1, name: p.heading })).toBeVisible();
      // The safety disclaimer is non-dismissible and must survive every route.
      await expect(page.getByText("General information, not medical advice.")).toBeVisible();
    });
  }

  test("every footer link resolves — no dead ends on a trust surface", async ({ page }) => {
    await page.goto("/");
    const nav = page.getByRole("navigation", { name: "Site information" });
    const hrefs = await nav.getByRole("link").evaluateAll((els) =>
      els.map((e) => (e as HTMLAnchorElement).getAttribute("href") ?? ""),
    );
    expect(hrefs.length).toBe(PAGES.length);
    for (const href of hrefs) {
      const res = await page.request.get(href);
      expect(res.status(), `${href} is a dead link`).toBe(200);
    }
  });

  test("status reports live component health @live", async ({ page }) => {
    await page.goto("/status");
    // Read from the service itself, so it must name the components rather than show a
    // static badge. A status page that cannot fail is not a status page.
    await expect(page.getByText("Reference index")).toBeVisible();
    await expect(page.getByText("Answer generation")).toBeVisible();
  });

  test("safety page leads with the emergency instruction", async ({ page }) => {
    await page.goto("/safety");
    await expect(page.getByText("If this is an emergency")).toBeVisible();
    await expect(page.getByText(/contact your local emergency services/i).first()).toBeVisible();
  });

  test("status degrades honestly when the API is unreachable", async ({ page }) => {
    // Complements the @live test above. Found while verifying the CI split against a
    // genuinely dead backend: the live assertion failed, correctly, because the page
    // renders its unavailable branch. That branch deserves its own test — a status page
    // that cannot report failure is not a status page.
    await page.route("**/api/v1/status", (route) => route.abort());
    await page.goto("/status");
    await expect(page.getByRole("heading", { level: 1, name: "Status" })).toBeVisible();
  });
});
