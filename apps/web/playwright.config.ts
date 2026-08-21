import { defineConfig, devices } from "@playwright/test";

/**
 * Runs against an ALREADY-RUNNING stack, deliberately.
 *
 * `webServer` could start Next for us, but the tests that matter here exercise the real
 * backend — retrieval, guardrails, streaming — and silently starting a web tier pointed at
 * a missing API would produce failures that look like UI bugs. Requiring the stack up front
 * makes the dependency explicit: `make app && make web-preview`.
 */
const BASE_URL = process.env.WEB_BASE_URL ?? "http://localhost:5008";

export default defineConfig({
  testDir: "./e2e",
  // Streaming answers take seconds and a cold rerank can take longer; a tight default
  // timeout would report the backend being honest as a test failure.
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  // Serial: the API enforces a per-session rate limit, and parallel workers sharing an IP
  // would trip the IP bucket and produce 429s that look like product bugs.
  workers: 1,
  // ONE retry, deliberately, with the reason recorded.
  //
  // This suite drives a REAL backend: a cold generation takes seconds while a cache hit
  // takes ~50ms, roughly 20x variance, and a cold ml-service rerank is slower still. That
  // is legitimate system behaviour, not a product defect, and it makes the first run after
  // an idle period occasionally exceed a timeout that the second run clears comfortably.
  //
  // A retry is honest here because a REAL failure still fails twice: this distinguishes
  // "slow" from "broken". It is not a licence to ignore a test that fails consistently —
  // if something needs two attempts every time, that is a defect wearing a flake costume.
  retries: 1,
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
