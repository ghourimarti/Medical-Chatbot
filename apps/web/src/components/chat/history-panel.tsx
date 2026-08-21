"use client";

import { History } from "lucide-react";

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
}

/**
 * Earlier turns in this session (S10.8).
 *
 * DELIBERATELY a plain transcript, not the AnswerCard treatments.
 *
 * `GET /api/v1/session/history` returns only `{role, content}`. The database does store
 * `kind`, but the repository drops it on read and `Message` — the type that would carry it
 * — is the LLM prompt type, shared with generation and frozen. Reusing the treatment
 * components here would therefore mean GUESSING the kind, and a past emergency refusal
 * rendered as an ordinary answer is exactly the misrepresentation this UI exists to avoid.
 *
 * So history is presented as what it verifiably is: a record of what was said. The live
 * answer, where the kind IS known, keeps the full treatment.
 */
export function HistoryPanel({
  messages,
  onReask,
}: {
  messages: HistoryMessage[];
  onReask: (question: string) => void;
}) {
  if (messages.length === 0) return null;

  return (
    <section aria-label="Earlier in this session" className="space-y-3">
      <h2 className="flex items-center gap-2 text-xs font-medium tracking-wide text-ink-muted uppercase">
        <History className="size-3.5" aria-hidden="true" />
        Earlier in this session
      </h2>

      <ol className="space-y-3 border-l-2 border-line pl-4">
        {messages.map((m, i) => (
          <li key={i} className="text-sm">
            {m.role === "user" ? (
              <button
                onClick={() => onReask(m.content)}
                className="text-left font-medium text-ink hover:text-accent"
                title="Ask this again"
              >
                {m.content}
              </button>
            ) : (
              <p className="mt-1 whitespace-pre-wrap text-ink-muted">{m.content}</p>
            )}
          </li>
        ))}
      </ol>

      <p className="text-xs text-ink-muted">
        Transcript only — sources are shown with the live answer, not stored with history.
      </p>
    </section>
  );
}
