/**
 * Empty-state illustration (S24).
 *
 * INLINE SVG, not an image file. It costs no request, scales without a second asset, and
 * — the reason that actually matters here — it is drawn in `currentColor` and theme
 * tokens, so it follows light/dark automatically. A raster would need two files and would
 * still be wrong for anyone on a theme we did not export.
 *
 * WHAT IT DEPICTS, and why not something friendlier: an open reference book with a page of
 * text and a marked passage, with a magnifier over it. Not a robot, not a stethoscope, not
 * a smiling assistant. The product does exactly one thing — it reads a fixed encyclopedia
 * and shows you the passage — and an illustration that implied a clinician or an AI
 * companion would be promising something it deliberately refuses to do. An empty state is
 * a promise about what happens next, so it should not overstate.
 *
 * `aria-hidden`: it carries no information the adjacent heading does not already say, and
 * announcing "decorative illustration" to a screen reader is noise.
 */
export function EmptyStateArt({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 200 130"
      fill="none"
      aria-hidden="true"
      className={className}
      role="presentation"
    >
      {/* Page ground — the one filled shape, kept very low contrast so it reads as paper
          rather than as a card competing with the real cards below it. */}
      <path
        d="M30 26h64c5 0 9 3 9 7v70c0-4-4-7-9-7H30V26Z"
        className="fill-[var(--surface-sunken)]"
      />
      <path
        d="M170 26h-64c-5 0-9 3-9 7v70c0-4 4-7 9-7h64V26Z"
        className="fill-[var(--surface-sunken)]"
      />

      {/* Book outline */}
      <path
        d="M30 26h64c5 0 9 3 9 7v70c0-4-4-7-9-7H30V26Zm140 0h-64c-5 0-9 3-9 7v70c0-4 4-7 9-7h64V26Z"
        stroke="var(--line-strong)"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <path d="M100 33v70" stroke="var(--line-strong)" strokeWidth="2.5" />

      {/* Lines of text. The right page is deliberately sparser — a book being read, not a
          symmetrical logo. */}
      {[44, 56, 68, 80].map((y) => (
        <path
          key={`l${y}`}
          d={`M42 ${y}h44`}
          stroke="var(--line-strong)"
          strokeWidth="3"
          strokeLinecap="round"
          opacity="0.55"
        />
      ))}
      {[44, 56].map((y) => (
        <path
          key={`r${y}`}
          d={`M114 ${y}h44`}
          stroke="var(--line-strong)"
          strokeWidth="3"
          strokeLinecap="round"
          opacity="0.55"
        />
      ))}

      {/* THE CITED PASSAGE — the only accent in the drawing, because it is the only thing
          the product actually promises. */}
      <path
        d="M114 68h30"
        stroke="var(--accent)"
        strokeWidth="3.5"
        strokeLinecap="round"
      />
      <rect
        x="112"
        y="62"
        width="36"
        height="12"
        rx="3"
        stroke="var(--accent)"
        strokeWidth="2"
        opacity="0.4"
      />

      {/* Magnifier over the marked passage: checking, not just reading. */}
      <circle
        cx="150"
        cy="88"
        r="17"
        stroke="var(--accent)"
        strokeWidth="2.5"
        className="fill-[var(--surface)]"
        opacity="0.95"
      />
      <path
        d="M162 100l11 11"
        stroke="var(--accent)"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <path
        d="M143 88h14M143 94h9"
        stroke="var(--accent)"
        strokeWidth="2"
        strokeLinecap="round"
        opacity="0.7"
      />
    </svg>
  );
}
