import { expect, test, type Page } from "@playwright/test";

/**
 * Conversation sidebar (S21).
 *
 * These run ANONYMOUSLY on purpose. The API owns a conversation by user_id when signed in
 * and by the session cookie otherwise, so the whole feature is exercisable with no account
 * — which is both the D24 design (no signup wall in front of the core value) and what makes
 * it testable without Clerk credentials.
 */
function sidebar(page: Page) {
  return page.getByRole("navigation", { name: "Saved conversations" });
}

/**
 * Reveal the sidebar, whichever viewport this project runs at (F1).
 *
 * On desktop it is a permanent rail. On a phone it is a drawer behind "Open navigation" —
 * the shape every product in this category uses, because a 17rem rail on a 412px screen
 * leaves no room for the answer. So the sidebar is not "missing" on mobile; it is one tap
 * away, and this helper asserts that tap actually works rather than skipping the viewport.
 */
async function openSidebar(page: Page) {
  const opener = page.getByRole("button", { name: "Open navigation" });
  if (await opener.isVisible()) await opener.click();
  await expect(sidebar(page)).toBeVisible({ timeout: 30_000 });
}

// "New chat", not "New conversation": the control was renamed with the app shell (F1)
// to match what the rest of the category calls it. The accessible name follows the VISIBLE
// label deliberately — giving it an aria-label of "New conversation" while it reads "New
// chat" on screen would break WCAG 2.5.3 (Label in Name) to keep a selector stable.
async function newConversation(page: Page) {
  const created = page.waitForResponse(
    (r) => r.url().includes("/api/v1/conversations") && r.request().method() === "POST",
  );
  await sidebar(page).getByRole("button", { name: "New chat" }).click();
  await created;
  // NOTE: on a phone this CLOSES the drawer — you asked for a new thread, so the composer
  // is what you want to see, not the list you just left. Deliberately not reopened here:
  // a test that goes on to type a question needs the composer reachable, and only the
  // tests that assert on the LIST reopen it (they call openSidebar themselves).
}

test.describe("conversation sidebar @live", () => {
  test("is available without signing in", async ({ page }) => {
    await page.goto("/");
    await openSidebar(page);
    // No signup wall: the feature is usable before an account exists.
    await expect(sidebar(page).getByRole("button", { name: "New chat" })).toBeVisible();
  });

  test("creating a conversation adds it to the list", async ({ page }) => {
    await page.goto("/");
    await openSidebar(page);
    await expect(sidebar(page).getByText("No saved conversations yet")).toBeVisible();

    await newConversation(page);
    await openSidebar(page);
    await expect(
      sidebar(page).getByRole("button", { name: "Untitled conversation", exact: true }),
    ).toBeVisible();
  });

  test("a conversation can be renamed", async ({ page }) => {
    await page.goto("/");
    await openSidebar(page);
    await newConversation(page);
    await openSidebar(page);

    await sidebar(page).getByRole("button", { name: /^Rename/ }).first().click();
    const field = sidebar(page).getByLabel("Conversation title");
    await field.fill("Liver questions");
    await field.press("Enter");

    // EXACT, because the rename and delete controls carry the title in their aria-labels
    // ("Rename Liver questions"), so a loose match finds three buttons. That is the
    // accessibility layer doing its job — the locator has to say which control it means.
    await expect(
      sidebar(page).getByRole("button", { name: "Liver questions", exact: true }),
    ).toBeVisible();
  });

  test("deleting asks for confirmation first", async ({ page }) => {
    await page.goto("/");
    await openSidebar(page);
    await newConversation(page);
    await openSidebar(page);

    await sidebar(page).getByRole("button", { name: /^Delete/ }).first().click();
    // Destroying stored health questions must never be one click.
    await expect(sidebar(page).getByText(/Delete this conversation and every question/)).toBeVisible();

    await sidebar(page).getByRole("button", { name: "Cancel" }).click();
    await expect(sidebar(page).getByText(/Delete this conversation/)).toHaveCount(0);

    await sidebar(page).getByRole("button", { name: /^Delete/ }).first().click();
    await sidebar(page).getByRole("button", { name: "Delete", exact: true }).click();
    await expect(sidebar(page).getByText("No saved conversations yet")).toBeVisible();
  });

  test("an answer lands in the selected conversation", async ({ page }) => {
    await page.goto("/");
    await openSidebar(page);
    await newConversation(page);

    // The selected thread id rides along with the ask. It is caller-supplied and therefore
    // untrusted — the API verifies ownership before writing — so this asserts the wiring,
    // not the authorisation.
    const asked = page.waitForRequest(
      (r) => r.url().includes("/api/v1/query/stream") && r.method() === "POST",
    );
    await page.getByLabel("Your question").fill("How many mg of ibuprofen should I take?");
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    const request = await asked;

    const body = JSON.parse(request.postData() ?? "{}");
    expect(body.conversation_id, "the selected thread was not sent with the question").toBeTruthy();
    await expect(page.locator("[data-answer-kind]")).toBeVisible({ timeout: 60_000 });
  });

  test("anonymous threads say what signing in would do", async ({ page }) => {
    await page.goto("/");
    await openSidebar(page);
    await newConversation(page);
    await openSidebar(page);
    // Not a generic "Sign up!" prompt: it states the consequence for work already done.
    await expect(sidebar(page).getByText(/saved to this browser/)).toBeVisible();
  });
});

test.describe("accounts are optional", () => {
  test("no Clerk UI is rendered when accounts are not configured", async ({ page }) => {
    await page.goto("/");
    // The backend uses a DisabledVerifier when CLERK_JWKS_URL is empty. A sign-in button
    // against a backend that cannot verify tokens is a door with no room behind it.
    await expect(page.getByRole("button", { name: "Sign in" })).toHaveCount(0);
  });

  test("no Clerk script is loaded when accounts are not configured", async ({ page }) => {
    const clerkRequests: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("clerk")) clerkRequests.push(r.url());
    });
    await page.goto("/");
    await page.waitForTimeout(1500);
    expect(clerkRequests, "an unconfigured deployment paid for the auth SDK").toEqual([]);
  });
});
