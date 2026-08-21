# medbot-web — the query surface (S10)

Next.js 15 App Router · React 19 · TypeScript (strict) · Tailwind v4.
Runs on **:5008** and talks to the API on **:5007** through a server-side proxy.

## Why a BFF proxy and not CORS (D23)

The browser only ever talks to this origin. `src/app/api/[...path]/route.ts` forwards
server-side to the API, so:

* **CORS does not exist as a problem** — there is no CORS middleware in the API at all,
  and a direct browser call would simply be blocked.
* the httpOnly `medbot_sid` cookie flows without `credentials` gymnastics;
* in Phase 7/8 only this tier needs an ingress — the API stays an internal service.

The forwarder is an **allowlist, not a passthrough** (`src/lib/proxy.ts`). A catch-all
would expose `/admin/kill-switch` and `/metrics` to the internet through the web tier.
Methods are pinned per route; path traversal is rejected independently of the allowlist.

## Proven, not assumed

`node scripts/verify-stream.mjs` starts a mock upstream that emits tokens at a known
cadence and asserts the cadence survives the proxy. A buffered response contains exactly
the same bytes as a streamed one — only the *timing* differs — so this is the only way to
know. Measured: 6 tokens at ~124 ms intervals against a 120 ms upstream cadence.

## The one contract every renderer must honour

`done.text` is **authoritative**. The output guardrail can cut a stream off mid-answer
(S10.2b), so a client MUST discard accumulated tokens whenever `done.kind !== "grounded"`
— otherwise a retracted dosage stays on screen. `finalText()` in `src/lib/contract.ts`
exists so that rule lives in one place.

## Run

```bash
make db && make app          # data tier + API (:5007)
make seed LIMIT=400          # the API refuses to start without an index (P6.3.5)
make web                     # dev server on :5008
```

## Layout

| Path | Role |
|---|---|
| `src/lib/env.ts` | server-only config; **no `NEXT_PUBLIC_` API address by design** |
| `src/lib/proxy.ts` | allowlist + header forwarding + typed 7807 on upstream failure |
| `src/lib/contract.ts` | TypeScript mirror of `medcore.schema` + `finalText()` |
| `src/lib/sse.ts` | SSE frame reader over `fetch` (EventSource cannot POST) |
| `src/app/api/[...path]/` | the BFF route handler |

## Status

S10.3 ships the skeleton and the transport proof. The designed chat surface, the four
answer-kind treatments, citations UI and public pages are S10.4–S10.10.

## Design system (S10.4)

Tokens live in `src/app/globals.css`. Three theme states, deliberately: `:root` is light,
`prefers-color-scheme: dark` applies only when no explicit choice is set, and
`[data-theme]` always wins — so a manual toggle can override the OS, which matters for a
product read at night.

**Red is reserved exclusively for medical emergencies.** Not errors, not validation, not
destructive buttons — there is deliberately no red `destructive` button variant. That
reservation is the only reason the emergency treatment lands when it fires.

### Answer treatments

| kind / category | treatment | voice |
|---|---|---|
| `grounded` | teal, serif body, citations | sourced and checkable |
| `no_answer` | **slate, never a warning colour** | careful, not broken |
| `refused` (dosage, diagnosis, prescription, medication_change, injection) | amber, stethoscope | care, not a scold |
| `refused` (emergency) | **red**, `role=alert`, action first | go to emergency care |
| `refused` (self_harm, harmful) | **red**, `role=alert`, LifeBuoy | support is available |
| `degraded` | stone | this is us, not you |

`src/components/answer/kind-meta.ts` resolves *(kind, category)* to a treatment in ONE
place, so no individual renderer makes a safety-presentation decision.

### Gates — run them, do not assume them

```bash
pnpm check           # contrast + contract drift + typecheck + build
pnpm check:contrast  # 30 colour pairs against WCAG AA, from the same hex values as the CSS
pnpm check:contract  # TS union vs the Python enums — catches frontend/backend drift
```

`check:contract` earned its place immediately: the TS `RefusalCategory` union listed 5 of
the backend's 8 categories, and the missing `harmful` — which carries crisis-helpline copy
— would have rendered as a routine amber refusal.

### Gallery

`/design` renders every treatment with the copy the backend actually returns (verbatim
from `medapi.guardrails._MESSAGES`), so a regression in one treatment is visible beside the
others. No lorem ipsum anywhere: a gallery of placeholder text proves the CSS works and
nothing about whether real content fits.

> Screenshots are deferred to S10.13, where Playwright lands and can capture both themes
> and both densities reproducibly. Until then the gallery is live at `/design`.
