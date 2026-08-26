/**
 * Performance budget (S10.12).
 *
 * Runs `next build` and asserts each route's First Load JS against a budget. A budget that
 * is not enforced is a wish: bundles grow one convenient dependency at a time, and nobody
 * ever notices the single commit that made the page slow.
 *
 * First Load JS is the right metric here because it is what a first-time visitor on a phone
 * actually waits for before the page is interactive.
 */
import { execSync } from "node:child_process";

const BUDGETS_KB = {
  "/": 150,          // the chat surface: streaming state machine, citations, transparency
  "/design": 130,    // gallery
  default: 130,      // public information pages
};

// `pnpm exec`, not a bare `next`: node_modules/.bin is only on PATH inside a package
// script, so invoking this file directly with `node` would otherwise fail to find next.
const out = execSync("pnpm exec next build", {
  encoding: "utf8",
  stdio: ["ignore", "pipe", "pipe"],
});

// Rows look like:  ┌ ○ /            6.24 kB    125 kB
const rows = [...out.matchAll(/[┌├└]\s+[○ƒ●]\s+(\S+)\s+[\d.]+\s*[kMB]+\s+([\d.]+)\s*kB/g)].map(
  (m) => ({ route: m[1], firstLoadKb: Number(m[2]) }),
);

if (rows.length === 0) {
  console.error("FAIL: could not parse the build output — the budget check is inert.");
  console.error(out.split("\n").slice(-25).join("\n"));
  process.exit(1);
}

let failed = 0;
for (const { route, firstLoadKb } of rows) {
  const budget = BUDGETS_KB[route] ?? BUDGETS_KB.default;
  const ok = firstLoadKb <= budget;
  if (!ok) failed++;
  const head = ok ? "PASS" : "FAIL";
  console.log(`${head}  ${String(firstLoadKb).padStart(6)} kB / ${budget} kB  ${route}`);
}
console.log(
  failed ? `\n${failed} route(s) over budget` : `\nAll ${rows.length} routes within budget.`,
);
process.exit(failed ? 1 : 0);
