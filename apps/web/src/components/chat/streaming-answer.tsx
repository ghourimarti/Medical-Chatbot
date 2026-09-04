"use client";

import { useEffect, useRef, useState } from "react";
import { BookOpenCheck } from "lucide-react";
import type { Citation } from "@/lib/contract";

/**
 * The streaming surface — where the backend's ordering contract becomes visible.
 *
 * `sources` arrives before any token, so evidence paints first and the answer is written
 * beneath it. That sequence IS the product claim: the system shows what it is reading
 * before it tells you what it thinks.
 *
 * The subtle case: a guardrail refusal emits `sources` with ZERO citations and then a
 * terminal event with no tokens at all. Rendering "0 sources found" there would report a
 * retrieval failure for a question that was never retrieved for. So an empty source set
 * during streaming shows nothing — the terminal event will explain itself in a moment.
 *
 * MOTION (F7). The stages were two spinners; they are now a labelled progression, because
 * the honest thing to show during a 6-second wait is WHICH part is slow. A spinner says
 * "blocked" and says it identically at 200ms and at 8s. Every animation here is switched
 * off by the prefers-reduced-motion block in globals.css — for someone anxious at 2am,
 * motion is not decoration.
 */
export function StreamingAnswer({
  citations,
  sourcesSeen,
  text,
}: {
  citations: Citation[];
  sourcesSeen: boolean;
  text: string;
}) {
  const hasSources = sourcesSeen && citations.length > 0;

  // Everything the reader has already seen, versus what landed on this render.
  //
  // `settledRef` trails `text` by one frame: the effect runs AFTER paint, so the newest
  // chunk gets one animation cycle and then joins the settled body. Without the ref the
  // whole answer would re-fade on every single chunk, which at streaming speed is a
  // strobe rather than an arrival.
  const settledRef = useRef("");
  const [, force] = useState(0);
  const settled = text.startsWith(settledRef.current) ? settledRef.current : "";
  const fresh = text.slice(settled.length);

  useEffect(() => {
    if (settledRef.current === text) return;
    const id = window.setTimeout(() => {
      settledRef.current = text;
      force((n) => n + 1);
    }, 260);
    return () => window.clearTimeout(id);
  }, [text]);

  return (
    <div className="space-y-5" aria-busy="true">
      {/* Stage 1 — retrieval in flight, with a skeleton standing in for the evidence
          block that is about to appear. Reserving that space stops the answer jumping
          down the page the moment sources land. */}
      {!sourcesSeen && (
        <div className="space-y-3">
          <Thinking label="Searching the reference corpus" />
          <div className="space-y-2" aria-hidden="true">
            <div className="shimmer h-9 rounded-md" />
            <div className="shimmer h-9 w-11/12 rounded-md" />
          </div>
        </div>
      )}

      {/* Stage 2 — evidence, painted the moment it lands. */}
      {hasSources && (
        <section aria-label="Evidence" className="turn-enter space-y-2.5">
          <h2 className="flex items-center gap-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
            <BookOpenCheck className="size-3.5 text-grounded" aria-hidden="true" />
            {citations.length} source{citations.length === 1 ? "" : "s"} found
          </h2>
          <ol className="flex flex-wrap gap-2">
            {citations.map((c, i) => (
              <li key={c.chunk_id}>
                <span className="lift inline-flex items-center gap-1.5 rounded-md border border-line bg-surface-raised px-2 py-1 text-xs text-ink-muted">
                  <span className="font-medium text-grounded">[{i + 1}]</span>
                  {c.source}
                  {c.page !== null && <span>p.{c.page}</span>}
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {/* Stage 3 — tokens. */}
      {text ? (
        <p className="answer-prose whitespace-pre-wrap text-ink">
          {/* Settled text renders plainly; only the CHUNK that just arrived fades in.
              Splitting it this way is what makes the effect honest — tokens arrive in
              chunks, so a per-character typewriter would be animating a cadence the model
              never produced. Keyed on the length so React treats each arrival as a new
              element and restarts the animation. */}
          {settled}
          {fresh && (
            <span key={settled.length} className="token-in">
              {fresh}
            </span>
          )}
          {/* A caret, not a spinner: it says "still writing" without implying a stall. */}
          <span
            className="ml-0.5 inline-block h-[1.1em] w-[2px] animate-pulse bg-accent align-text-bottom"
            aria-hidden="true"
          />
        </p>
      ) : (
        hasSources && <Thinking label="Composing an answer from these sources" />
      )}

      {/* Screen readers get one polite summary rather than a token-by-token barrage, which
          is unusable: every incremental update would interrupt the previous announcement.
          The visual stages above changed; this contract did not. */}
      <span className="sr-only" role="status" aria-live="polite">
        {!sourcesSeen
          ? "Searching the reference corpus"
          : text
            ? "Writing the answer"
            : "Sources found, composing an answer"}
      </span>
    </div>
  );
}

/** Label plus three staggered dots. `aria-hidden` on the dots: the live region above
 *  already announces the stage, and an animation has nothing to say to a screen reader. */
function Thinking({ label }: { label: string }) {
  return (
    <p className="flex items-center gap-2 text-sm text-ink-muted">
      {label}
      <span className="inline-flex gap-1" aria-hidden="true">
        <span className="thinking-dot size-1.5 rounded-full bg-ink-muted" />
        <span className="thinking-dot size-1.5 rounded-full bg-ink-muted" />
        <span className="thinking-dot size-1.5 rounded-full bg-ink-muted" />
      </span>
    </p>
  );
}
