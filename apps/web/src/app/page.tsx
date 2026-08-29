"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown } from "lucide-react";
import type { Answer } from "@/lib/contract";
import { AnswerCard } from "@/components/answer/answer-card";
import { DataControlsRow } from "@/components/chat/data-controls-row";
import { DegradedBanner, ErrorState } from "@/components/chat/error-state";
import { HistoryPanel, type HistoryMessage } from "@/components/chat/history-panel";
import { CopyAnswer } from "@/components/chat/copy-answer";
import { QuestionBox } from "@/components/chat/question-box";
import { SavePdf } from "@/components/chat/save-pdf";
import { StreamingAnswer } from "@/components/chat/streaming-answer";
import { Button } from "@/components/ui/button";
import type { PublicStatus } from "@/lib/contract";
import { useAnswerStream } from "@/lib/use-answer-stream";
import { useStickToBottom } from "@/lib/use-stick-to-bottom";
import { useConversationsContext } from "@/lib/conversations-context";

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
  const convos = useConversationsContext();

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

  // Follows the answer while it streams, and lets go the moment the reader scrolls
  // up. `state` is the dependency rather than `state.text` so the jump also happens
  // when sources land and when the terminal event replaces the streamed text.
  const { endRef, stuck, jumpToLatest } = useStickToBottom(busy, state);

  // A print requested from the sidebar. Held in a ref rather than state because it is
  // a one-shot instruction, not something the UI renders — putting it in state would
  // cause a re-render for a value nothing displays.
  const printWhenLoaded = useRef<string | null>(null);
  useEffect(() => {
    const onRequest = (e: Event) => {
      printWhenLoaded.current = (e as CustomEvent<string>).detail;
    };
    window.addEventListener("medbot:print-conversation", onRequest);
    return () => window.removeEventListener("medbot:print-conversation", onRequest);
  }, []);

  /** Returns how many turns the server reported, so a caller can tell "not yet" from
   *  "nothing to show" — the two look identical from the outside and mean opposite things. */
  const loadHistory = useCallback(async (): Promise<number> => {
    try {
      const res = await fetch("/api/v1/session/history");
      if (!res.ok) return 0;
      const body = (await res.json()) as { messages: HistoryMessage[] };
      setHistory(body.messages ?? []);
      return (body.messages ?? []).length;
    } catch {
      // History is a convenience, never a precondition (D21). A failure here must not
      // stop someone asking a question, so it is swallowed rather than surfaced.
      return 0;
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
  //
  // WITH A RETRY, because a single fetch RACES THE SERVER. `done` is emitted to the client
  // from inside the stream, and `record_turn` runs afterwards in postflight — deliberately,
  // since persistence is a side effect of answering and never a precondition for it (D21).
  // So the client can, and does, ask for the transcript microseconds before the turn is
  // committed, get the PREVIOUS state back, and then never look again: the answer on screen
  // is simply missing from "Earlier in this session" until something else triggers a reload.
  //
  // Proven rather than assumed: history returned `messages: []` for session 379012f0 while
  // Postgres held two rows for that exact session, written moments later.
  //
  // Bounded and self-terminating — it stops the moment the turn appears, and after three
  // tries regardless. Never a spinner: a transcript that fills in a beat late is invisible,
  // whereas blocking the UI on a record that is explicitly optional would be the wrong
  // trade entirely.
  useEffect(() => {
    if (state.status !== "done") return;
    let cancelled = false;
    void (async () => {
      for (const delay of [0, 250, 750]) {
        if (cancelled) return;
        if (delay) await new Promise((r) => setTimeout(r, delay));
        const seen = await loadHistory();
        if (cancelled || seen > 0) return;
      }
    })();
    return () => {
      cancelled = true;
    };
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

  /**
   * Load the transcript for whichever thread the sidebar selected.
   *
   * The sidebar moved into the layout (F1), so it can no longer call a handler on this
   * surface — it sets `activeId` on the shared context and nothing more. Reacting to that
   * id here is what keeps the list and the transcript in agreement, and it means ANY future
   * way of changing threads (a command palette, a deep link) gets the same behaviour for
   * free rather than needing its own wiring.
   */
  useEffect(() => {
    const id = convos.activeId;
    if (!id) return;
    // Guards a fast switch A -> B: without it, a slow response for A can land after B's and
    // leave the reader looking at B's title above A's messages.
    let stale = false;
    void (async () => {
      const msgs = (await convos.messages(id)) as HistoryMessage[];
      if (stale) return;
      setHistory(msgs);
      reset();
      // Only after this thread's messages are on screen. Two frames, not one: the first
      // commits React's update, the second lets the browser lay it out. print() before
      // layout captures a half-rendered page.
      if (printWhenLoaded.current === id) {
        printWhenLoaded.current = null;
        requestAnimationFrame(() => requestAnimationFrame(() => window.print()));
      }
    })();
    return () => {
      stale = true;
    };
  }, [convos.activeId, convos.messages, reset]);

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

          {/* The front door, and it is the EMPTY STATE rather than a separate landing route.
              A marketing page before the product puts a click in front of the core value and
              contradicts D24's anonymous-first sequencing — you can ask a question here
              without an account, so nothing should stand between you and the box.

              What it promises is what the system actually does: these three cards are the
              four answer kinds stated in plain language. Naming the REFUSALS up front is the
              point — someone who arrives wanting a dose should learn the boundary before
              they type, not after. A product that oversells and then declines feels broken;
              one that says what it will not do and then does exactly that reads as careful. */}
          <ul className="grid gap-3 sm:grid-cols-3">
            {[
              {
                title: "Cited, or nothing",
                body: "Every grounded answer names the source and page it came from, so you can check it rather than trust it.",
              },
              {
                title: "Says when it does not know",
                body: "If the reference material does not cover your question, it says so. It does not fill the gap with something plausible.",
              },
              {
                title: "No diagnosis, no dosages",
                body: "It will not tell you what you have or how much to take. For an emergency it points you to emergency services instead.",
              },
            ].map((c) => (
              <li
                key={c.title}
                className="rounded-lg border border-line bg-surface-raised p-3.5"
              >
                <h2 className="text-sm font-medium text-ink">{c.title}</h2>
                <p className="mt-1 text-sm text-ink-muted">{c.body}</p>
              </li>
            ))}
          </ul>

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
          {/* Chronological order: earlier turns, then the one being answered now. It used
              to render the live answer first with the transcript below it, which reads as
              a form that keeps a log rather than as a conversation. Nothing about the
              transcript's CONTENT changed — see HistoryPanel on why past turns must not
              borrow the answer-kind treatments. */}
          <HistoryPanel messages={history} onReask={ask} />

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

          <div className="space-y-3 border-t border-line pt-6" data-print="hide">
            <QuestionBox onSubmit={ask} onCancel={cancel} busy={busy} />
            {!busy && (
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="ghost" size="sm" onClick={reset}>
                  Start over
                </Button>
                {state.status === "done" && (
                  <>
                    <Button variant="ghost" size="sm" onClick={retry}>
                      Ask again
                    </Button>
                    <CopyAnswer answer={state.answer} />
                    <SavePdf />
                  </>
                )}
              </div>
            )}
          </div>

          <DataControlsRow onDeleted={() => setHistory([])} />

          {/* Scroll anchor. Empty and aria-hidden: it is a POSITION, not content, and a
              screen reader announcing a stray element at the end of every answer would be
              noise on the surface that most needs to stay quiet. */}
          <div ref={endRef} aria-hidden="true" />
        </section>
      )}

      {/* Jump-to-latest. Only while streaming AND only once the reader has actually
          scrolled away — a button offering to take you where you already are is clutter,
          and on the idle screen it would be meaningless. */}
      {busy && !stuck && (
        <button
          onClick={jumpToLatest}
          className="fixed bottom-6 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-line bg-surface-raised px-3 py-1.5 text-sm text-ink shadow-[var(--shadow-md)]"
          style={{ zIndex: "var(--z-sticky)" }}
        >
          <ArrowDown className="size-3.5" aria-hidden="true" />
          Jump to latest
        </button>
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
