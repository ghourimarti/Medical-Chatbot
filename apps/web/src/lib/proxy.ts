import "server-only";
import { API_BASE_URL, UPSTREAM_TIMEOUT_MS } from "@/lib/env";

/**
 * The BFF forwarder (D23).
 *
 * ALLOWLIST, NOT PASSTHROUGH. A catch-all that blindly forwarded /api/* would make the
 * ENTIRE internal API reachable from the public internet through the web tier, including
 * /admin/kill-switch and /metrics. In Phase 7/8 only this web tier gets an ingress and the
 * API stays an internal service, so the allowlist is the boundary.
 *
 * Methods are pinned per route too, so a GET-only surface cannot be POSTed to.
 */

/** A UUID path segment. Anything else in that position is not a route we serve. */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Route patterns. `:uuid` matches exactly one UUID segment and nothing else.
 *
 * S21 added the conversation routes, which are the first with a dynamic segment. Matching
 * is done SEGMENT BY SEGMENT rather than with a loose regex over the whole path: a pattern
 * like /^v1\/conversations\/.+$/ would happily match `v1/conversations/../../admin/status`
 * before any normalisation, which is precisely the class of bug an allowlist exists to
 * prevent.
 */
const ROUTES: { pattern: string; methods: ReadonlySet<string> }[] = [
  { pattern: "v1/status", methods: new Set(["GET"]) },
  { pattern: "v1/query", methods: new Set(["POST"]) },
  { pattern: "v1/query/stream", methods: new Set(["POST"]) },
  { pattern: "v1/session/history", methods: new Set(["GET"]) },
  { pattern: "v1/session/clear", methods: new Set(["POST"]) },
  // S21 — conversations.
  { pattern: "v1/conversations", methods: new Set(["GET", "POST"]) },
  { pattern: "v1/conversations/:uuid", methods: new Set(["PATCH", "DELETE"]) },
  { pattern: "v1/conversations/:uuid/messages", methods: new Set(["GET"]) },
  { pattern: "v1/auth/claim", methods: new Set(["POST"]) },
];

/** Headers we send upstream. Everything else the browser volunteers (origin, referer,
 *  user-agent, x-forwarded-*) is dropped rather than relayed: the API's IP-based rate
 *  limiting must key on OUR hop, not on a header a caller controls.
 *
 *  `authorization` is DELIBERATELY ABSENT. A client-supplied bearer token is never
 *  forwarded; the proxy mints one server-side from the verified session (see `authorize`),
 *  so a caller cannot present an arbitrary token to the API through us. */
const FORWARD_UP = ["content-type", "cookie", "accept"] as const;

/** Headers we return. `x-accel-buffering: no` must survive: it is what stops an ingress
 *  buffering the SSE body and turning "streaming" into batch delivery. */
const FORWARD_DOWN = ["content-type", "cache-control", "x-accel-buffering"] as const;

function matches(pattern: string, path: string): boolean {
  const p = pattern.split("/");
  const s = path.split("/");
  if (p.length !== s.length) return false;
  return p.every((seg, i) => (seg === ":uuid" ? UUID.test(s[i] ?? "") : seg === s[i]));
}

export function isAllowed(path: string, method: string): boolean {
  // Reject traversal outright rather than relying on the matcher to catch it. Defence in
  // depth: two independent reasons `v1/../admin/kill-switch` fails.
  if (path.includes("..") || path.startsWith("/")) return false;
  return ROUTES.some((r) => r.methods.has(method) && matches(r.pattern, path));
}

/**
 * Server-side bearer token for the API, or null when accounts are not in play.
 *
 * Injected here rather than sent by the browser. The client never handles an API-bound
 * credential, and a forged `Authorization` header on an inbound request is ignored because
 * FORWARD_UP does not include it. Clerk is loaded dynamically so the whole auth path stays
 * absent from the bundle — and so a deployment with no Clerk configured does not fail to
 * build merely for lacking an optional dependency.
 */
async function authorize(headers: Headers): Promise<void> {
  if (!process.env.CLERK_SECRET_KEY) return;
  try {
    const { auth } = await import("@clerk/nextjs/server");
    const token = await (await auth()).getToken();
    if (token) headers.set("authorization", `Bearer ${token}`);
  } catch {
    // No signed-in user, or Clerk unavailable. Anonymous is a valid state for every route
    // in the allowlist, so this degrades to an anonymous call rather than failing (D24:
    // anonymous chat must keep working without signup).
  }
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
  await authorize(headers);

  // Body is read to text rather than piped: these payloads are small JSON, and streaming a
  // REQUEST body through Node fetch needs `duplex: "half"` plus its own failure modes. The
  // RESPONSE is what has to stream, and that is handled below.
  const method = request.method;
  const body = method === "POST" || method === "PATCH" ? await request.text() : undefined;

  const upstream = await fetch(`${API_BASE_URL}/api/${path}`, {
    method,
    headers,
    body,
    signal: request.signal ?? AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    redirect: "manual",
    cache: "no-store",
  });

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
