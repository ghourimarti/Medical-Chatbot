# In-cluster failure drills

Measured on the local `kind` cluster (3 nodes, kindnet CNI, Helm release `medbot`).
Every result below is from a probe pod issuing **90 sequential requests, 1/second** through
the `medbot-api` Service while the fault was injected — so "zero failures" means zero
observed by a client on the cluster network, not an inference from pod status.

| Drill | Fault injected | Result | Notes |
|---|---|---|---|
| 1 | `kubectl delete pod --grace-period=0 --force` | **90 ok / 0 fail** | Worst case: no preStop, no graceful shutdown. Second replica absorbed it |
| 2 | `kubectl rollout restart` (before fix) | **89 ok / 1 fail** | Endpoint race — see below |
| 2 | `kubectl rollout restart` (after fix) | **90 ok / 0 fail** | preStop + `maxUnavailable: 0` |
| 3 | `kubectl drain medbot-worker` | **90 ok / 0 fail** | PDB honoured; api pod rescheduled. **Caveat below** |
| 4 | `kubectl scale deploy/medbot-ml --replicas=0` | 503 typed, not 500 | Readiness bug found — see below |
| 5 | Deploy a nonexistent image tag, then `rollout undo` | **90 ok / 0 fail** | Broken deploy had zero user-visible impact |

## Drill 2 — "zero-downtime" was not zero

The first rolling restart lost one request in ninety (a connection failure, `code=000`).

The cause is the standard endpoint race, and it is worth stating precisely because the
obvious remedy does not work. Deleting a pod triggers two things **concurrently and
asynchronously**: removal from the Service's endpoint list (which every node's kube-proxy
must then observe) and delivery of SIGTERM to the container. uvicorn stops accepting
connections the moment it sees SIGTERM, so for a short window traffic is still being routed
to a socket that is already closing.

`terminationGracePeriodSeconds: 45` does not help. A grace period governs how long a pod may
take to finish; it does nothing about a pod that is *refusing* rather than *slow*.

The fix is to delay the SIGTERM rather than the shutdown:

```yaml
lifecycle:
  preStop:
    exec: { command: ["sh", "-c", "sleep 6"] }
```

The pod keeps serving normally for those six seconds while endpoint removal propagates, and
only then begins shutting down. Paired with an explicit strategy, because the 25% default
would have served on a single pod mid-deploy:

```yaml
strategy:
  rollingUpdate: { maxUnavailable: 0, maxSurge: 1 }
```

Re-measured after the change: **90/90**.

## Drill 3 — what the drain number does and does not prove

The drain drill reports 90/90, and that is true of what it measured: the **API's health
endpoint**. It is not a claim about end-to-end query availability, because only
`medbot-api` has a PodDisruptionBudget:

| workload | replicas | PDB |
|---|---:|---|
| medbot-api | 2 | yes |
| medbot-ml | 1 | no |
| medbot-redis | 1 | no |
| medbot-postgres | 1 | no |
| medbot-qdrant | 1 | no |

Draining a node evicted `medbot-ml` and `medbot-postgres` with no protection and no
redundancy. During their reschedule a real query would have failed, even though the probe
saw an unbroken run of 200s.

This is recorded rather than quietly fixed because single-replica dependencies are the
correct choice for a local cluster — the point is that **the same drill on Phase 7/8
infrastructure must probe an actual query**, not `/healthz`, or it will keep reporting a
availability the system does not have.

## Drill 4 — readiness that could not see its own dependency

Scaling `medbot-ml` to zero produced exactly the right *client* behaviour: a typed RFC 7807
`503 retrieval-unavailable`, never a raw 500 or a leaked exception.

But `/readyz` returned **200** throughout. It consulted only the vector store, so the pod
advertised itself as able to serve while every query failed. Embedding is the first step of
retrieval — without a vector there is nothing to search — which makes an unreachable
embedder exactly as disqualifying as an unreachable index.

Readiness now checks both, concurrently so a slow dependency cannot serialise the probe.
Redis and Postgres are deliberately **excluded**: losing either degrades the service (cache
bypass, history disabled) but it can still answer, and failing readiness on a partial loss
would remove the entire deployment from service to no one's benefit.

The general rule this phase kept re-teaching: **readiness must mean "can serve", not "a
name resolved" or "a dependency I happened to check is up".** The same defect appeared in
three separate places — an empty index reported healthy, a probe that only proved a
binary could execute, and this one.

## Reproducing
```bash
kubectl apply -f /tmp/probe.yaml      # 90 requests, 1/s, through the Service
kubectl rollout restart deploy/medbot-api
kubectl logs rollout-probe            # RESULT ok=<n> fail=<n>
```
