# Decision log — S20 / S20b: accounts, conversations, and the identity seam

Extends `DECISION_LOG_S10.md` (D23–D27b). Nothing there is amended; these are the
decisions the accounts work forced that the frontend log did not cover.

D24 chose **Clerk** and D25 the capability split. What neither settled was *how identity
attaches to data that already exists*, which is where every real bug in this step lived.

---

## D28 — A present-but-invalid token is `401`, never a silent downgrade to anonymous

| Option | Verdict |
|---|---|
| Invalid token → treat as anonymous | **Rejected** |
| Invalid token → `401` | **Chosen** |
| Invalid token → `403` | Rejected — the caller *may* be allowed once re-authenticated |

Downgrading keeps the product working, which is exactly why it is tempting, and it is
wrong twice over:

- **It hides an attack.** A forged token becomes indistinguishable from a signed-out
  visitor, so the one signal that someone is probing the token format disappears.
- **It confuses an honest user.** A person whose session expired stays signed in
  *visually* while their conversations silently vanish, with nothing on screen to explain
  it. Support gets "the app deleted my history".

A **missing** token is anonymous. A **broken** token is broken. A **malformed**
`Authorization` header (`Basic …`, bare `Bearer`) is treated as absent, because it is
indistinguishable from a client that simply is not signed in, and treating a typo as an
attack helps nobody.

Enforced in `medapi/auth.py`; proven in `test_auth_endpoints.py` by downgrading the token
in `resolve_user` and watching two tests fail.

---

## D29 — Ownership failures are `404`, never `403`

`403` is an **oracle**. An attacker enumerating conversation ids learns which ones are
real from the status code alone, without ever reading a byte of content. The owner
notices no difference between the two, so `403` buys nothing and leaks membership.

One `ConversationNotFound` covers "does not exist" and "not yours", raised from a single
`owned_by()` whose ownership predicate is **in the SQL**, not applied to a fetched row.
Filtering after the fetch is how the first version worked, and it was not merely
cosmetic — reading `convo.user_id` on an expired identity-map copy raised
`MissingGreenlet` after a claim.

---

## D30 — `conversation_id` on the query path is authorised in `preflight`, before any work

This is the decision with the sharpest failure mode in the step.

`conversation_id` arrives in the **request body**, so it is attacker-controlled. Passing
it to the writer unverified is a **write-side IDOR**, and write-side is worse than read
here: a conversation is *prompt context*, so appending a turn to a stranger's thread puts
text of the attacker's choosing into what that person's next request sends to the model.
It is stored prompt injection wearing the costume of a feature.

Authorisation therefore runs in `serving.preflight`, which is:

- **before any expensive work** — no embedding or generation is paid for on a request
  that is about to be rejected; and
- **before the `StreamingResponse` is constructed** — so an unauthorised thread is a real
  HTTP `404`. Once bytes are on the wire the status line is already `200`, and the only
  way left to report a refusal is in-band, which every client then has to special-case.

The authorised id — never the request body's — is what travels onward in `Preflight`.

`test_stream_parity.py` asserts this on **both** endpoints, because that file exists
precisely because a control once lived on only one of them.

---

## D31 — "Cannot prove ownership" resolves to *drop the thread*, never to *allow*

Three outcomes, deliberately distinct:

| Situation | Result |
|---|---|
| Caller owns the thread | write into it |
| Caller does not own it | `404` |
| **Postgres unreachable** | **`None` — answer the question, write no thread** |

Failing **open** on the third row would be the worst kind of outage bug: a database blip
would turn every caller-supplied id into an authorised one, and the moment Postgres
recovered the writes would already have landed in strangers' threads.

Failing **closed** with a `500` would violate D21 — a database outage costs history, not
the ability to answer.

Dropping the thread satisfies both: nothing is written into anyone's conversation, and
the question is still answered.

---

## D32 — Claiming an anonymous conversation requires `user_id IS NULL`

Sign-in transfers this session's anonymous conversations to the account, because
the conversation someone just had is usually *the reason they signed up*, and losing it
at the moment of sign-in is the worst possible time to lose it.

The predicate is `session_id = :sid AND user_id IS NULL`. Without the second clause, two
accounts on one shared browser means the **second** sign-in re-assigns the **first**
account's conversations — a cross-account data leak wearing the costume of a merge.
The session id comes from the cookie and is never a parameter, so a caller cannot claim a
session they do not hold.

---

## D33 — Accounts health is an operator fact, not a readiness signal

`/admin/status` reports `{enabled, storage, jwks_reachable}`. `/readyz` and the public
`/api/v1/status` report **none of it**, and a test reads their source to keep it that way.

A JWKS outage stops *new sign-ins from being verified*. It does not stop the pod
answering questions. Failing readiness on it would pull every pod out of the load
balancer over a dependency the anonymous product never uses, and the
autoscaler would then cycle healthy pods for the duration of someone else's incident.

Three booleans rather than one, because they fail independently: an operator seeing a
single `accounts: false` cannot tell whether to fix Postgres or Clerk.

The JWKS probe is **only** on the operator path. Verification itself uses the cached
JWKS, so probing per request would add a network hop to every signed-in call for
information the request does not need.

---

## D34 — Users store no PII beyond the auth subject

`users` is `{id, auth_subject, created_at, last_seen_at}`, asserted by a test that reads
`information_schema.columns` and fails on **any** extra column.

Every additional field (email, name, avatar) is a deletion obligation under D18 and a
breach surface, and the identity provider already holds them. The test exists so adding
one is a deliberate decision with a failing build behind it, rather than a convenient
afternoon.

Messages carry **no** foreign key to conversations — a cascade across partitions would
defeat `DROP PARTITION`. So account deletion removes messages **explicitly and
first**: once the cascade takes the conversations, their messages are unreachable orphans
that only the 30-day partition drop would clear, which is not a deletion anyone would
accept from a GDPR request.

---

## Testing note — why the endpoint tests use `httpx.ASGITransport`, not `TestClient`

`TestClient` runs the app in its **own** event loop (an anyio `BlockingPortal`), while the
fixture builds the asyncpg pool in pytest-asyncio's loop. An asyncpg connection belongs to
the loop that created it, so every database call failed with *"attached to a different
loop"* and *"got result for unknown protocol state"*.

Staying in one loop is the fix. Building the engine inside the app's lifespan would also
work, and was rejected: it would test a wiring production does not use.

The verifier is a `Protocol` for the same reason — the security properties above are
provable **today**, against a stub, instead of "once someone configures an identity
provider". Every one of them was confirmed by breaking the implementation and watching the
specific test fail.

| Guard | Broken how | Tests that failed |
|---|---|---|
| D28 invalid token → 401 | `resolve_user` swallowed `InvalidToken` | 2 |
| D29 ownership → 404 | dropped `owned_by` from the read path | 2 |
| D30 thread authorisation | `thread = conversation_id` (unverified) | 4 (2 per endpoint) |
| D33 readiness independence | read `svc.verifier` in `public_status` | 1 |
