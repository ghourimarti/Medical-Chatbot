# Decision Log — S10 Frontend (D23–D27b)

> Extends [DECISION_LOG_V2.md](DECISION_LOG_V2.md). Status: **signed off**, S10.2 implemented.
> Design reference: Consensus.app — take the evidence-led, "shows its work" quality; reject
> its assumption that the user is a researcher. A medical assistant must refuse, abstain and
> disclaim in ways a paper-search tool never needs to.

## Contract verified against the running backend (not the brief)
`POST /api/v1/query` · `POST /api/v1/query/stream` (SSE `sources`→`token`*→`done`) ·
`GET /api/v1/session/history` · `POST /api/v1/session/clear` (returns rows deleted) ·
`GET /healthz` · `GET /readyz` · `GET /api/v1/status` (new) · admin routes behind `x-admin-key`.
Session: `medbot_sid`, **httpOnly**, SameSite=Lax, 30 days.

## D23 — Browser↔API topology: **Next.js BFF proxy**
**Options:** CORS middleware on FastAPI (backend change, per-env origin lists, exposes the API
publicly, credentialed CORS is easy to misconfigure) · **route-handler proxy** (chosen).
**Reasoning:** the browser only ever talks to `:5008`, so CORS does not exist as a problem;
the httpOnly cookie flows without `credentials` gymnastics; and in Phase 7/8 only the web
tier needs an ingress while the API stays an internal service — *better* posture than today.
There is no CORS middleware in the API at all, so a direct call would simply be blocked.
**Trade-offs:** one extra hop; the SSE handler must stream (`ReadableStream`), verified byte-wise
rather than assumed.
**Reversibility:** Easy — adding CORS later does not invalidate the proxy.

## D24 — Authentication: **Clerk** *(user override of the Auth.js recommendation)*
**Options:** Clerk (fastest DX; ~$0.02/MAU past 10k free → economics invert at the 10M design
scale; vendor lock) · Auth.js v5 ($0/MAU, own Postgres, vendor-portable — **recommended, not
chosen**) · Cognito (cheap at scale, AWS-only, conflicts with Phase 7's DOKS-first portability).
**Decision:** **Clerk**, speed prioritised over portability by explicit user decision.
**Accepted cost, recorded so it is not rediscovered later:** per-MAU pricing above ~10k MAU, an
external identity dependency, and a deviation from the P3.3 vendor-portability principle.
**Flip-trigger:** MAU > ~50k, a client data-residency requirement, or Clerk pricing changes →
migrate to Auth.js (the seam is the session-merge point in D25).
**Sequencing (decided, not asked twice):** Clerk answers *who is this person*; it does **not**
create the `users`/`conversations` schema that logged-in history needs. That backend work does
not exist. Therefore **S10 ships anonymous-first**, and auth lands as **S20 (backend) → S21
(frontend)**. Anonymous chat never gets a signup wall.

## D25 — Capability split
Anonymous: ask · stream · citations · refusals · single-thread history (30d) · delete-my-data ·
per-session+per-IP quota · client-side transcript export.
Signed-in (S21): all of the above · multiple named conversations · cross-device · higher quota ·
full account delete.

## D26 — State layer: **server components + one client island; no TanStack Query**
A single long-lived SSE stream is not a cache-and-revalidate resource, so Query's dedup/cache/
refetch value does not apply and its ~13 kB buys nothing. Public pages are server components
(zero JS). Chat is one client component owning a `useReducer` machine
(`idle → streaming → done | cancelled | error`) plus `AbortController`.

## D27 — Design tokens
**Type:** Inter (UI) + Source Serif 4 (answer body — signals considered editorial content and
reads better in long form at night).
**Palette rule:** **red is reserved exclusively for medical emergencies.** Not errors, not
validation, not destructive buttons. That reservation is what makes the emergency treatment
unmissable when it fires.
Surface `#FAFAF8` (not pure white — harsh at 2 a.m.) · accent teal · grounded teal ·
no_answer slate (calm, *not* a warning) · refused amber (care, not scold) · **emergency red** ·
degraded stone. 4 px spacing base, 1.7 line-height on answers, 68ch measure. Contrast verified
in S10.12, not assumed.

## D27b — Two answer densities *(user addition, better than the either/or offered)*
**Clinical Calm** is the default: airy, evidence in a side panel. **Editorial Evidence** is an
opt-in density: numbered footnotes with passages expanded inline beneath the answer. Persisted
per user; one renderer, two layouts — not two codebases.

---

# S10.2 — Backend gap closure (implemented)

## S10.2a — `refusal_category` reaches the client
`guardrails.py` classified EMERGENCY / SELF_HARM / DOSAGE / DIAGNOSIS / injection and had
distinct copy for each, then **logged the category and discarded it**. Any client wanting an
emergency-specific treatment had to pattern-match refusal prose — a second source of truth for
a safety rule, guaranteed to drift the first time a message is reworded.
Added to `Answer` and `DoneEvent`, with a validator: the field is only valid when
`kind == refused`.

## S10.2b — 🔴 DEFECT FOUND AND FIXED: the output dosage net never covered the streaming path
`contains_dosage_instruction` — described in-code as the last line of defence against a dose
reaching a user — was called only in `_generate`, which serves `answer()`. **`stream_answer()`
had no output-side check at all**, and the browser uses that path for every question.
It passed everything because the eval harness calls `answer_verbose()` and `test_streaming.py`
asserted nothing about dosages: **every safety number this project has reported was measured on
a code path a browser never takes.**
Fix: check the accumulated buffer per token, stop generation on detection (spend stops), emit a
categorised refusal as the terminal event.
**New client contract:** `done.text` is AUTHORITATIVE — a client MUST discard accumulated tokens
whenever `done.kind != "grounded"`.
Proven: with the fix disabled the regression test observed
`kind=GROUNDED, text="Take 500mg twice daily."` — a dose delivered as a cited medical answer.

## S10.2c — public `GET /api/v1/status`
Separate from the key-gated `/admin/status`, which exposes spend, circuit state and the serving
chain — operator facts that tell an attacker which provider to target and how much budget is
left. Public surface returns `status` (ok|degraded|unavailable), the two readiness checks,
`generation_enabled`, and corpus/index versions. Readiness is computed by a shared helper so the
status page and `/readyz` can never disagree.
