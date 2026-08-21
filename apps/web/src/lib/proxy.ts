import "server-only";
import { API_BASE_URL, UPSTREAM_TIMEOUT_MS } from "@/lib/env";

/**
 * The BFF forwarder (D23).
 *
 * ALLOWLIST, NOT PASSTHROUGH — the decision gate of this step. A catch-all that blindly
 * forwards /api/* would make the ENTIRE internal API reachable from the public internet
 * through the web tier, including /admin/kill-switch and /metrics. That would hand back
 * the very security posture the proxy was chosen to gain: in Phase 7/8 only this web tier
 * gets an ingress, and the API stays an internal service.
 *
 * Methods are pinned per route too, so a GET-only surface cannot be POSTed to.
 */
const ROUTES: Record<string, ReadonlySet<string>> = {
  "v1/status": new Set(["GET"]),
  "v1/query": new Set(["POST"]),
  "v1/query/stream": new Set(["POST"]),
  "v1/session/history": new Set(["GET"]),
  "v1/session/clear": new Set(["POST"]),
};

/** Headers we send upstream. `cookie` carries the httpOnly session; everything else the
 *  browser volunteers (origin, referer, user-agent, x-forwarded-*) is dropped rather than
 *  relayed — the API's IP-based rate limiting must key on OUR hop, not a spoofable header. */
const FORWARD_UP = ["content-type", "cookie", "accept"] as const;

/** Headers we return. `x-accel-buffering: no` must survive: it is what stops an ingress
 *  from buffering the SSE body and turning "streaming" into batch delivery. */
const FORWARD_DOWN = ["content-type", "cache-control", "x-accel-buffering"] as const;

export function isAllowed(path: string, method: string): boolean {
  // Reject traversal outright rather than relying on the allowlist to catch it. Defence in
  // depth: two independent reasons `v1/../admin/kill-switch` fails.
  if (path.includes("..") || path.startsWith("/")) return false;
  return ROUTES[path]?.has(method) ?? false;
}

async function fetchUpstream(
  request: Request,
  path: string,
  headers: Headers,
  body: string | undefined,
): Promise<Response> {
  return fetch(`${API_BASE_URL}/api/${path}`, {
    method: request.method,
    headers,
    body,
    // BUG CAUGHT IN REVIEW: these were two separate `signal` keys, so the object literal's
    // later spread silently overwrote the timeout and UPSTREAM_TIMEOUT_MS never applied.
    // AbortSignal.any fires on whichever comes first, which is what was always intended.
    //
    // The client half matters for cost: passing the browser's disconnect upstream is what
    // lets the API abort the provider stream and STOP PAYING when a user hits Stop (D20).
    signal: request.signal
      ? AbortSignal.any([request.signal, AbortSignal.timeout(UPSTREAM_TIMEOUT_MS)])
      : AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    redirect: "manual",
    cache: "no-store",
  });

}

export async function forward(request: Request, path: string): Promise<Response> {
  if (!isAllowed(path, request.method)) {
    // 404, not 403: a proxy that distinguishes "exists but forbidden" from "no such route"
    // tells a prober which internal endpoints are real.
    return Response.json(
      { type: "about:blank", title: "Not Found", status: 404, detail: "No such endpoint." },
      { status: 404 },
    );
  }

  const headers = new Headers();
  for (const name of FORWARD_UP) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  // Body is read to text rather than piped: these payloads are small JSON, and streaming a
  // REQUEST body through Node fetch needs `duplex: "half"` plus its own failure modes. The
  // RESPONSE is what has to stream, and that is handled below.
  const body = request.method === "POST" ? await request.text() : undefined;

  let upstream: Response;
  try {
    upstream = await fetchUpstream(request, path, headers, body);
  } catch (cause) {
    // An unreachable or timed-out API must surface as the SAME RFC 7807 shape the backend
    // itself emits, not a framework error page. The UI branches on `problem.status`; a bare
    // 500 HTML page would fall through every one of those branches into "unknown error".
    const timedOut = (cause as Error)?.name === "TimeoutError";
    return Response.json(
      {
        type: "https://p5-medical-chatbot/problems/upstream-unavailable",
        title: timedOut ? "Upstream Timeout" : "Service Unavailable",
        status: 503,
        detail: "The assistant is temporarily unreachable. Please try again shortly.",
      },
      { status: 503, headers: { "content-type": "application/problem+json" } },
    );
  }

  const out = new Headers();
  for (const name of FORWARD_DOWN) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  // set-cookie can legitimately repeat (getSetCookie preserves that); a plain get() would
  // collapse them into one malformed header and silently break session continuity.
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);

  // upstream.body is a ReadableStream handed straight back — no await, no buffering.
  return new Response(upstream.body, { status: upstream.status, headers: out });
}
