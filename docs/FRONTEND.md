# Frontend — Medical Reference Assistant

Next.js 15 (App Router, TypeScript, Tailwind v4) serving a medical RAG assistant. Answers
stream token-by-token, every sourced claim carries a citation you can open, and the four
ways an answer can end — grounded, abstained, refused, degraded — each look different on
purpose.

Decisions and their reasoning: [DECISION_LOG_S10.md](DECISION_LOG_S10.md).

---

## Quick start

```bash
make db && make app          # data tier + API + ml-service
make seed                    # index the corpus (LIMIT=400 for a fast partial index)
make web-preview             # build + serve on :5008
```

Or run the whole thing in containers, web included:

```bash
docker compose -f docker-compose.data.yaml -f docker-compose.app.yaml up -d --build
open http://localhost:5008
```

| Route | What it is |
|---|---|
| `/` | The assistant |
| `/design` | Design-system gallery — every answer treatment, both themes, both densities |
| `/how-it-works` `/safety` `/sources` `/status` `/privacy` `/terms` | Public information |

---

## Architecture

```
browser ──► :5008 Next.js ──► BFF route handler ──► :5007 API ──► pipeline
            (only origin       (allowlisted,          (never publicly
             the browser        server-side)           exposed in prod)
             ever talks to)
```

**The browser never learns the API's address.** `src/lib/env.ts` imports `server-only`, so
a client import of it is a build error rather than a code-review question. There is
deliberately no `NEXT_PUBLIC_*` variable anywhere: one image runs in every environment,
configured at runtime.

**The proxy is an allowlist, not a passthrough** (`src/lib/proxy.ts`). Five routes and their
methods are permitted; everything else 404s — including `/admin/*` and `/metrics`, which a
catch-all would have exposed to the internet through the web tier. Traversal (`..`) is
rejected independently, so two separate reasons stop `v1/../admin/kill-switch`.

Consequences worth naming: no CORS configuration exists anywhere, the httpOnly session
cookie flows without special handling, and in a real deployment only the web tier needs an
ingress.

**State** is one `useReducer` discriminated union (`src/lib/use-answer-stream.ts`):
`idle → streaming → done | cancelled | error`. No TanStack Query — a single long-lived SSE
stream is not a cache-and-revalidate resource, and `isLoading && !error && text.length > 0`
is how a chat UI ends up rendering a spinner over a finished answer.

---

## The rules that are not negotiable

These are enforced in code and covered by tests, not left to reviewer memory.

**1. `done.text` is authoritative.** The server's output guardrail can cut a stream off
mid-answer — a model begins emitting a dose, generation stops, and the terminal event is a
refusal. A client that appended would leave the retracted dose on screen. `finalText()` in
`src/lib/contract.ts` applies this at the reducer, and a mocked-SSE test proves it: break
that function and the refusal and emergency tests fail.

**2. Red is reserved exclusively for medical emergencies.** Not errors, not validation, not
destructive actions — there is deliberately no red `destructive` button variant, and
`Delete my data` is an outline button. That reservation is the only reason the emergency
treatment reads as urgent when it fires.

**3. An abstention is not a warning.** `no_answer` renders in slate. Rendering candour as a
malfunction teaches users to distrust the abstentions that protect them from a confabulated
medical answer.

**4. A citation you cannot show is not a citation.** A marker referencing a passage that
does not exist — `[9]` when three were retrieved — renders as plain text, never a link. A
model can emit a number it was never given, and making that clickable manufactures
provenance the system does not have.

**5. The disclaimer is non-dismissible.** No close control exists; it lives in the root
layout so no route can render without it.

**6. Colour never carries meaning alone** (WCAG 1.4.1). Every treatment has an icon and a
visible text label, so it survives greyscale, colour-blindness and a screen reader.

---

## Design system

Tokens: `src/app/globals.css`. Three theme states, deliberately — `:root` is light,
`prefers-color-scheme: dark` applies only when no explicit choice is set, and `[data-theme]`
always wins, so a manual toggle can override the OS. That matters for a product read at
night. Surface is `#fafaf8`, not `#fff`: a pure-white field is harsh at 2 a.m.

`src/components/answer/kind-meta.ts` resolves *(kind, refusal_category)* to a treatment in
**one place**, so no individual renderer makes a safety-presentation decision.

| kind / category | treatment | voice |
|---|---|---|
| `grounded` | teal, serif body, citations | sourced and checkable |
| `no_answer` | slate | careful, not broken |
| `refused` · dosage, diagnosis, prescription, medication_change, injection | amber, stethoscope | care, not a scold |
| `refused` · emergency | **red**, `role=alert`, TriangleAlert | go to emergency care |
| `refused` · self_harm, harmful | **red**, `role=alert`, LifeBuoy | support is available |
| `degraded` | stone | this is us, not you |

The two urgent voices are separate on purpose: urgency is right for both, but
"go to the nearest emergency department" is the wrong thing to say to someone disclosing
self-harm.

**Densities:** Clinical Calm by default, Editorial Evidence as an opt-in toggle. One
renderer, two layouts — not two component trees.

---

## Testing

```bash
pnpm check       # contrast (30 pairs) · contract drift · types · bundle budget
pnpm a11y        # axe on 8 routes + keyboard + screen-reader assertions
pnpm mobile      # Pixel 7 layout
pnpm e2e         # functional browser tests
make web-ci      # exactly what CI runs: everything not tagged @live
```

**Tests are split by dependency, not by layer.** `@live` tests need the real backend and run
locally; the rest run in CI, where the stack does not exist because the corpus PDF is
correctly untracked. Verified against a genuinely unreachable API rather than assumed — which
immediately caught a mis-scoped status test.

**Four gates that fail the build**, each proven to fail before being trusted:

| Gate | What it catches |
|---|---|
| `check-contrast.mjs` | any token pair below WCAG AA, in either theme |
| `check-contract.mjs` | the TS mirror drifting from the Python enums |
| `check-bundle.mjs` | a route exceeding its First Load JS budget |
| mocked-SSE suite | the terminal-event contract regressing |

A guard never seen failing is not a guard.

---

## What the frontend work found

Building the frontend surfaced defects in the backend it was built against. In order of
severity:

**The streaming endpoint enforced none of the request controls.** `query_stream()` had no
rate limiting, kill switch, cache, spend accounting, history or session handling, while
`query()` had all of them — and the browser only ever calls the streaming endpoint. Measured
before the fix: 25 consecutive requests against a 20/min limit returned 25× 200. Fixed by
extraction into `medapi/serving.py`; 14 parity tests now assert every control on both paths.

**The output dosage guardrail never covered the streaming path.** The control described
in-code as the last line of defence ran only in `answer()`. Every safety number the project
had published was measured on a path a browser never takes.

**Refusal categories were computed and discarded.** The guardrail classified emergency,
self-harm, dosage, diagnosis and injection, then returned only `kind: "refused"`. Without
`refusal_category` on the response, an emergency was indistinguishable from a pharmacy
redirect.

**A read minted a session.** `GET /session/history` resolved-and-attached unconditionally, so
a first-time visitor raced their own first question: both requests cookie-less, both minting,
whichever `Set-Cookie` landed last orphaning the other session's history. Symptom: history
intermittently missing — caught because a browser test failed about one run in two.

**A completed answer was never announced.** The only `aria-live` region lived inside the
streaming view. A cache hit has no streaming phase, so a screen-reader user was told nothing.

**Three build-time defects** found only by containerising: an env var documented but read by
nothing (and misleading — `NEXT_PUBLIC_*` would have exposed the API URL), a pnpm warning
that is a hard failure non-interactively, and an unpinned package manager making image
builds non-reproducible.

---

## Known limitations

- **No accounts.** Sessions are anonymous; history is a single thread keyed by cookie.
  Multiple named conversations need backend work (users + conversations schema) that does
  not exist. Auth is planned as Clerk in S20/S21.
- **History is a plain transcript.** `GET /session/history` returns only role and content.
  The database stores `kind`, but the repository drops it on read, so reusing the treatment
  components would mean guessing — and a past emergency refusal rendered as an ordinary
  answer is exactly the misrepresentation this UI exists to prevent.
- **A cancelled stream is not cost-attributed.** A partial generation has no usage figures,
  and inventing them would corrupt the spend ledger. Bounded now that rate limiting applies
  to the streaming endpoint.
- **Playwright runs with `retries: 1`**, documented in the config. The suite drives a real
  backend where a cold generation takes seconds and a cache hit ~50 ms. A real failure still
  fails twice.
- **Not audited.** This is a portfolio project. `/privacy` says so plainly.

---

## File map

```
apps/web/
├── Dockerfile                  multi-stage · non-root uid 10001 · 409 MB · no npm at runtime
├── next.config.ts              standalone is OPT-IN (BUILD_STANDALONE=1) — see below
├── e2e/                        answer-kinds · streaming-client (mocked) · a11y · mobile · public-pages · screenshots
├── scripts/                    check-contrast · check-contract · check-bundle · verify-stream
└── src/
    ├── app/
    │   ├── api/[...path]/      the BFF proxy route
    │   ├── page.tsx            the assistant
    │   ├── design/             gallery
    │   └── how-it-works|safety|sources|status|privacy|terms/
    ├── components/
    │   ├── answer/             kind-meta (the resolver) · answer-card · emergency-card · evidence · transparency
    │   ├── chat/               question-box · streaming-answer · history-panel · error-state · data-controls
    │   ├── disclaimer · preferences · page-shell · site-footer · ui/button
    └── lib/
        ├── contract.ts         TS mirror of medcore.schema + finalText (rule 1)
        ├── env.ts              server-only API address
        ├── proxy.ts            allowlist forwarder
        ├── sse.ts              SSE frame reader
        ├── citations.ts        [n] parsing + the out-of-range guard
        └── use-answer-stream.ts  the state machine
```

**`output: "standalone"` is opt-in.** It produces a self-contained server for the image, but
it also makes `next start` unsupported — which silently turned `pnpm preview`
(`next build && next start`) into an invalid combination that failed intermittently. The
Dockerfile sets `BUILD_STANDALONE=1`; local builds do not.
