"use client";

import { useCallback, useReducer, useRef } from "react";
import type {
  Answer,
  Citation,
  DoneEvent,
  ProblemDetail,
  SourcesEvent,
  TokenEvent,
} from "@/lib/contract";
import { finalText } from "@/lib/contract";
import { readSSE } from "@/lib/sse";

/**
 * The streaming state machine (D26).
 *
 * A discriminated union rather than a bag of booleans. `isLoading && !error && text` is how
 * a chat UI ends up rendering a spinner over a finished answer, or an empty answer frame
 * during a refusal: the illegal combinations exist and eventually occur. Here they cannot
 * be constructed, which is the same instinct that made AnswerKind an enum in the API
 * instead of a set of flags.
 */
export type StreamState =
  | { status: "idle" }
  | {
      status: "streaming";
      question: string;
      /** Arrives BEFORE any token by backend contract — the UI paints it immediately. */
      citations: Citation[];
      sourcesSeen: boolean;
      text: string;
      ttftMs: number | null;
    }
  | { status: "done"; question: string; answer: Answer }
  | { status: "cancelled"; question: string; text: string }
  | { status: "error"; question: string; problem: ProblemDetail };

type Action =
  | { type: "submit"; question: string }
  | { type: "sources"; citations: Citation[] }
  | { type: "token"; text: string; elapsedMs: number }
  | { type: "done"; event: DoneEvent }
  | { type: "cancel" }
  | { type: "error"; problem: ProblemDetail }
  | { type: "reset" };

const GENERIC_PROBLEM: ProblemDetail = {
  type: "about:blank",
  title: "Request failed",
  status: 0,
  detail: "Something went wrong. Please try again.",
};

/** DoneEvent -> Answer. The terminal event carries everything the non-streaming endpoint
 *  would have returned; the two fields it omits are not knowable from a stream. */
function toAnswer(event: DoneEvent, streamed: string): Answer {
  return {
    kind: event.kind,
    // AUTHORITATIVE (S10.2b): the output guardrail can cut a stream off mid-answer, so a
    // non-grounded terminal event REPLACES what was streamed rather than appending to it.
    // Without this a retracted dosage stays on screen.
    text: finalText(event, streamed),
    citations: event.citations,
    confidence: null,
    model_id: event.model_id,
    usage: event.usage,
    timings: event.timings,
    cache_hit: false,
    refusal_category: event.refusal_category,
  };
}

function reducer(state: StreamState, action: Action): StreamState {
  switch (action.type) {
    case "submit":
      return {
        status: "streaming",
        question: action.question,
        citations: [],
        sourcesSeen: false,
        text: "",
        ttftMs: null,
      };
    case "sources":
      if (state.status !== "streaming") return state;
      return { ...state, citations: action.citations, sourcesSeen: true };
    case "token":
      if (state.status !== "streaming") return state;
      return {
        ...state,
        text: state.text + action.text,
        ttftMs: state.ttftMs ?? action.elapsedMs,
      };
    case "done":
      if (state.status !== "streaming") return state;
      return {
        status: "done",
        question: state.question,
        answer: toAnswer(action.event, state.text),
      };
    case "cancel":
      if (state.status !== "streaming") return state;
      return { status: "cancelled", question: state.question, text: state.text };
    case "error":
      // Reachable from streaming OR from a pre-stream HTTP failure, so no status guard.
      return {
        status: "error",
        question: state.status === "idle" ? "" : (state as { question: string }).question,
        problem: action.problem,
      };
    case "reset":
      return { status: "idle" };
  }
}

export function useAnswerStream() {
  const [state, dispatch] = useReducer(reducer, { status: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  const cancel = useCallback(() => {
    // Aborting the fetch closes the connection, which the BFF passes upstream, which lets
    // the API abort the provider stream. That chain is what makes Stop stop the SPEND and
    // not merely hide the text (D20).
    abortRef.current?.abort();
    abortRef.current = null;
    dispatch({ type: "cancel" });
  }, []);

  const ask = useCallback(async (question: string) => {
    const trimmed = question.trim();
    if (!trimmed) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    dispatch({ type: "submit", question: trimmed });
    const startedAt = performance.now();

    try {
      const res = await fetch("/api/v1/query/stream", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: trimmed, stream: true }),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        // The BFF emits RFC 7807 for upstream failures too, so one parser covers both.
        const problem = await res
          .json()
          .catch(() => ({ ...GENERIC_PROBLEM, status: res.status }));
        dispatch({ type: "error", problem: problem as ProblemDetail });
        return;
      }

      for await (const frame of readSSE(res.body)) {
        switch (frame.event) {
          case "sources":
            dispatch({
              type: "sources",
              citations: (JSON.parse(frame.data) as SourcesEvent).citations,
            });
            break;
          case "token":
            dispatch({
              type: "token",
              text: (JSON.parse(frame.data) as TokenEvent).text,
              elapsedMs: Math.round(performance.now() - startedAt),
            });
            break;
          case "done":
            dispatch({ type: "done", event: JSON.parse(frame.data) as DoneEvent });
            break;
          case "error":
            dispatch({
              type: "error",
              problem: (JSON.parse(frame.data) as { problem: ProblemDetail }).problem,
            });
            break;
        }
      }
    } catch (e) {
      // A user-initiated abort already produced the `cancelled` state; treating it as an
      // error would overwrite that with a scary message for something they chose to do.
      if ((e as Error).name === "AbortError") return;
      dispatch({ type: "error", problem: GENERIC_PROBLEM });
    } finally {
      abortRef.current = null;
    }
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    dispatch({ type: "reset" });
  }, []);

  return { state, ask, cancel, reset };
}
