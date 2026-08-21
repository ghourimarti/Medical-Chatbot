"use client";

import type { Answer } from "@/lib/contract";
import { cn } from "@/lib/utils";
import { EmergencyCard } from "./emergency-card";
import { CitedProse, EvidenceList, useEvidence } from "./evidence";
import { TREATMENTS, resolveTreatment } from "./kind-meta";
import { TransparencyPanel } from "./transparency";

/**
 * Renders an Answer according to its resolved treatment. Four kinds, four DISTINCT
 * presentations — never one rendered as another, which is what makes an abstention legible
 * as honesty and a refusal legible as care.
 */
export function AnswerCard({ answer }: { answer: Answer }) {
  const treatment = resolveTreatment(answer.kind, answer.refusal_category);
  const { openIndex, open, toggle } = useEvidence();

  if (treatment === "emergency") return <EmergencyCard answer={answer} />;

  const meta = TREATMENTS[treatment];
  const Icon = meta.icon;
  const hasEvidence = answer.citations.length > 0;

  return (
    <article
      // A stable hook for tests and debugging. Asserting the resolved TREATMENT is
      // stronger than matching label prose: copy changes are expected, a grounded answer
      // silently rendering with the refusal treatment is not.
      data-answer-kind={treatment}
      className={cn(
        "rounded-lg border bg-surface-raised p-5",
        treatment === "grounded" ? "border-line" : meta.border,
      )}
      aria-labelledby={`answer-label-${treatment}`}
    >
      <div className="mb-3 flex items-center gap-2">
        <Icon className={cn("size-4 shrink-0", meta.fg)} aria-hidden="true" />
        <h2 id={`answer-label-${treatment}`} className={cn("text-sm font-medium", meta.fg)}>
          {meta.label}
        </h2>
      </div>

      {hasEvidence ? (
        // Only a grounded answer has citations, so only it gets interactive markers.
        // Running the parser over a refusal would be harmless but meaningless — and a
        // refusal that appeared to cite sources would be actively misleading.
        <CitedProse
          text={answer.text}
          citations={answer.citations}
          onOpen={open}
          activeIndex={openIndex}
        />
      ) : (
        <p className="answer-prose whitespace-pre-wrap text-ink">{answer.text}</p>
      )}

      {treatment === "no_answer" && (
        <p className="mt-4 max-w-[68ch] text-sm text-ink-muted">
          This assistant only answers from its medical reference corpus, and will not guess
          when a topic is missing. Try rephrasing, or ask about a different condition.
        </p>
      )}

      {hasEvidence && (
        <EvidenceList
          citations={answer.citations}
          answerText={answer.text}
          openIndex={openIndex}
          onToggle={toggle}
        />
      )}

      {/* Shown for every kind, including refusals: "why did it refuse and what did that
          cost" is a legitimate question, and hiding the panel on refusals would make the
          system least inspectable exactly where it is most opinionated. */}
      <TransparencyPanel answer={answer} />
    </article>
  );
}
