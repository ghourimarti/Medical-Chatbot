import type { NextConfig } from "next";

const config: NextConfig = {
  // `standalone` emits a self-contained server with only the files actually imported,
  // which is what keeps the runtime image small — the same dead-weight problem P6.1a fixed
  // on the Python side (26 GB -> 6.6 GB).
  //
  // BUT IT IS OPT-IN, because it changes what `next start` means. With standalone output
  // Next produces its own server at .next/standalone/server.js and prints
  //   "next start does not work with output: standalone"
  // then exits non-zero. Having it on unconditionally made `pnpm preview` — literally
  // `next build && next start` — an unsupported combination that failed intermittently,
  // which is worse than failing every time.
  //
  // Standalone is a DEPLOYMENT concern. The Dockerfile (S10.14) sets BUILD_STANDALONE=1;
  // local preview builds normally and `next start` is valid again.
  output: process.env.BUILD_STANDALONE === "1" ? "standalone" : undefined,
  reactStrictMode: true,
  // The browser must never learn the API's address: it talks only to this origin, and the
  // BFF proxy (src/app/api/[...path]) forwards server-side. That is what makes CORS a
  // non-problem (D23) and keeps the API an internal service in Phase 7/8.
  env: {},
  // Deliberately NOT enabling `compress` for SSE: gzip buffering is a classic cause of
  // "streaming" that silently arrives in one chunk. Verified in scripts/verify-stream.mjs.
};

export default config;
