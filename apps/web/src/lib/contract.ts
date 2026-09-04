/**
 * TypeScript mirror of packages/core/src/medcore/schema.py.
 *
 * Hand-written on purpose: it is small, and a generated client would hide the one thing
 * that matters most here — the invariants. They are restated as comments so a reader of
 * the frontend learns the rules without opening the Python.
 */

export type AnswerKind = "grounded" | "no_answer" | "refused" | "degraded";

/** Which safety rule fired. Only ever present when kind === "refused" (S10.2a). */
export type RefusalCategory =
  | "emergency"
  | "self_harm"
  | "harmful"
  | "dosage"
  | "diagnosis"
  | "prescription"
  | "medication_change"
  | "injection";

export interface Citation {
  chunk_id: string;
  source: string;
  page: number | null;
  snippet: string;
  score: number;
}

export interface Usage {
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
}

export interface StageTimings {
  condense_ms: number | null;
  embed_ms: number | null;
  retrieve_ms: number | null;
  rerank_ms: number | null;
  generate_ms: number | null;
  ttft_ms: number | null;
  total_ms: number;
}

export interface Answer {
  kind: AnswerKind;
  text: string;
  /** A grounded answer ALWAYS has >= 1; a refusal ALWAYS has 0. Enforced server-side. */
  citations: Citation[];
  confidence: number | null;
  model_id: string | null;
  usage: Usage;
  timings: StageTimings;
  cache_hit: boolean;
  refusal_category: RefusalCategory | null;
  /** Which chain leg served this (`local-sglang`, `groq`). NOT derivable from
   *  model_id: every venue can serve the same model, and Groq serves one named
   *  `openai/gpt-oss-20b`. Null when no failover chain is configured. */
  venue: string | null;
}

/** SSE: exactly one `sources`, then zero or more `token`, then exactly one `done` — or an
 *  `error` carrying an RFC 7807 body if the failure happens after bytes are on the wire. */
export interface SourcesEvent {
  citations: Citation[];
}
export interface TokenEvent {
  text: string;
}
export interface DoneEvent {
  kind: AnswerKind;
  text: string;
  citations: Citation[];
  model_id: string | null;
  usage: Usage;
  timings: StageTimings;
  refusal_category: RefusalCategory | null;
  /** Which chain leg served this (`local-sglang`, `groq`). NOT derivable from
   *  model_id: every venue can serve the same model, and Groq serves one named
   *  `openai/gpt-oss-20b`. Null when no failover chain is configured. */
  venue: string | null;
}
export interface ProblemDetail {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance?: string | null;
}
export interface ErrorEvent {
  problem: ProblemDetail;
}

export interface PublicStatus {
  status: "ok" | "degraded" | "unavailable";
  checks: { vector_store: boolean; embedder: boolean };
  generation_enabled: boolean;
  corpus: { version: string; index_version: string };
}

/**
 * S10.2b CONTRACT: `done.text` is AUTHORITATIVE.
 *
 * The output guardrail can cut a stream off mid-answer — a model that begins emitting a
 * dose is stopped and the terminal event becomes a refusal. Any renderer MUST therefore
 * discard accumulated tokens whenever done.kind !== "grounded", or a retracted dose stays
 * on screen. This helper exists so that rule is applied in one place, not remembered.
 */
export function finalText(done: DoneEvent, streamed: string): string {
  return done.kind === "grounded" ? streamed || done.text : done.text;
}

/** A saved thread (S20/S21). Owned by a user when signed in, otherwise by the anonymous
 *  session — which is why the sidebar works with no account at all. */
export interface Conversation {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  /** S22. Server-side pin. Optional so a client built against an older API still
   *  type-checks — the sidebar treats a missing value as unpinned. */
  pinned?: boolean;
  /** False while owned only by an anonymous session. The UI uses this to explain that
   *  signing in will keep the thread rather than silently discarding it. */
  claimed: boolean;
}

export interface ConversationList {
  /** False when no database is configured: the feature is absent, not broken. */
  enabled: boolean;
  signed_in: boolean;
  conversations: Conversation[];
}
