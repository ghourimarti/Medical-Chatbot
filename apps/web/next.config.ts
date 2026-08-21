import type { NextConfig } from "next";

const config: NextConfig = {
  // `standalone` emits a self-contained server with only the files actually imported.
  // Without it the runtime image carries the whole node_modules tree — the same dead-weight
  // problem P6.1a fixed on the Python side (26 GB -> 6.6 GB).
  output: "standalone",
  reactStrictMode: true,
  // The browser must never learn the API's address: it talks only to this origin, and the
  // BFF proxy (src/app/api/[...path]) forwards server-side. That is what makes CORS a
  // non-problem (D23) and keeps the API an internal service in Phase 7/8.
  env: {},
  // Deliberately NOT enabling `compress` for SSE: gzip buffering is a classic cause of
  // "streaming" that silently arrives in one chunk. Verified in scripts/verify-stream.mjs.
};

export default config;
