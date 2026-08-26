"use client";

import { useCallback, useEffect, useState } from "react";
import type { Answer } from "@/lib/contract";
import { AnswerCard } from "@/components/answer/answer-card";
import { DataControlsRow } from "@/components/chat/data-controls-row";
import { DegradedBanner, ErrorState } from "@/components/chat/error-state";
import { AccountControls } from "@/components/auth/account-controls";
import { ConversationSidebar } from "@/components/chat/conversation-sidebar";
import { HistoryPanel, type HistoryMessage } from "@/components/chat/history-panel";
import { QuestionBox } from "@/components/chat/question-box";
import { StreamingAnswer } from "@/components/chat/streaming-answer";
import { Button } from "@/components/ui/button";
import type { PublicStatus } from "@/lib/contract";
import { useAnswerStream } from "@/lib/use-answer-stream";
import { useConversations } from "@/lib/use-conversations";

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
  const { state, ask: askStream, cancel, reset } = useAnswerStream();
  const convos = useConversations();
  const accountsEnabled = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);

  // Every ask carries the selected thread, so an answer lands where the user is looking.
  // The id is verified server-side before anything is written (serving.preflight), so this
  // is a routing hint, not a trust boundary.
  const ask = useCallback(
    (question: string) => askStream(question, convos.activeId),
    [askStream, convos.activeId],
  );
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

  // A11y (S10.12): announce that an answer ARRIVED.
  //
  // Found by an audit: the only live region was inside the streaming view, so it announced
  // progress and then unmounted. A cache hit has no streaming phase at all, which meant a
  // screen-reader user was told nothing — the page simply changed under them. This region
  // persists across states and reports the outcome and its kind.
  //
  // Emergencies are deliberately EXCLUDED: the emergency card is role="alert" and already
  // announces assertively. Announcing here as well would say it twice.
  const announcement = (() => {
    if (state.status === "streaming") {
      return state.sourcesSeen ? "Sources found, writing the answer" : "Searching the reference corpus";
    }
    if (state.status === "done") return describe(state.answer);
    if (state.status === "cancelled") return "Stopped. The answer is incomplete.";
    if (state.status === "error") return `Request failed. ${state.problem.title}.`;
    return "";
  })();

  const selectConversation = useCallback(
    async (id: string) => {
      convos.setActiveId(id);
      setHistory((await convos.messages(id)) as HistoryMessage[]);
      reset();
    },
    [convos, reset],
  );

  const retry = useCallback(() => {
    if (state.status !== "idle" && "question" in state) void ask(state.question);
  }, [state, ask]);

  return (
    <div className="space-y-8">
      {/* One persistent polite live region for the whole surface. Polite, never assertive:
          assertive interrupts whatever the user is currently reading, which is justified
          for a medical emergency and for nothing else here. */}
      <span className="sr-only" role="status" aria-live="polite">
        {announcement}
      </span>

      {degraded && <DegradedBanner />}

      {convos.enabled && !convos.loading && (
        <aside className="rounded-lg border border-line bg-surface-raised p-3">
          <ConversationSidebar
            items={convos.items}
            activeId={convos.activeId}
            signedIn={convos.signedIn}
            onSelect={(id) => void selectConversation(id)}
            onCreate={() => {
              void convos.create();
              setHistory([]);
              reset();
            }}
            onRename={(id, title) => void convos.rename(id, title)}
            onDelete={(id) => {
              void convos.remove(id);
              setHistory([]);
            }}
          />
          <div className="mt-3 flex justify-end border-t border-line pt-2">
            <AccountControls enabled={accountsEnabled} onSignedIn={() => void convos.claim()} />
          </div>
        </aside>
      )}


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

/** What a screen reader should hear when an answer lands. Says the KIND, because "answer
 *  ready" is useless if the answer is actually a refusal. */
function describe(answer: Answer): string {
  switch (answer.kind) {
    case "grounded": {
      const n = answer.citations.length;
      return `Answer ready, with ${n} source${n === 1 ? "" : "s"}.`;
    }
    case "no_answer":
      return "No answer: this topic is not in the reference material.";
    case "degraded":
      return "Limited service: a new answer could not be generated.";
    case "refused":
      // The emergency card announces itself via role="alert"; do not duplicate it.
      return answer.refusal_category === "emergency" ||
        answer.refusal_category === "self_harm" ||
        answer.refusal_category === "harmful"
        ? ""
        : "This question needs a clinician. The assistant declined to answer it.";
  }
}
