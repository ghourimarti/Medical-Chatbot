import { expect, test, type Page } from "@playwright/test";

/**
 * Client-side streaming contract (S10.13), with the network mocked.
 *
 * Every other browser test drives the real backend, which is the right way to prove the
 * system works — but it cannot reach the states that matter most here. You cannot ask a
 * real model to reliably emit a dosage mid-answer so the output guardrail cuts it off, and
 * you cannot ask a healthy service for a 502.
 *
 * Mocking the SSE response makes those states deterministic AND removes the backend
 * dependency, so these run in CI where the full stack does not exist.
 */
function sse(frames: [string, unknown][]): string {
  return frames.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

const CITATION = {
  chunk_id: "c1",
  source: "Gale Encyclopedia of Medicine (2nd ed.)",
  page: 42,
  snippet: "Cirrhosis is a chronic degenerative disease of the liver.",
  score: 0.81,
};

const TIMINGS = {
  condense_ms: null,
  embed_ms: 180,
  retrieve_ms: 11,
  rerank_ms: 1024,
  generate_ms: 840,
  ttft_ms: 1200,
  total_ms: 2055,
};

async function mockStream(page: Page, body: string, status = 200) {
  await page.route("**/api/v1/query/stream", (route) =>
    route.fulfill({
      status,
      contentType: status === 200 ? "text/event-stream" : "application/problem+json",
      body,
    }),
  );
}

async function ask(page: Page, question = "What is cirrhosis?") {
  await page.goto("/chat");
  await page.getByLabel("Your question").fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
}

test.describe("terminal event is authoritative", () => {
  test("a refusal REPLACES the tokens already streamed", async ({ page }) => {
    // THE SAFETY CONTRACT (S10.2b). The output guardrail can cut a stream off mid-answer:
    // the model begins emitting a dose, the server stops it, and the terminal event is a
    // refusal. If the client appended instead of replacing, the retracted dose would stay
    // on screen — the exact failure the server-side fix exists to prevent.
    await mockStream(
      page,
      sse([
        ["sources", { citations: [CITATION] }],
        ["token", { text: "Take " }],
        ["token", { text: "500mg " }],
        [
          "done",
          {
            kind: "refused",
            text: "I can't provide dosage information. Please ask your pharmacist or prescribing clinician.",
            citations: [],
            model_id: "stub",
            usage: { prompt_tokens: 10, completion_tokens: 2, cost_usd: 0 },
            timings: TIMINGS,
            refusal_category: "dosage",
          },
        ],
      ]),
    );
    await ask(page);

    const card = page.locator("[data-answer-kind]");
    await expect(card).toHaveAttribute("data-answer-kind", "refused");
    // The partial dose must be GONE, not merely followed by a correction.
    await expect(card).not.toContainText("500mg");
    await expect(card).toContainText("can't provide dosage information");
    // A refusal cites nothing, even though a sources event arrived first.
    await expect(card.getByText(/Gale Encyclopedia/)).toHaveCount(0);
  });

  test("an emergency terminal event escalates even after tokens streamed", async ({ page }) => {
    await mockStream(
      page,
      sse([
        ["sources", { citations: [] }],
        ["token", { text: "Chest pain can " }],
        [
          "done",
          {
            kind: "refused",
            text: "This may be a medical emergency. Please contact your local emergency services immediately.",
            citations: [],
            model_id: "stub",
            usage: { prompt_tokens: 5, completion_tokens: 1, cost_usd: 0 },
            timings: TIMINGS,
            refusal_category: "emergency",
          },
        ],
      ]),
    );
    await ask(page, "I have crushing chest pain");

    const card = page.locator('[data-answer-kind="emergency"]');
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute("role", "alert");
    await expect(card).not.toContainText("Chest pain can ");
  });

  test("a grounded terminal event KEEPS the streamed text", async ({ page }) => {
    // The mirror image: when the answer is grounded, the streamed tokens are the answer and
    // must not be discarded in favour of the terminal copy.
    await mockStream(
      page,
      sse([
        ["sources", { citations: [CITATION] }],
        ["token", { text: "Cirrhosis is scarring " }],
        ["token", { text: "of the liver [1]." }],
        [
          "done",
          {
            kind: "grounded",
            text: "Cirrhosis is scarring of the liver [1].",
            citations: [CITATION],
            model_id: "stub",
            usage: { prompt_tokens: 900, completion_tokens: 12, cost_usd: 0.00014 },
            timings: TIMINGS,
            refusal_category: null,
          },
        ],
      ]),
    );
    await ask(page);

    const card = page.locator("[data-answer-kind]");
    await expect(card).toHaveAttribute("data-answer-kind", "grounded");
    await expect(card).toContainText("Cirrhosis is scarring of the liver");
    await expect(card.getByRole("button", { name: /Show source 1/ })).toBeVisible();
  });
});

test.describe("in-band and transport failures", () => {
  test("an error EVENT mid-stream renders the designed state", async ({ page }) => {
    // Once bytes are on the wire the HTTP status is already 200, so the server must report
    // failures in-band. The client has to honour that second channel.
    await mockStream(
      page,
      sse([
        ["sources", { citations: [] }],
        [
          "error",
          {
            problem: {
              type: "https://p5-medical-chatbot/problems/provider-error",
              title: "Model Provider Error",
              status: 502,
              detail: "The answering model is temporarily unavailable.",
            },
          },
        ],
      ]),
    );
    await ask(page);

    const err = page.locator("[data-error-slug]");
    await expect(err).toHaveAttribute("data-error-slug", "provider-error");
    await expect(err).toContainText("answering model is temporarily unavailable");
    await expect(err.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  test("a 429 before the stream starts renders the quota state with no retry", async ({
    page,
  }) => {
    await mockStream(
      page,
      JSON.stringify({
        type: "https://p5-medical-chatbot/problems/quota-exceeded",
        title: "Quota Exceeded",
        status: 429,
        detail: "You have reached your request limit.",
      }),
      429,
    );
    await ask(page);

    const err = page.locator("[data-error-slug]");
    await expect(err).toHaveAttribute("data-error-slug", "quota-exceeded");
    // A quota is a wait, not a retry.
    await expect(err.getByRole("button", { name: "Try again" })).toHaveCount(0);
  });

  test("no answer card is rendered when the request fails", async ({ page }) => {
    await mockStream(page, JSON.stringify({ type: "x", title: "y", status: 503, detail: "z" }), 503);
    await ask(page);
    await expect(page.locator("[data-error-slug]")).toBeVisible();
    // A failure must never leave a half-rendered answer beside the error.
    await expect(page.locator("[data-answer-kind]")).toHaveCount(0);
  });
});

test.describe("degraded mode", () => {
  test("a degraded status shows a standing banner", async ({ page }) => {
    await page.route("**/api/v1/status", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "degraded",
          checks: { vector_store: true, embedder: true },
          generation_enabled: false,
          corpus: { version: "v1", index_version: "v1" },
        }),
      }),
    );
    await page.goto("/chat");
    // A standing condition needs a standing signal — the user should know before typing.
    await expect(page.getByText("Limited service.")).toBeVisible();
  });

  test("a healthy status shows no banner", async ({ page }) => {
    await page.route("**/api/v1/status", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "ok",
          checks: { vector_store: true, embedder: true },
          generation_enabled: true,
          corpus: { version: "v1", index_version: "v1" },
        }),
      }),
    );
    await page.goto("/chat");
    await expect(page.getByText("Limited service.")).toHaveCount(0);
  });
});
