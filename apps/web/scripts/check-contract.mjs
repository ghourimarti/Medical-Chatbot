/**
 * Cross-language contract guard.
 *
 * src/lib/contract.ts is a HAND-WRITTEN mirror of the Python schema, which buys clarity at
 * the cost of drift. This is the cost being paid back: it caught a real one — the TS union
 * listed 5 of the backend's 8 refusal categories, and the missing `harmful` (which carries
 * crisis-helpline copy) would have rendered as a routine amber refusal.
 *
 * Compares the RefusalCategory enum in guardrails.py against the TS union, and AnswerKind
 * in schema.py against its TS counterpart.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "../../..");
const read = (p) => readFileSync(resolve(ROOT, p), "utf8");

function pyEnum(src, className) {
  const body = src.split(`class ${className}`)[1] ?? "";
  const stop = body.search(/\n\S/);
  return new Set(
    [...(stop === -1 ? body : body.slice(0, stop)).matchAll(/=\s*"([a-z_]+)"/g)].map((m) => m[1]),
  );
}
function tsUnion(src, typeName) {
  const decl = src.split(`export type ${typeName} =`)[1]?.split(";")[0] ?? "";
  return new Set([...decl.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]));
}

const cases = [
  {
    label: "RefusalCategory",
    py: pyEnum(read("apps/api/src/medapi/guardrails.py"), "RefusalCategory"),
    ts: tsUnion(read("apps/web/src/lib/contract.ts"), "RefusalCategory"),
  },
  {
    label: "AnswerKind",
    py: pyEnum(read("packages/core/src/medcore/schema.py"), "AnswerKind"),
    ts: tsUnion(read("apps/web/src/lib/contract.ts"), "AnswerKind"),
  },
];

let failed = 0;
for (const { label, py, ts } of cases) {
  const missing = [...py].filter((v) => !ts.has(v));
  const extra = [...ts].filter((v) => !py.has(v));
  if (py.size === 0) {
    console.log(`FAIL ${label}: parsed 0 values from Python — the parser, not the code, broke`);
    failed++;
    continue;
  }
  if (missing.length || extra.length) {
    failed++;
    console.log(`FAIL ${label}: missing in TS [${missing}] · not in Python [${extra}]`);
  } else {
    console.log(`PASS ${label}: ${py.size} values match`);
  }
}
console.log(failed ? `\n${failed} contract mismatch(es)` : "\nFrontend contract matches the backend.");
process.exit(failed ? 1 : 0);
