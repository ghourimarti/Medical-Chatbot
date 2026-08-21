"use client";

import { useState } from "react";
import { ChevronDown, Gauge } from "lucide-react";
import type { Answer } from "@/lib/contract";
import { cn } from "@/lib/utils";

/**
 * "How this answer was made" (S10.11).
 *
 * Collapsed by default: this is for the curious and for anyone auditing the system, not
 * part of reading an answer. Someone looking up a symptom should not have to scroll past
 * latency figures to reach the content.
 *
 * TWO HONESTY PROBLEMS, both found by reading real responses rather than the schema:
 *
 * 1. A cache hit returns the ORIGINAL generation's timings. Measured: a reused answer
 *    arrived in about 50 ms while reporting total_ms 2054. Presenting that as "this
 *    request took 2 seconds" would be false, so cached timings are explicitly labelled as
 *    belonging to the original generation.
 *
 * 2. A cache hit also returns the original cost_usd. No new tokens were bought, so that
 *    number is what reuse AVOIDED, not what this answer spent. Labelling it "cost" would
 *    inflate every reported total.
 */
const STAGES = [
  { key: "condense_ms", label: "Condense" },
  { key: "embed_ms", label: "Embed" },
  { key: "retrieve_ms", label: "Retrieve" },
  { key: "rerank_ms", label: "Rerank" },
  { key: "generate_ms", label: "Generate" },
] as const;

const STAGE_TINT = [
  "bg-no-answer/50",
  "bg-accent/40",
  "bg-accent/60",
  "bg-grounded/70",
  "bg-grounded",
];

function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`;
}

export function TransparencyPanel({ answer }: { answer: Answer }) {
  const [open, setOpen] = useState(false);
  const t = answer.timings;
  const cached = answer.cache_hit;

  const stages = STAGES.map((s) => ({ ...s, value: t[s.key] ?? 0 })).filter(
    (s) => s.value > 0,
  );
  const measured = stages.reduce((sum, s) => sum + s.value, 0);

  return (
    <div className="mt-4 border-t border-line pt-3">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="transparency-body"
        className="flex items-center gap-2 text-xs text-ink-muted hover:text-ink"
      >
        <Gauge className="size-3.5" aria-hidden="true" />
        How this answer was made
        <ChevronDown
          className={cn("size-3.5 transition-transform", open && "rotate-180")}
          aria-hidden="true"
        />
      </button>

      {open && (
        <div id="transparency-body" className="mt-3 space-y-4 text-sm">
          {cached && (
            <p className="rounded-md bg-surface-sunken px-3 py-2 text-ink-muted">
              <span className="font-medium text-ink">Reused from an identical question.</span>{" "}
              No model was called and no new tokens were bought. The figures below describe
              the original generation, not this request.
            </p>
          )}

          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5">
            <dt className="text-ink-muted">Model</dt>
            <dd className="font-mono text-xs text-ink">{answer.model_id ?? "—"}</dd>

            <dt className="text-ink-muted">Tokens</dt>
            <dd className="text-ink">
              {answer.usage.prompt_tokens.toLocaleString()} in ·{" "}
              {answer.usage.completion_tokens.toLocaleString()} out
            </dd>

            <dt className="text-ink-muted">{cached ? "Cost avoided" : "Cost"}</dt>
            <dd className="text-ink">
              {answer.usage.cost_usd > 0 ? (
                `$${answer.usage.cost_usd.toFixed(6)}`
              ) : (
                // Self-hosted venues price at $0/token by construction — their cost is
                // GPU time, accounted separately. Printing "$0.00" would read as free.
                <span className="text-ink-muted">
                  not billed per token for this model
                </span>
              )}
            </dd>
          </dl>

          {stages.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs font-medium tracking-wide text-ink-muted uppercase">
                {cached ? "Original generation" : "Time in each stage"}
              </h4>

              <div
                className="flex h-2 overflow-hidden rounded-full bg-surface-sunken"
                role="img"
                aria-label={stages.map((s) => `${s.label} ${ms(s.value)}`).join(", ")}
              >
                {stages.map((s, i) => (
                  <div
                    key={s.key}
                    className={STAGE_TINT[i % STAGE_TINT.length]}
                    style={{ width: `${(s.value / measured) * 100}%` }}
                  />
                ))}
              </div>

              <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
                {stages.map((s, i) => (
                  <li key={s.key} className="flex items-center gap-1.5">
                    <span
                      className={cn("size-2 rounded-full", STAGE_TINT[i % STAGE_TINT.length])}
                      aria-hidden="true"
                    />
                    {s.label} {ms(s.value)}
                  </li>
                ))}
              </ul>

              <p className="text-xs text-ink-muted">
                Total {ms(t.total_ms)}
                {t.ttft_ms !== null && <> · first token {ms(t.ttft_ms)}</>}
                {/* The stages rarely sum to the total: queueing, serialisation and network
                    live in the gap. Naming it stops the panel implying the breakdown is
                    exhaustive when it is not. */}
                {t.total_ms > measured + 1 && (
                  <> · {ms(t.total_ms - measured)} elsewhere (queueing, transport)</>
                )}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
