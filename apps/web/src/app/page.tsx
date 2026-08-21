"use client";

import { useCallback, useEffect, useState } from "react";
import { AnswerCard } from "@/components/answer/answer-card";
import { DataControlsRow } from "@/components/chat/data-controls-row";
import { DegradedBanner, ErrorState } from "@/components/chat/error-state";
import { HistoryPanel, type HistoryMessage } from "@/components/chat/history-panel";
import { QuestionBox } from "@/components/chat/question-box";
import { StreamingAnswer } from "@/components/chat/streaming-answer";
import { Button } from "@/components/ui/button";
import type { PublicStatus } from "@/lib/contract";
import { useAnswerStream } from "@/lib/use-answer-stream";

/**
 * The chat surface (S10.5, extended in S10.7-S10.9).
 *
 * Search-first landing: the question box is the page, not a bar bolted to an empty chat
 * log. Someone arriving with a health question should not have to work out where to type.
 */

/** Real topics from the reference corpus, so an example never demonstrates a question the
 *  system cannot answer. */
const EXAMPLES = [
  "What is cirrhosis?",
  "What causes conjunctivitis?",
  "How is croup treated?",
];

export default function Page() {
  const { state, ask, cancel, reset } = useAnswerStream();
  const [history, setHistory] = useState<HistoryMessage[]>([]);
  const [degraded, setDegraded] = useState(false);
  const busy = state.status === "streaming";
  const idle = state.status === "idle";

  const loadHistory = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/session/history");
      if (!res.ok) return;
      const body = (await res.json()) as { messages: HistoryMessage[] };
      setHistory(body.messages ?? []);
    } catch {
      // History is a convenience, never a precondition (D21). A failure here must not
      // stop someone asking a question, so it is swallowed rather than surfaced.
    }
  }, []);

  useEffect(() => {
    void loadHistory();
    // The status endpoint drives the degraded banner. A standing condition needs a
    // standing signal — discovering it only when a request fails means the user has
    // already typed a question and waited for nothing.
    void (async () => {
      try {
        const res = await fetch("/api/v1/status");
        if (!res.ok) return;
        const body = (await res.json()) as PublicStatus;
        setDegraded(body.status === "degraded" || !body.generation_enabled);
      } catch {
        /* the banner is advisory; its absence must never block the page */
      }
    })();
  }, [loadHistory]);

  // Refresh the transcript once an answer has landed, so the session record stays true.
  useEffect(() => {
    if (state.status === "done") void loadHistory();
  }, [state.status, loadHistory]);

  const retry = useCallback(() => {
    if (state.status !== "idle" && "question" in state) void ask(state.question);
  }, [state, ask]);

  return (
    <div className="space-y-8">
      {degraded && <DegradedBanner />}

      {idle ? (
        <section className="space-y-8 pt-6">
          <div className="space-y-3">
            <h1 className="text-3xl font-semibold tracking-tight text-balance">
              Answers from a medical reference, with the sources shown.
            </h1>
            <p className="max-w-[60ch] text-ink-muted">
              Every claim is drawn from a medical encyclopedia and cited. When the answer is
              not in the reference material, this assistant says so instead of guessing.
            </p>
          </div>

          <QuestionBox onSubmit={ask} onCancel={cancel} busy={busy} autoFocus />

          <div className="space-y-2">
            <h2 className="text-xs font-medium tracking-wide text-ink-muted uppercase">
              Try one of these
            </h2>
            <ul className="flex flex-wrap gap-2">
              {EXAMPLES.map((q) => (
                <li key={q}>
                  <button
                    onClick={() => ask(q)}
                    className="rounded-full border border-line bg-surface-raised px-3 py-1.5 text-sm text-ink-muted transition-colors hover:border-line-strong hover:text-ink"
                  >
                    {q}
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <HistoryPanel messages={history} onReask={ask} />
          <DataControlsRow onDeleted={() => setHistory([])} />
        </section>
      ) : (
        <section className="space-y-6">
          <h1 className="text-xl font-medium text-balance">{state.question}</h1>

          {state.status === "streaming" && (
            <StreamingAnswer
              citations={state.citations}
              sourcesSeen={state.sourcesSeen}
              text={state.text}
            />
          )}

          {state.status === "done" && <AnswerCard answer={state.answer} />}

          {state.status === "cancelled" && (
            <div className="space-y-3">
              {state.text && (
                <p className="answer-prose whitespace-pre-wrap text-ink">{state.text}</p>
              )}
              <p className="text-sm text-ink-muted">
                Stopped. This answer is incomplete
                {state.text ? " and should not be relied on" : ""}.
              </p>
              <Button variant="outline" size="sm" onClick={retry}>
                Ask again
              </Button>
            </div>
          )}

          {state.status === "error" && <ErrorState problem={state.problem} onRetry={retry} />}

          <div className="space-y-3 border-t border-line pt-6">
            <QuestionBox onSubmit={ask} onCancel={cancel} busy={busy} />
            {!busy && (
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="ghost" size="sm" onClick={reset}>
                  Start over
                </Button>
                {state.status === "done" && (
                  <Button variant="ghost" size="sm" onClick={retry}>
                    Ask again
                  </Button>
                )}
              </div>
            )}
          </div>

          <HistoryPanel messages={history} onReask={ask} />
          <DataControlsRow onDeleted={() => setHistory([])} />
        </section>
      )}
    </div>
  );
}
