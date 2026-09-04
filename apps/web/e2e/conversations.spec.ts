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
    await page.goto("/chat");
    await openSidebar(page);
    // No signup wall: the feature is usable before an account exists.
    await expect(sidebar(page).getByRole("button", { name: "New chat" })).toBeVisible();
  });

  test("creating a conversation adds it to the list", async ({ page }) => {
    await page.goto("/chat");
    await openSidebar(page);
    await expect(sidebar(page).getByText("No saved conversations yet")).toBeVisible();

    await newConversation(page);
    await openSidebar(page);
    await expect(
      sidebar(page).getByRole("button", { name: "Untitled conversation", exact: true }),
    ).toBeVisible();
  });

  test("a conversation can be renamed", async ({ page }) => {
    await page.goto("/chat");
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
    await page.goto("/chat");
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
    await page.goto("/chat");
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
    await page.goto("/chat");
    await openSidebar(page);
    await newConversation(page);
    await openSidebar(page);
    // Not a generic "Sign up!" prompt: it states the consequence for work already done.
    await expect(sidebar(page).getByText(/saved to this browser/)).toBeVisible();
  });
});

test.describe("accounts are optional", () => {
  /**
   * These assert the UNCONFIGURED path, so they are meaningless once a key exists — and
   * worse than meaningless: they would fail on a correctly configured deployment and read
   * as a regression.
   *
   * Detected from the PAGE rather than from process.env, because the thing under test is
   * what the browser receives. The key is inlined into the client bundle at build time, so
   * the test runner's own environment says nothing about what the server actually served.
   */
  test.beforeEach(async ({ page }) => {
    // networkidle, NOT load: Clerk injects its script asynchronously, so checking straight
    // after goto reports "unconfigured" on a deployment that is configured — the same race
    // that made the request-watching test below flaky in full-suite runs while passing in
    // isolation.
    await page.goto("/", { waitUntil: "networkidle" });
    const configured = await page.evaluate(
      () =>
        !!document.querySelector('script[src*="clerk"]') ||
        !!(window as unknown as { Clerk?: unknown }).Clerk,
    );
    test.skip(configured, "accounts ARE configured here; this covers the opposite case");
  });

  test("no Clerk UI is rendered when accounts are not configured", async ({ page }) => {
    await page.goto("/chat");
    // The backend uses a DisabledVerifier when CLERK_JWKS_URL is empty. A sign-in button
    // against a backend that cannot verify tokens is a door with no room behind it.
    await expect(page.getByRole("button", { name: "Sign in" })).toHaveCount(0);
  });

  test("no Clerk script is loaded when accounts are not configured", async ({ page }) => {
    const clerkRequests: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("clerk")) clerkRequests.push(r.url());
    });
    await page.goto("/chat");
    await page.waitForTimeout(1500);
    expect(clerkRequests, "an unconfigured deployment paid for the auth SDK").toEqual([]);
  });
});

test.describe("thread isolation @live", () => {
  test("a new conversation does NOT inherit the previous one's turns", async ({ page }) => {
    // The reported bug: "the chat begins in the same window where we started previously".
    // The transcript was reloaded from /session/history — which spans EVERY thread — after
    // each answer, so a brand-new conversation filled with turns from the old one.
    await page.goto("/chat");
    await openSidebar(page);

    // Thread A: ask something distinctive.
    await newConversation(page);
    await page.getByLabel("Your question").fill("What is cirrhosis?");
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    await page.locator("[data-answer-kind]").waitFor({ timeout: 90_000 });

    // Thread B: brand new, and it must stay ISOLATED once used.
    await openSidebar(page);
    await newConversation(page);

    // ASKING IN B IS THE STEP THAT MATTERS. Merely creating B loads its (empty) messages,
    // so a test that stopped here would pass against the broken build too. The corruption
    // happened on the reload AFTER an answer, which is when the session-wide fetch ran.
    //
    // Let the reset settle BEFORE typing. Creating a thread resets the surface, which
    // swaps the idle and answered branches — and because the composer lives in both, React
    // remounts it and discards whatever had been typed. Filling mid-transition loses the
    // text and leaves Ask permanently disabled.
    //
    // (That remount is a real, if narrow, UX flaw: type immediately after "New chat" and
    // your first characters can vanish. Fixing it properly means hoisting the composer out
    // of the branch so it renders once — noted, not done here.)
    await page.waitForLoadState("networkidle");
    const askButton = page.getByRole("button", { name: "Ask", exact: true });
    await expect(askButton).toBeVisible();
    await page.getByLabel("Your question").fill("What is asthma?");
    await expect(askButton).toBeEnabled({ timeout: 15_000 });
    await askButton.click();
    await page.locator("[data-answer-kind]").waitFor({ timeout: 90_000 });
    await page.waitForTimeout(2000);

    const transcript = page.getByRole("region", { name: "Earlier in this session" });
    await expect(
      transcript.getByText(/cirrhosis/i),
      "thread B inherited thread A's turns",
    ).toHaveCount(0);
  });
});

test.describe("composer and route hygiene @live", () => {
  test("the question box CLEARS after asking", async ({ page }) => {
    // Reported: "each time after the response the same query appears again in the query box,
    // and for the next query I have to remove it with backspace". The box held the submitted
    // text, so the composer looked pre-filled with something already answered.
    await page.goto("/chat");
    const box = page.getByLabel("Your question");
    await box.fill("What is fever?");
    await page.getByRole("button", { name: "Ask", exact: true }).click();

    // Asserted on the TRANSCRIPT, not on [data-answer-kind]: grounded answers currently
    // render without the answer-card wrapper, so that attribute is absent for them.
    await expect(page.getByText("What is fever?").first()).toBeVisible({ timeout: 90_000 });
    await expect(box, "the composer kept the question after sending").toHaveValue("");
  });
});
