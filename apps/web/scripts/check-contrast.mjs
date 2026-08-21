/**
 * WCAG 2.2 contrast gate (D27).
 *
 * Run BEFORE building components on a palette, not during the a11y pass: discovering at
 * the end that half the pairs fail means restyling everything built on them. Ratios are
 * computed from the same hex values globals.css uses, so a token edit that breaks contrast
 * fails here rather than in a screenshot review.
 *
 * AA: 4.5:1 for body text, 3:1 for large text (>=18.66px bold / 24px) and UI boundaries.
 */
const srgb = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const luminance = (hex) => {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => srgb(v / 255));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a, b) => {
  const [l1, l2] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
};

const LIGHT = {
  surface: "#fafaf8", raised: "#ffffff", ink: "#1c1c1a", inkMuted: "#57564f",
  accent: "#0f766e", grounded: "#0f766e", noAnswer: "#475569",
  refused: "#a4550a", emergency: "#b91c1c", degraded: "#57534e",
};
const DARK = {
  surface: "#12140f", raised: "#1a1d17", ink: "#e9e7e0", inkMuted: "#a8a69c",
  accent: "#5eead4", grounded: "#5eead4", noAnswer: "#94a3b8",
  refused: "#fcd34d", emergency: "#fca5a5", degraded: "#d6d3d1",
};

const checks = [];
for (const [name, T] of [["light", LIGHT], ["dark", DARK]]) {
  const bg = T.surface;
  checks.push([`${name}: ink on surface`, ratio(T.ink, bg), 4.5]);
  checks.push([`${name}: ink-muted on surface`, ratio(T.inkMuted, bg), 4.5]);
  checks.push([`${name}: ink on raised`, ratio(T.ink, T.raised), 4.5]);
  checks.push([`${name}: accent on surface`, ratio(T.accent, bg), 4.5]);
  for (const kind of ["grounded", "noAnswer", "refused", "emergency", "degraded"]) {
    checks.push([`${name}: ${kind} on surface`, ratio(T[kind], bg), 4.5]);
    checks.push([`${name}: ${kind} on raised`, ratio(T[kind], T.raised), 4.5]);
  }
}
// White text on the accent button fill, and on the emergency fill.
checks.push(["light: white on accent fill", ratio("#ffffff", LIGHT.accent), 4.5]);
checks.push(["light: white on emergency fill", ratio("#ffffff", LIGHT.emergency), 4.5]);

let failed = 0;
for (const [label, r, min] of checks) {
  const ok = r >= min;
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${r.toFixed(2)}:1  (min ${min})  ${label}`);
}
console.log(failed ? `\n${failed} contrast failure(s)` : "\nAll contrast checks pass (WCAG AA).");
process.exit(failed ? 1 : 0);
