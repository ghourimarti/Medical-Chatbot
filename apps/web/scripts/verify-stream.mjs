/**
 * D23 PROOF: does SSE survive the BFF proxy, or does Next buffer it?
 *
 * "Streaming works" is the easiest thing in this stack to believe without evidence: a
 * buffered response contains exactly the same bytes as a streamed one, so the only
 * difference is WHEN they arrive. This spins up a mock upstream that emits tokens at a
 * known cadence, reads through the proxy, and asserts the cadence survives.
 *
 * Usage: node scripts/verify-stream.mjs <webBaseUrl>
 * Requires the web server started with API_BASE_URL pointing at MOCK_PORT.
 */
import { createServer } from "node:http";

const MOCK_PORT = 5099;
const GAP_MS = 120;
const TOKENS = ["An ", "abscess ", "is ", "a ", "pus-filled ", "area."];
const WEB = process.argv[2] ?? "http://localhost:5008";

const mock = createServer((req, res) => {
  res.writeHead(200, {
    "content-type": "text/event-stream",
    "cache-control": "no-cache",
    "x-accel-buffering": "no",
  });
  const send = (event, data) => res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  send("sources", { citations: [{ chunk_id: "c1", source: "Mock", page: 1, snippet: "", score: 1 }] });
  let i = 0;
  const timer = setInterval(() => {
    if (i < TOKENS.length) {
      send("token", { text: TOKENS[i++] });
    } else {
      clearInterval(timer);
      send("done", {
        kind: "grounded", text: TOKENS.join(""), citations: [],
        model_id: "mock", usage: {}, timings: {}, refusal_category: null,
      });
      res.end();
    }
  }, GAP_MS);
  req.on("close", () => clearInterval(timer));
});

await new Promise((r) => mock.listen(MOCK_PORT, r));

const started = performance.now();
const res = await fetch(`${WEB}/api/v1/query/stream`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ question: "What is an abscess?", stream: true }),
});

if (!res.ok) {
  console.error(`FAIL: proxy returned HTTP ${res.status}`);
  mock.close();
  process.exit(1);
}

const arrivals = [];
const reader = res.body.getReader();
const decoder = new TextDecoder();
let buf = "";
for (;;) {
  const { done, value } = await reader.read();
  if (done) break;
  buf += decoder.decode(value, { stream: true });
  let b;
  while ((b = buf.indexOf("\n\n")) !== -1) {
    const frame = buf.slice(0, b);
    buf = buf.slice(b + 2);
    if (frame.includes("event: token")) arrivals.push(Math.round(performance.now() - started));
  }
}
mock.close();

console.log(`token arrivals (ms): ${arrivals.join(", ")}`);
if (arrivals.length < 2) {
  console.error(`FAIL: expected ${TOKENS.length} token frames, saw ${arrivals.length}`);
  process.exit(1);
}
const spread = arrivals[arrivals.length - 1] - arrivals[0];
const expected = GAP_MS * (TOKENS.length - 1);
console.log(`spread ${spread}ms (upstream cadence implies ~${expected}ms)`);

// A buffered proxy delivers every frame in one chunk: spread collapses toward 0.
if (spread < expected * 0.5) {
  console.error(`FAIL: BUFFERED — ${arrivals.length} tokens arrived within ${spread}ms`);
  process.exit(1);
}
console.log("PASS: cadence preserved end-to-end; the proxy streams.");
