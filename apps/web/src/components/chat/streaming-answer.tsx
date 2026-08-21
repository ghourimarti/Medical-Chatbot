"use client";

import { BookOpenCheck, Loader2 } from "lucide-react";
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

  return (
    <div className="space-y-5" aria-busy="true">
      {/* Stage 1 — retrieval in flight. */}
      {!sourcesSeen && (
        <p className="flex items-center gap-2 text-sm text-ink-muted">
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          Searching the reference corpus…
        </p>
      )}

      {/* Stage 2 — evidence, painted the moment it lands. */}
      {hasSources && (
        <section
          aria-label="Evidence"
          className="rounded-lg border border-line bg-surface-raised p-4"
        >
          <h2 className="mb-2.5 flex items-center gap-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
            <BookOpenCheck className="size-3.5 text-grounded" aria-hidden="true" />
            {citations.length} source{citations.length === 1 ? "" : "s"} found
          </h2>
          <ol className="flex flex-wrap gap-2">
            {citations.map((c, i) => (
              <li key={c.chunk_id}>
                <span className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink-muted">
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
          {text}
          {/* A caret, not a spinner: it says "still writing" without implying a stall.
              globals.css collapses this animation under prefers-reduced-motion. */}
          <span
            className="ml-0.5 inline-block h-[1.1em] w-[2px] animate-pulse bg-accent align-text-bottom"
            aria-hidden="true"
          />
        </p>
      ) : (
        hasSources && (
          <p className="flex items-center gap-2 text-sm text-ink-muted">
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            Composing an answer from these sources…
          </p>
        )
      )}

      {/* Screen readers get one polite summary rather than a token-by-token barrage, which
          is unusable: every incremental update would interrupt the previous announcement. */}
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
