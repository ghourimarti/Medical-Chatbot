/**
 * Minimal SSE reader over fetch's ReadableStream.
 *
 * Why not EventSource: it is GET-only and cannot send a JSON body, and the query endpoint
 * is a POST. fetch + a hand-rolled frame parser is the standard way to consume a POSTed
 * event stream, and it also gives us AbortController for real server-side cancellation.
 */
export interface SSEFrame {
  event: string;
  data: string;
}

export async function* readSSE(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SSEFrame, void, unknown> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      // stream:true keeps a multi-byte character split across two chunks intact — without
      // it, a UTF-8 codepoint straddling a chunk boundary decodes to a replacement char.
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseFrame(frame);
        if (parsed) yield parsed;
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    // Releasing the lock lets an aborted fetch tear the connection down promptly, which is
    // what propagates the cancel to the API and stops token spend.
    reader.releaseLock();
  }
}

function parseFrame(raw: string): SSEFrame | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}
