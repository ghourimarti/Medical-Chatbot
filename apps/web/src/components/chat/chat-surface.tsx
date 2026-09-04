"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowDown } from "lucide-react";
import type { Answer } from "@/lib/contract";
import { AnswerCard } from "@/components/answer/answer-card";
import { DataControlsRow } from "@/components/chat/data-controls-row";
import { DegradedBanner, ErrorState } from "@/components/chat/error-state";
import { Transcript, type HistoryMessage } from "@/components/chat/transcript";
import { CopyAnswer } from "@/components/chat/copy-answer";
import { EmptyStateArt } from "@/components/chat/empty-state-art";
import { QuestionBox } from "@/components/chat/question-box";
import { DownloadPdf } from "@/components/chat/download-pdf";
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

/**
 * The chat surface. Rendered by BOTH /chat and /chat/[id].
 *
 * `conversationId` comes from the URL when present. That is the whole point of the route:
 * conversation identity used to live only in React state, so refreshing the page lost
 * which thread you were in and the next question silently started a new one. A thread you
 * cannot link to or reload is not really a saved thread.
 */
export function ChatSurface({ conversationId }: { conversationId?: string }) {
  const { state, ask: askStream, cancel, reset } = useAnswerStream();
  const convos = useConversationsContext();
  const router = useRouter();

  /**
   * Every ask happens INSIDE a conversation — one is created if there is not one yet.
   *
   * Without this, asking with no thread selected wrote to the session instead, and the
   * transcript then fell back to `/session/history`, which spans EVERY conversation in the
   * session. Opening the app and typing a question dropped you into a page showing all your
   * previous threads at once — reported as "it navigates me towards the old conversation".
   *
   * Creating implicitly is also what the category does: you never pick a thread before
   * typing, you type and a thread appears. The alternative — refusing to answer until a
   * thread exists — would put a click in front of the first question, which is the one
   * moment the product cannot afford friction (D24).
   *
   * `enabled` is respected: with no database configured there are no conversations, and the
   * session genuinely IS the thread. That path is unchanged.
   *
   * The id is verified server-side before anything is written (serving.preflight), so it is
   * a routing hint, not a trust boundary.
   */
  // Set while an ask is creating its OWN thread, so the activeId effect below can tell
  // "the user picked a different conversation" from "we just made one to answer into".
  const creatingForAsk = useRef(false);

  // The URL is the source of truth for WHICH thread is open. Without this the id in the
  // address bar and the thread actually loaded could disagree after a refresh or a
  // back-navigation — the address bar would say one thing and the transcript show another.
  useEffect(() => {
    if (conversationId && conversationId !== convos.activeId) {
      convos.setActiveId(conversationId);
    }
  }, [conversationId, convos]);



  const ask = useCallback(
    async (question: string) => {
      let id = convos.activeId;
      if (!id && convos.enabled) {
        creatingForAsk.current = true;
        const created = await convos.create();
        id = created?.id ?? null;
        // Give the new thread its own URL — via the HISTORY API, not the Next router.
        //
        // router.replace() triggers a real navigation: it remounted this component and
        // destroyed the streaming state of the very request being started, so the answer
        // never appeared as a live answer at all (it turned up later in the transcript,
        // which looked like the answer had been "moved" somewhere else).
        //
        // replaceState changes the address bar and nothing else. React keeps rendering,
        // the stream survives, and a refresh still lands on /chat/<id> and loads the
        // thread — which is the entire point of the route.
        if (id) window.history.replaceState(null, "", `/chat/${id}`);
      }
      await askStream(question, id);
    },
    [askStream, convos],
  );
  const [history, setHistory] = useState<HistoryMessage[]>([]);
  const [degraded, setDegraded] = useState(false);
  const busy = state.status === "streaming";
  const idle = state.status === "idle";
  // Is there a conversation on screen? Drives whether this surface reads as a front
  // door or as a thread you are already in.
  const hasThread = history.length > 0;

  /**
   * The transcript MINUS the turn currently on screen.
   *
   * `loadHistory` refetches after every answer (it has to — that is what makes the record
   * true), so the moment an answer lands the turn exists in BOTH places: once in the
   * transcript and once as the live AnswerCard below it. The page then showed the same
   * question and the same answer twice, one directly above the other.
   *
   * Trimmed by MATCHING rather than by slicing a fixed count: an assistant turn is not
   * guaranteed to have been recorded yet when this runs, so "drop the last two" would
   * sometimes eat a previous turn instead.
   */
  const priorTurns = useMemo(() => {
    if (idle) return history;
    const question = "question" in state ? state.question : null;
    if (!question) return history;
    // Reverse scan rather than findLastIndex: that method needs lib es2023, and raising
    // the whole project's target to shave three lines here would be the wrong trade.
    let last = -1;
    for (let i = history.length - 1; i >= 0; i--) {
      // Bound to a local first: noUncheckedIndexedAccess types history[i] as possibly
      // undefined, and it is right to — the loop bound is the only thing saying otherwise.
      const turn = history[i];
      if (turn && turn.role === "user" && turn.content === question) {
        last = i;
        break;
      }
    }
    return last === -1 ? history : history.slice(0, last);
  }, [history, idle, state]);

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

  /**
   * Reload the transcript for WHATEVER IS ON SCREEN.
   *
   * SCOPED TO THE ACTIVE CONVERSATION when there is one. It used to always read
   * `/api/v1/session/history`, which returns every message in the SESSION — across all
   * threads. Selecting a thread loaded the right messages, and then the very next answer
   * called this and replaced them with the whole session, so a brand-new conversation
   * filled up with turns from every earlier one. Reported as "the chat begins in the same
   * window where we started previously", which is exactly what it looked like.
   *
   * The session endpoint remains the correct source for the anonymous single-thread path,
   * where there IS no conversation and the session genuinely is the thread.
   *
   * Returns how many turns the server reported, so a caller can tell "not yet" from
   * "nothing to show" — the two look identical from outside and mean opposite things.
   */
  const loadHistory = useCallback(async (): Promise<number> => {
    const id = convos.activeId;
    try {
      if (id) {
        const msgs = (await convos.messages(id)) as HistoryMessage[];
        setHistory(msgs);
        return msgs.length;
      }
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
  }, [convos]);

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
      // DO NOT reset when this thread was created BY the ask that is starting right now.
      //
      // create() sets activeId, which fires this effect, which called reset() — clearing
      // the very question being submitted a moment before askStream dispatched it. The
      // answer then never appeared at all. reset() is right when a user SELECTS a
      // different conversation and wrong when we quietly made one to answer into, and the
      // effect cannot tell those apart from activeId alone.
      if (creatingForAsk.current) {
        creatingForAsk.current = false;
      } else {
        reset();
      }
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
        <section className="space-y-9 pt-8">
          {/* THE LANDING IS THE EMPTY STATE, and only that.
              Opening a saved conversation calls reset(), which returns the surface to
              `idle` — so this branch also renders when a thread is selected from the
              sidebar. It used to show the headline, the three cards and the example chips
              regardless, pushing the actual conversation below the fold. Clicking a thread
              therefore looked like it had done nothing: the transcript WAS there, under a
              screenful of marketing.
              A thread with turns in it is a conversation. Show the conversation. */}
          {hasThread ? (
            <Transcript messages={history} onReask={ask} />
          ) : (
            <>
          <div className="space-y-3">
            {/* The illustration sits ABOVE the headline and is hidden on small screens: on
                a phone the composer must stay above the fold, and art that pushes the one
                control people came for off-screen is worse than no art. */}
            <EmptyStateArt className="mb-2 hidden h-28 w-auto sm:block" />
            {/* 31px -> 40px and tighter tracking. The old headline was only ~2x the body
                text, which is not a hierarchy, it is a slightly larger paragraph. */}
            <h1 className="text-[2.5rem] leading-[1.15] font-semibold tracking-[-0.02em] text-balance">
              Answers from a medical reference,{" "}
              {/* The one place the accent appears at display size. A product whose entire
                  claim is "we show you the sources" should say so in its own colour. */}
              <span className="text-accent">with the sources shown.</span>
            </h1>
            <p className="max-w-[58ch] text-[1.0625rem] leading-relaxed text-ink-muted">
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
          <ul className="grid gap-3.5 sm:grid-cols-3">
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
                className="lift rounded-xl border border-line bg-surface-raised p-5"
              >
                <h2 className="text-[0.9375rem] font-semibold text-ink">{c.title}</h2>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{c.body}</p>
              </li>
            ))}
          </ul>
            </>
          )}

          {/* The composer is common to both states — it is the point of the page. */}
          {/* Suggestions belong to an EMPTY thread. Offering "What is cirrhosis?" under a
              conversation already six turns deep is noise, and it competes with the
              follow-up the reader is actually about to type. */}
          {!hasThread && (
          <div className="space-y-2">
            <h2 className="text-[0.6875rem] font-semibold tracking-[0.08em] text-ink-muted uppercase">
              Try one of these
            </h2>
            <ul className="flex flex-wrap gap-2">
              {EXAMPLES.map((q) => (
                <li key={q}>
                  <button
                    onClick={() => ask(q)}
                    className="lift rounded-full border border-line bg-surface-raised px-4 py-2.5 text-sm text-ink-muted hover:border-accent/40 hover:text-ink"
                  >
                    {q}
                  </button>
                </li>
              ))}
            </ul>
          </div>
          )}

          <DataControlsRow onDeleted={() => setHistory([])} />
        </section>
      ) : (
        <section className="space-y-6">
          {/* Chronological order: earlier turns, then the one being answered now. It used
              to render the live answer first with the transcript below it, which reads as
              a form that keeps a log rather than as a conversation. Nothing about the
              transcript's CONTENT changed — see HistoryPanel on why past turns must not
              borrow the answer-kind treatments. */}
          <Transcript messages={priorTurns} onReask={ask} />

          {/* The question you just asked is a TURN in the conversation, not the page's
              title. Rendering it as an <h1> above the answer is what made the surface
              read as a document about one question rather than a thread you are in — and
              it broke the visual rhythm the transcript above establishes, so the current
              turn looked like a different kind of thing from every turn before it. */}
          <div className="turn-enter flex justify-end">
            <div className="max-w-[85%] rounded-3xl rounded-br-lg bg-surface-sunken px-4 py-2.5">
              <h1 className="whitespace-pre-wrap text-[0.95rem] leading-relaxed font-normal text-ink">
                {state.question}
              </h1>
            </div>
          </div>

          {state.status === "streaming" && (
            <StreamingAnswer
              citations={state.citations}
              sourcesSeen={state.sourcesSeen}
              text={state.text}
            />
          )}

          {state.status === "done" && (
            <div className="turn-enter-delayed">
              <AnswerCard answer={state.answer} />
            </div>
          )}

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

          <div className="space-y-3 pt-4" data-print="hide">
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
                    {/* A real file, and the print route kept beside it: printing is
                        still the better choice for someone who wants paper. */}
                    <DownloadPdf answer={state.answer} question={state.question} />
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

      {/* THE COMPOSER, RENDERED ONCE.
          It used to appear inside BOTH branches of the idle/answered ternary. Those are
          different parents, so React could not keep one instance across the swap — even
          with a shared key, which only preserves siblings. Every transition unmounted the
          box and mounted a new one, discarding whatever had been typed: click "New chat",
          start typing, and the reset that follows ate your first characters while leaving
          Ask disabled.
          One instance, one parent, no remount. The surrounding layout differs between the
          two states, which is why it was duplicated in the first place — but that is a
          reason to move the box, not to have two of them. */}
      <div className="space-y-3 pt-2" data-print="hide">
        <QuestionBox onSubmit={ask} onCancel={cancel} busy={busy} autoFocus={idle} />
      </div>

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
