/**
 * Splits answer text into prose and citation markers (S10.7).
 *
 * The model is instructed to cite passage numbers as [1], [2]. Those markers are the only
 * link between a claim and its evidence, so rendering them correctly is a safety concern
 * rather than a formatting one.
 *
 * THE RULE THAT MATTERS: a marker referencing a source that does not exist — [5] when four
 * passages were retrieved — renders as PLAIN TEXT, never as a link. An LLM can emit a
 * citation number it was never given, and turning that into a clickable affordance would
 * manufacture provenance the system does not have. That is exactly the "uncited claim
 * rendered as sourced" failure the whole design is built to prevent.
 */

export type Segment =
  | { type: "text"; value: string }
  | { type: "cite"; value: string; index: number };

const MARKER = /\[(\d{1,2})\]/g;

export function parseCitations(text: string, citationCount: number): Segment[] {
  const segments: Segment[] = [];
  let cursor = 0;

  for (const match of text.matchAll(MARKER)) {
    const at = match.index;
    const raw = match[0];
    const n = Number(match[1]);

    if (at > cursor) segments.push({ type: "text", value: text.slice(cursor, at) });

    // 1-based and within range, or it is not a citation we can stand behind.
    if (n >= 1 && n <= citationCount) {
      segments.push({ type: "cite", value: raw, index: n - 1 });
    } else {
      segments.push({ type: "text", value: raw });
    }
    cursor = at + raw.length;
  }

  if (cursor < text.length) segments.push({ type: "text", value: text.slice(cursor) });
  return segments;
}

/** Which citation indices the answer actually referenced. Evidence the prose never cites
 *  is still shown — it was retrieved and fed to the model — but marked as uncited, because
 *  quietly hiding it would misrepresent what the answer was built from. */
export function referencedIndices(text: string, citationCount: number): Set<number> {
  return new Set(
    parseCitations(text, citationCount)
      .filter((s): s is Extract<Segment, { type: "cite" }> => s.type === "cite")
      .map((s) => s.index),
  );
}
