# Phase 6 findings — what local & kind validation actually caught

Phase 6 cost $0 and found six defects, four of which had passed every prior check. That is
the point of the phase: `helm lint` passing, a template rendering, and a pod reporting
`Running` are all statements about *declarations*, not about behaviour.

## The recurring defect: readiness that means "a name resolved"

The same mistake appeared in three unrelated places, which is why it is worth naming rather
than listing three separate fixes.

| Where | What readiness/health actually proved | What it should have proved |
|---|---|---|
| P6.3.5 | the collection name resolves | the index has content to search |
| P6.4.1 | the Qdrant binary can execute | the Qdrant HTTP API answers |
| P6.5.4 | the vector store is reachable | every dependency a query needs is reachable |

In all three the pod advertised itself as able to serve while every query failed. A probe
that cannot fail for the reason you actually care about is close to no probe at all.

The fixes share a rule: **readiness means "this pod can answer a request"**. Notably that
rule also says what NOT to check — Redis and Postgres are deliberately excluded, because
losing either degrades the service (cache bypass, history disabled) without stopping it, and
failing readiness on a partial loss would withdraw the whole deployment to no one's benefit.

## The most severe: the API was permanently breaking its own alias swap

`QDRANT_COLLECTION` names an **alias** (D11): ingestion builds `gale_live_v1` and repoints
`gale_live` atomically, so readers never see a half-built corpus.

The API called `ensure_collection()` at startup, which *creates* the collection when absent.
`collection_exists()` resolves aliases, so on any environment where the alias already existed
this was a harmless no-op — which is exactly why it survived compose, the test suite, and
every earlier step. On a **fresh** cluster it created `gale_live` as a real collection.

Qdrant forbids an alias and a collection sharing a name. Proven by running real ingestion
against the cluster:

```
409 Conflict — Wrong input: Collection `gale_live` already exists!
```

So D11's zero-downtime swap was **permanently broken on any fresh environment where the API
starts before ingestion** — the normal deployment order. The bug could not be reproduced in
the environment it was written in.

Two things worked correctly throughout and are worth crediting: verify-then-swap meant the
150-chunk collection built fully before the swap was attempted, so nothing half-ingested ever
served; and the query path refused to report an empty index as "no information", returning a
fault instead (P5.3.6).

**Fix:** `verify_collection()` for the read path (checks, never creates, fails loudly) split
from `ensure_collection()` for ingestion, which legitimately creates because it knows what to
put in it.

## "Zero-downtime" was 89/90

Measured, not assumed. A rolling restart under continuous traffic lost one request in ninety.
The cause is the endpoint race — pod deletion removes the pod from Service endpoints and
sends SIGTERM *concurrently*, and uvicorn stops accepting the instant it sees SIGTERM — and
the obvious remedy does not work: `terminationGracePeriodSeconds` governs a pod that is slow,
not one that is refusing. A `preStop: sleep 6` delays the SIGTERM instead of the shutdown.
Re-measured: 90/90. Details and the full drill table in [K8S_DRILLS.md](K8S_DRILLS.md).

## A security control that was doing nothing

Six NetworkPolicies render, `helm lint` is clean, `kubectl get networkpolicy` lists them all
— and kind's default CNI (kindnet) does not implement NetworkPolicy. An unlabelled probe pod,
covered by a `podSelector: {}` default-deny, reached every "protected" service with HTTP 200.

Recording this rather than "fixing" it, because the policies are correct and the gap is the
environment: enforcement must be verified on Calico/Cilium in Phase 7/8. The lesson is that
**"verified in-cluster" on kind would have been a false claim**, and a security control
nobody has watched fail is a control nobody has tested.

## Two measurements I nearly misread

Recorded because the near-misses are as instructive as the finds.

1. **A stale metrics snapshot looked like broken load balancing.** During HPA scale-up one
   pod showed 740m and two showed 3m. The fresh reading moments later was even across all
   five. metrics-server samples on an interval and the new pods had barely started; I was
   one step from filing a distribution bug against a sampling lag.
2. **My own kubectl query "found" missing probes.** Asking for
   `readinessProbe.httpGet.path` renders `<none>` for an **exec** probe, so redis, postgres
   and qdrant all appeared to have no readiness probe. The tool was wrong, not the chart.
   The real finding was underneath it: qdrant's exec probe could not detect the failure that
   mattered.

## Things that were already right

Worth stating, because a findings document that only lists faults misrepresents the system.

- Typed RFC 7807 errors throughout — every failure mode returned a structured envelope with
  a safe message, never a raw 500 or a leaked exception.
- The degradation ladder held: empty index → fault, provider dead → chain, ml-service gone →
  typed 503, all three distinguishable by a client.
- The worker is deliberately not deployed to kind, with the reason written down: a queue-less
  consumer would CrashLoopBackOff forever and "train you to ignore red pods".
- Verify-then-swap, secret-by-reference (zero plaintext env values), non-root images, and a
  `maxUnavailable: 0` rollout that made a completely broken deploy invisible to users.
