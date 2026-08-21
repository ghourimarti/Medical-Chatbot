"use client";

import { useState } from "react";
import { BookOpenCheck, ChevronDown } from "lucide-react";
import type { Citation } from "@/lib/contract";
import { parseCitations, referencedIndices } from "@/lib/citations";
import { cn } from "@/lib/utils";

/**
 * Citations (S10.7): inline markers, and an evidence list that can be opened per passage.
 *
 * CLICK, NOT HOVER. A hover-only preview does not exist on a phone, and this is used on
 * phones at night by worried people. Everything here is reachable by tap and by keyboard.
 */

/** Renders answer prose with [n] markers turned into buttons that open their passage. */
export function CitedProse({
  text,
  citations,
  onOpen,
  activeIndex,
}: {
  text: string;
  citations: Citation[];
  onOpen: (index: number) => void;
  activeIndex: number | null;
}) {
  const segments = parseCitations(text, citations.length);

  return (
    <p className="answer-prose whitespace-pre-wrap text-ink">
      {segments.map((seg, i) =>
        seg.type === "text" ? (
          <span key={i}>{seg.value}</span>
        ) : (
          <button
            key={i}
            onClick={() => onOpen(seg.index)}
            aria-label={`Show source ${seg.index + 1}: ${citations[seg.index]?.source ?? ""}`}
            className={cn(
              "mx-0.5 inline-flex min-w-[1.5rem] items-center justify-center rounded",
              "border px-1 align-baseline font-sans text-xs font-medium transition-colors",
              activeIndex === seg.index
                ? "border-grounded bg-grounded text-surface-raised"
                : "border-grounded/40 bg-grounded-wash text-grounded hover:border-grounded",
            )}
          >
            {seg.index + 1}
          </button>
        ),
      )}
    </p>
  );
}

/** The evidence list. Each passage expands to show the retrieved snippet. */
export function EvidenceList({
  citations,
  answerText,
  openIndex,
  onToggle,
}: {
  citations: Citation[];
  answerText: string;
  openIndex: number | null;
  onToggle: (index: number) => void;
}) {
  const referenced = referencedIndices(answerText, citations.length);

  return (
    <section aria-label="Evidence" className="mt-5 border-t border-line pt-4">
      <h3 className="mb-3 flex items-center gap-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
        <BookOpenCheck className="size-3.5 text-grounded" aria-hidden="true" />
        Evidence ({citations.length})
      </h3>

      <ol className="space-y-2">
        {citations.map((c, i) => {
          const open = openIndex === i;
          return (
            <li
              key={c.chunk_id}
              id={`evidence-${i}`}
              className={cn(
                "rounded-md border transition-colors",
                open ? "border-grounded/50 bg-grounded-wash" : "border-line bg-surface",
              )}
            >
              <button
                onClick={() => onToggle(i)}
                aria-expanded={open}
                aria-controls={`evidence-body-${i}`}
                className="flex w-full items-start gap-2.5 p-2.5 text-left"
              >
                <span className="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded border border-grounded/40 bg-grounded-wash text-xs font-medium text-grounded">
                  {i + 1}
                </span>

                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-ink">
                    {c.source}
                    {c.page !== null && (
                      <span className="text-ink-muted"> · p.{c.page}</span>
                    )}
                  </span>
                  <span className="mt-0.5 flex items-center gap-2 text-xs text-ink-muted">
                    {/* The retrieval score, shown plainly. It is a relevance score, not a
                        confidence in the medical claim — labelled so it cannot be misread
                        as "how true this is". */}
                    <span>relevance {c.score.toFixed(2)}</span>
                    {!referenced.has(i) && (
                      <span
                        className="rounded bg-surface-sunken px-1.5 py-0.5"
                        title="Retrieved and given to the model, but not cited in the answer"
                      >
                        not cited
                      </span>
                    )}
                  </span>
                </span>

                <ChevronDown
                  className={cn(
                    "mt-0.5 size-4 shrink-0 text-ink-muted transition-transform",
                    open && "rotate-180",
                  )}
                  aria-hidden="true"
                />
              </button>

              {open && (
                <div id={`evidence-body-${i}`} className="border-t border-line/60 px-2.5 py-3">
                  {c.snippet ? (
                    <blockquote className="border-l-2 border-grounded/40 pl-3 text-sm leading-relaxed text-ink-muted">
                      {c.snippet}
                    </blockquote>
                  ) : (
                    // Honest about a limitation instead of rendering an empty quote: the
                    // API sends a snippet, not the full passage, to keep every response
                    // small. Full text is an operator concern (answer_verbose).
                    <p className="text-sm text-ink-muted">
                      No preview text was returned for this passage.
                    </p>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** Convenience hook: which evidence item is open, and opening one from a marker. */
export function useEvidence() {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  function open(index: number) {
    setOpenIndex(index);
    // Bring the passage into view when opened from an inline marker — otherwise the
    // citation appears to do nothing on a long answer.
    requestAnimationFrame(() => {
      document
        .getElementById(`evidence-${index}`)
        ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }

  function toggle(index: number) {
    setOpenIndex((current) => (current === index ? null : index));
  }

  return { openIndex, open, toggle };
}
