import { expect, test, type Page } from "@playwright/test";

/**
 * S10.6b — the four answer kinds, verified IN A BROWSER against the real backend.
 *
 * Everything before this step was verified at the HTTP level. That proves the contract but
 * not the product: a client can receive a correct `refused` event and still render it as a
 * grounded answer. These tests assert what a user actually sees.
 *
 * Requires the stack up:  make app && make seed LIMIT=400 && make web-preview
 */

async function ask(page: Page, question: string) {
  await page.goto("/");
  await page.getByLabel("Your question").fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
}

/**
 * The answer surface has settled when the answer article exists.
 *
 * The first version of this waited for the streaming text to disappear and hit a strict
 * mode violation: the sr-only aria-live region duplicates that copy for screen readers, so
 * the locator matched two elements. That is the accessibility layer working correctly, and
 * the lesson is that prose is a poor test hook. `data-answer-kind` carries the RESOLVED
 * treatment, so tests assert the decision rather than the wording.
 */
/**
 * Our own urgent card, NOT `getByRole("alert")`.
 *
 * Next.js injects <div id="__next-route-announcer__" role="alert"> into every page for
 * route announcements, so a bare role query always matches at least one element and an
 * assertion of "no alert" can never pass. Scoping to our own hook keeps the test about
 * the product rather than the framework.
 */
function urgentCard(page: Page) {
  return page.locator('[data-answer-kind="emergency"]');
}

/** The answer card itself. Assertions MUST be scoped to it: since S10.8 the session
 *  transcript repeats the answer text, so a page-wide getByText matches twice and trips
 *  strict mode. That is the transcript working correctly — the test was too loose. */
function card(page: Page) {
  return page.locator("[data-answer-kind]");
}

/**
 * Arms a waiter for the history response that actually CONTAINS messages.
 *
 * Must be called BEFORE asking. Two earlier attempts failed for instructive reasons:
 * a fixed 20s timeout raced the fetch (passing in isolation, failing in a full run), and
 * arming the waiter after the answer settled missed a response that had already arrived.
 * Matching on the body rather than the URL also skips the empty mount fetch, which now
 * returns session_id: null because a read no longer mints a session.
 */
function armTranscript(page: Page) {
  return page.waitForResponse(
    async (r) => {
      if (!r.url().includes("session/history") || r.status() !== 200) return false;
      try {
        return ((await r.json()) as { messages: unknown[] }).messages.length > 0;
      } catch {
        return false;
      }
    },
    { timeout: 40_000 },
  );
}

function transcriptPanel(page: Page) {
  return page.getByRole("region", { name: "Earlier in this session" });
}

async function settled(page: Page): Promise<string> {
  const article = page.locator("[data-answer-kind]");
  await expect(article).toBeVisible({ timeout: 60_000 });
  return (await article.getAttribute("data-answer-kind")) ?? "";
}

test.describe("answer kinds", () => {
  test("grounded: cites its sources and uses the grounded treatment", async ({ page }) => {
    await ask(page, "What is cancer?");
    expect(await settled(page)).toBe("grounded");

    await expect(card(page).getByText("Answer from the reference corpus")).toBeVisible();
    // The invariant the API enforces server-side must survive rendering: a grounded answer
    // ALWAYS shows at least one citation. Rendering an uncited claim as sourced is the
    // single worst failure this UI could have.
    await expect(card(page).getByText(/Gale Encyclopedia/).first()).toBeVisible();
    await expect(card(page).locator(".answer-prose")).not.toBeEmpty();
  });

  test("no_answer: abstains WITHOUT a warning treatment", async ({ page }) => {
    await ask(page, "How does CRISPR gene editing work?");
    expect(await settled(page)).toBe("no_answer");

    await expect(card(page).getByText("Not in the reference material")).toBeVisible();
    await expect(card(page).getByText(/don't have reliable information/)).toBeVisible();
    // It must NOT be dressed as an emergency or an error. Rendering candour as a
    // malfunction teaches users to distrust the abstentions that protect them.
    await expect(urgentCard(page)).toHaveCount(0);
    await expect(page.getByText("Seek emergency care now")).toHaveCount(0);
  });

  test("refused/dosage: reads as care, not as an emergency", async ({ page }) => {
    await ask(page, "How many mg of ibuprofen should I take for my back pain?");
    // The RESOLVED treatment must be the routine one, never the urgent one.
    expect(await settled(page)).toBe("refused");

    await expect(card(page).getByText("This needs a clinician")).toBeVisible();
    await expect(card(page).getByText(/can't provide dosage information/)).toBeVisible();
    // A routine refusal must not borrow the emergency treatment: red is reserved, and
    // spending it here is how it stops meaning "act now".
    await expect(urgentCard(page)).toHaveCount(0);
    // A refusal cites nothing (enforced server-side); the UI must not invent evidence.
    await expect(card(page).getByText(/Gale Encyclopedia/)).toHaveCount(0);
  });

  test("refused/emergency: unmissable, announced, and action-first", async ({ page }) => {
    await ask(page, "I have crushing chest pain and my left arm is numb");
    expect(await settled(page)).toBe("emergency");

    const alert = urgentCard(page);
    await expect(alert).toBeVisible();
    // Announced immediately by assistive tech — justified here and almost nowhere else.
    await expect(alert).toHaveAttribute("role", "alert");
    await expect(alert).toContainText("This may be a medical emergency");
    // Action must precede explanation: someone with chest pain should not have to read a
    // paragraph to find out what to do.
    await expect(alert).toContainText(/contact your local emergency services/i);
    // No invented phone number: emergency numbers differ by country and a wrong one here
    // is a catastrophic failure.
    await expect(alert).not.toContainText(/\b911\b|\b999\b|\b112\b/);
  });

  test("the four kinds are visually DISTINCT, not one rendered as another", async ({ page }) => {
    // Colour is verified in the design gallery; here we assert the LABELS differ, because
    // colour never carries meaning alone (WCAG 1.4.1) and the label is what a screen
    // reader and a greyscale display both receive.
    await page.goto("/design");
    for (const label of [
      "Answer from the reference corpus",
      "Not in the reference material",
      "This needs a clinician",
      "Seek emergency care now",
      "Limited service",
    ]) {
      await expect(page.getByText(label).first()).toBeVisible();
    }
  });
});

test.describe("streaming contract", () => {
  test("evidence is painted before the answer text", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Your question").fill("How is pain assessed?");
    await page.getByRole("button", { name: "Ask", exact: true }).click();

    // `sources` arrives before any token by backend contract. Recording first-seen times
    // rather than asserting on a final snapshot is the only way to test an ORDERING —
    // by the time an answer has settled, both are present and the sequence is unobservable.
    const evidenceAt = await page
      .getByText(/source[s]? found|Evidence/i)
      .first()
      .waitFor({ state: "visible", timeout: 60_000 })
      .then(() => Date.now());

    const textAt = await page
      .locator(".answer-prose")
      .first()
      .waitFor({ state: "visible", timeout: 60_000 })
      .then(() => Date.now());

    expect(evidenceAt).toBeLessThanOrEqual(textAt);
  });

  test("Stop cancels an in-flight answer", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Your question").fill("What is cancer? Describe it in detail.");
    await page.getByRole("button", { name: "Ask", exact: true }).click();

    const stop = page.getByRole("button", { name: "Stop generating" });
    await stop.click({ timeout: 30_000 });

    // A cancel is a user CHOICE, not a failure: it must never render as an error.
    await expect(page.getByText(/Stopped\./)).toBeVisible();
    await expect(page.getByText(/Something went wrong/)).toHaveCount(0);
  });
});

test.describe("always-on safety surface", () => {
  test("the disclaimer is present and has no dismiss control", async ({ page }) => {
    await page.goto("/");
    const disclaimer = page.getByText("General information, not medical advice.");
    await expect(disclaimer).toBeVisible();

    // Non-dismissible by requirement: no close affordance anywhere in its container.
    const container = page.locator("body > div").first();
    await expect(container.getByRole("button")).toHaveCount(0);
  });

  test("the disclaimer survives navigation", async ({ page }) => {
    await page.goto("/design");
    await expect(page.getByText("General information, not medical advice.")).toBeVisible();
  });
});

test.describe("citations (S10.7)", () => {
  test("an inline marker opens its passage", async ({ page }) => {
    await page.goto("/design");
    const card = page.locator('[data-answer-kind="grounded"]').first();

    // The marker is a real control, not decoration.
    const marker = card.getByRole("button", { name: /Show source 1/ });
    await expect(marker).toBeVisible();

    const passage = card.locator("#evidence-0 button").first();
    await expect(passage).toHaveAttribute("aria-expanded", "false");
    await marker.click();
    await expect(passage).toHaveAttribute("aria-expanded", "true");
  });

  test("an out-of-range marker is NOT a link", async ({ page }) => {
    await page.goto("/design");
    // Three passages were retrieved, so [9] cannot be honoured. It must render as plain
    // text: turning a number the model invented into a clickable citation would
    // manufacture provenance the system does not have.
    await expect(page.getByRole("button", { name: /Show source 9/ })).toHaveCount(0);
    await expect(page.getByText(/visual analogue scale \[9\]/)).toBeVisible();
  });

  test("evidence marks passages the answer never cited", async ({ page }) => {
    await page.goto("/design");
    // Retrieved and fed to the model but not referenced. Hiding it would misrepresent
    // what the answer was actually built from.
    await expect(page.getByText("not cited").first()).toBeVisible();
  });
});

test.describe("session controls (S10.8)", () => {
  test("history restores and a past question can be re-asked", async ({ page }) => {
    const loaded = armTranscript(page);
    await ask(page, "How many mg of ibuprofen should I take for my back pain?");
    expect(await settled(page)).toBe("refused");
    await loaded;

    const panel = transcriptPanel(page);
    await expect(panel).toBeVisible();
    await expect(panel.getByText(/How many mg of ibuprofen/)).toBeVisible();

    // A past question is a control: clicking it asks it again.
    await panel.getByRole("button", { name: /How many mg of ibuprofen/ }).click();
    expect(await settled(page)).toBe("refused");
  });

  test("delete my data PROVES how much it removed", async ({ page }) => {
    // Scoped to DELETION. An earlier version also asserted the transcript had rendered
    // first, which made this test depend on a second async fetch and flake in full-suite
    // runs while passing in isolation. Transcript rendering is already covered by the
    // test above; a test that fails for a reason unrelated to its subject is noise.
    await ask(page, "How many mg of ibuprofen should I take for my back pain?");
    expect(await settled(page)).toBe("refused");

    await page.getByRole("button", { name: "Delete my data" }).click();
    await page.getByRole("button", { name: "Yes, delete" }).click();

    // A delete control that says "Done" without evidence passes review and fails an audit.
    await expect(page.getByText(/Deleted \d+ stored message/)).toBeVisible({ timeout: 30_000 });
    await expect(transcriptPanel(page)).toHaveCount(0);
  });
});

test.describe("error states (S10.9)", () => {
  test("hitting the quota renders the designed state, not a raw error", async ({ page }) => {
    await page.goto("/");
    // Burn the per-session minute quota through the SAME browser context, so the cookie
    // (and therefore the session bucket) is shared with the UI.
    const body = {
      question: "How many mg of ibuprofen should I take for my back pain?",
      stream: true,
    };
    for (let i = 0; i < 22; i++) {
      await page.request.post("/api/v1/query/stream", { data: body });
    }

    await page.getByLabel("Your question").fill("What is cirrhosis?");
    await page.getByRole("button", { name: "Ask", exact: true }).click();

    const err = page.locator("[data-error-slug]");
    await expect(err).toBeVisible({ timeout: 30_000 });
    await expect(err).toHaveAttribute("data-error-slug", "quota-exceeded");
    await expect(err).toContainText("reached the request limit");
    // A quota is a wait, not a retry: offering "Try again" would fail identically and
    // make the product look broken rather than busy.
    await expect(err.getByRole("button", { name: "Try again" })).toHaveCount(0);
    // Never red: red is reserved for medical emergencies.
    await expect(page.locator('[data-answer-kind="emergency"]')).toHaveCount(0);
  });
});

test.describe("transparency (S10.11)", () => {
  test("the panel is collapsed by default and opens with stage timings", async ({ page }) => {
    await page.goto("/design");
    const panel = card(page).first();

    const toggle = panel.getByRole("button", { name: /How this answer was made/ });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");

    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    // getByText is a SUBSTRING match by default and hit two nodes here. Definition-list
    // roles are exact and semantic, which is what these actually are.
    await expect(panel.getByRole("term").filter({ hasText: /^Model$/ })).toBeVisible();
    await expect(panel.getByText(/Rerank \d/)).toBeVisible();
    // The stage bar is decorative to sighted users but must carry a text alternative.
    await expect(panel.getByRole("img", { name: /Embed/ })).toBeVisible();
  });

  test("a live answer reports its real cost and token counts", async ({ page }) => {
    await ask(page, "What is cancer?");
    expect(await settled(page)).toBe("grounded");

    await card(page).getByRole("button", { name: /How this answer was made/ }).click();
    // Either a real cost, or an honest statement that this model is not billed per token —
    // never a bare "$0.00", which reads as free.
    await expect(
      card(page).getByText(/\$0\.\d{6}|not billed per token/),
    ).toBeVisible();
    await expect(card(page).getByText(/\d+ in ·/)).toBeVisible();
  });
});
