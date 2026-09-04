# Decision log — frontend (D23–D27b)

> Extends [DECISION_LOG_V2.md](DECISION_LOG_V2.md). Status: **signed off**, backend gaps implemented.
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
external identity dependency, and a deviation from the vendor-portability principle.
**Flip-trigger:** MAU > ~50k, a client data-residency requirement, or Clerk pricing changes →
migrate to Auth.js (the seam is the session-merge point in D25).
**Sequencing (decided, not asked twice):** Clerk answers *who is this person*; it does **not**
create the `users`/`conversations` schema that logged-in history needs. That backend work does
not exist. Therefore **the frontend ships anonymous-first**, and auth lands later as **backend →
(frontend)**. Anonymous chat never gets a signup wall.

## D25 — Capability split
Anonymous: ask · stream · citations · refusals · single-thread history (30d) · delete-my-data ·
per-session+per-IP quota · client-side transcript export.
Signed-in: all of the above · multiple named conversations · cross-device · higher quota ·
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
by measurement, not assumed.

## D27b — Two answer densities *(user addition, better than the either/or offered)*
**Clinical Calm** is the default: airy, evidence in a side panel. **Editorial Evidence** is an
opt-in density: numbered footnotes with passages expanded inline beneath the answer. Persisted
per user; one renderer, two layouts — not two codebases.

---

# Backend gap closure (implemented)

## `refusal_category` reaches the client
`guardrails.py` classified EMERGENCY / SELF_HARM / DOSAGE / DIAGNOSIS / injection and had
distinct copy for each, then **logged the category and discarded it**. Any client wanting an
emergency-specific treatment had to pattern-match refusal prose — a second source of truth for
a safety rule, guaranteed to drift the first time a message is reworded.
Added to `Answer` and `DoneEvent`, with a validator: the field is only valid when
`kind == refused`.

## 🔴 Defect found and fixed: the output dosage net never covered the streaming path
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

## Public `GET /api/v1/status`
Separate from the key-gated `/admin/status`, which exposes spend, circuit state and the serving
chain — operator facts that tell an attacker which provider to target and how much budget is
left. Public surface returns `status` (ok|degraded|unavailable), the two readiness checks,
`generation_enabled`, and corpus/index versions. Readiness is computed by a shared helper so the
status page and `/readyz` can never disagree.

---

# Endpoint parity (the largest finding of the frontend work)

## The defect

`query_stream()` carried NONE of the cross-cutting controls that `query()` carried. Not a
subset — none:

| Control | `query()` | `query_stream()` (before) |
|---|---|---|
| Rate limiting | yes | **no** |
| Kill switch | yes | **no** |
| Spend tracking / cost attribution | yes | **no** |
| Response cache | yes | **no** |
| History persistence | yes | **no** |
| Session identity | yes | **no** |

Measured against the running service before the fix, one session, 25 requests each:

```
/api/v1/query          ->  200 x20, then 429 x5      (limit enforced)
/api/v1/query/stream   ->  200 x25                   (no limit at all)
```

The browser only ever calls the streaming endpoint. So the deployed rate limit was
bypassable by using the default path; the kill switch could not stop browser traffic
during a cost incident; streamed answers were never cached, never costed, and never
persisted — which also meant the history feature was inert for real usage.

## Why it stayed invisible

Every test and the eval harness exercise `answer()` or `query()`. `PipelineTarget` calls
`answer_verbose()`. The load tests drove the non-streaming path. So every quality, safety
and performance number this project has published describes a code path a browser never
takes. This is the second instance of that shape: the output dosage guardrail
missing from the same handler for the same reason.

## The fix

Extraction, not duplication. `medapi/serving.py` holds `preflight` (session + quota),
`short_circuit` (cache hit or degraded), and `postflight` (cost, metrics, cache write,
history). Both handlers call them. Copying the controls into the stream handler would have
left two copies to drift again, which is how this happened in the first place.

Two ordering constraints are encoded:

* controls run BEFORE the `StreamingResponse` is constructed, so a quota rejection is a
  real HTTP 429 with an RFC 7807 body rather than an in-band SSE error arriving after the
  status line has already gone out as 200;
* a cached or degraded answer is delivered through the SAME event sequence as a generated
  one, so the client keeps exactly one code path.

## Verified after the fix

* streaming rate limit: `200 x20, then 429 x5` — identical to the non-streaming endpoint
* session cookie present on a streaming response
* history persisted for a streamed answer (both turns readable via `/session/history`)
* cache hit on the stream: 2212 ms / 111 token events becomes 59 ms / 0 token events
* 14 parametrized parity tests assert every control on BOTH endpoints, and were proven to
  fail (4 failures, all on the stream variant) when the handler was reverted

## Known and bounded gap, recorded rather than hidden

A cancelled stream skips `postflight`, so a partial generation is not cost-attributed:
there are no usage figures for it, and inventing them would corrupt the spend ledger. The
exposure is bounded because rate limiting now applies to this endpoint. Closing it properly
needs per-token accounting during generation, which is a separate change.

---

# Later frontend findings

## Browser verification (Playwright pulled forward)

Everything before this was verified at the HTTP level, which proves the contract but not
the product: a client can receive a correct `refused` event and still render it as a
grounded answer. Chromium only, ~114 MB, and it unblocks honest verification for every
remaining step plus reproducible screenshots.

Two findings from writing the tests:

* **Next.js injects `<div id="__next-route-announcer__" role="alert">` into every page.**
  So `getByRole("alert")).toHaveCount(0)` can never pass, and the emergency card is not the
  only alert in the document. Assertions are now scoped to `[data-answer-kind="emergency"]`.
* **Prose is a poor test hook.** The first `settled()` helper matched streaming copy and hit
  a strict mode violation, because the sr-only aria-live region duplicates that text for
  screen readers. That is the accessibility layer working correctly. `data-answer-kind`
  now carries the RESOLVED treatment, so tests assert the decision rather than the wording.

## Citations

Inline `[n]` markers are real controls that open their passage. Click, not hover: a
hover-only preview does not exist on a phone, and this is used on phones.

**The rule that matters:** a marker referencing a source that does not exist - `[9]` when
three passages were retrieved - renders as PLAIN TEXT, never as a link. A model can emit a
citation number it was never given, and turning that into a clickable affordance would
manufacture provenance the system does not have. There is a gallery sample demonstrating
it and an e2e test asserting it.

Retrieved passages the answer never cited are shown and labelled "not cited" rather than
hidden, because hiding them would misrepresent what the answer was built from.

## Session controls, and a session race

History renders as a PLAIN TRANSCRIPT, not the treatment components. `GET /session/history`
returns only role and content; the database does store `kind`, but the repository drops it
on read and `Message` is the LLM prompt type, shared with generation. Reusing the treatment
components would therefore mean GUESSING the kind, and a past emergency refusal rendered as
an ordinary answer is exactly the misrepresentation this UI exists to prevent.

**DEFECT FOUND: a read was minting a session.** `GET /session/history` resolved and attached
unconditionally, so a first-time visitor loading the page raced their own first question:
both requests arrive without a cookie, both mint a session, and whichever Set-Cookie lands
last silently orphans the other session history. The symptom was history that intermittently
failed to appear - caught only because a browser test failed roughly one run in two. A
visitor with no session has no history by definition, so there is nothing to mint a session
for. Only a write establishes one. Two regression tests pin it.

Delete-my-data reports the number of rows removed, because the API does. A delete control
that says "Done" without evidence passes review and fails an audit, and the person most
likely to use it wants proof. It is on the main surface rather than in a settings page, and
it uses NO red button: red is reserved for medical emergencies.

## Designed failure states

Each cause gets its own copy, because "what do I do now" differs for each: a quota is a
wait, a provider outage is a retry, a degraded service is a partial capability. A single
generic error box gives the user no way to tell them apart and teaches them the product is
simply unreliable. The quota state deliberately offers NO retry button - retrying
immediately would fail identically and make the product look broken rather than busy.

None of them use red.

The degraded banner is driven by `GET /api/v1/status` on mount rather than discovered when
a request fails, because a standing condition needs a standing signal.

## Test-suite honesty

Playwright runs with `retries: 1`, documented in the config. This suite drives a real
backend where a cold generation takes seconds and a cache hit takes about 50 ms - roughly
20x variance - so the first run after an idle period can exceed a timeout the next run
clears comfortably. A retry is honest here because a real failure still fails twice. It is
not a licence to ignore a test that fails consistently.
