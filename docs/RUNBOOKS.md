# Operational runbooks

> Every number here was produced by a P5 drill or load test. Nothing is estimated.
> Sources: [CHAOS_DRILLS.md](CHAOS_DRILLS.md) · [LOAD_TEST.md](LOAD_TEST.md) ·
> [BACKUP_RESTORE.md](BACKUP_RESTORE.md) · [SECURITY_AUDIT.md](SECURITY_AUDIT.md)

A runbook written from imagination documents what you *hope* happens. Each procedure below
states the measured behaviour first, because the most common on-call mistake is escalating
a system that is degrading exactly as designed.

## Triage: is this actually an incident?

Check in this order — it goes from cheapest to most expensive, and the first two questions
resolve most pages.

| Question | Command | If yes |
|---|---|---|
| Are answers still being served? | `curl -s localhost:1107/api/v1/query -d '{"question":"What is an abscess?","stream":false}' -H 'content-type: application/json'` | Not an outage. Continue triage at ticket pace |
| Which dependency is unhealthy? | `curl -s localhost:1107/metrics \| grep circuit_state` | Jump to that section |
| Is it saturation rather than failure? | p95 latency climbing while error rate stays 0% | [Saturation](#saturation) |

**A 503 with a problem-type body is designed behaviour, not a crash.** `service-degraded`
and `retrieval-unavailable` are typed, retryable refusals. A **500** is the real alarm — it
means something was not anticipated.

---

## Provider outage

**Alert:** `MedbotDegradedMode`, `MedbotAllVenueCircuitsOpen`

**Measured:** requests return `503 service-degraded` with RFC 7807. The venue circuit
opens after 3 consecutive failures. **Recovery took 64.8 s** — dominated by the model
reloading into GPU memory, which no application change shortens.

1. Confirm the venue is actually down, not merely slow:
   `curl -s http://localhost:1111/v1/models`
2. Check the chain in use: the startup log line `serving chain: ...`. A chain of one venue
   has nothing to fail over to — **this is the single most common cause of a full outage in
   this system**, and it is a configuration problem, not an infrastructure one.
3. Read the venue error. It names the exception type:
   `local: ConnectError: All connection attempts failed`
  - `ConnectError` → the process is down or the port is wrong
  - `ReadTimeout` → alive but overloaded; check GPU memory before restarting
  - `status=400 body=...` → the provider is rejecting the request. SGLang reports exact
   token counts; compare against its 8192-token context
4. If a second venue exists, set `SERVING_CHAIN` to put it first and roll the pods.
5. If no venue is available, `CACHE_ONLY_MODE=true` still serves cached answers.

**Expected recovery: ~65 s** after the engine restarts. Do not escalate before then — you
will be watching a model load.

---

## Redis outage

**Alert:** `MedbotRedisCircuitOpen`

**Measured:** the service **keeps answering correctly**. Before the breaker, latency
went 2.0 s → **20.4 s**, because ~10 Redis calls per request each paid a 2 s socket timeout.
With the breaker: one slow request (~12 s), then normal latency. **Recovery: 4.1 s**, no
restart needed.

**What is actually broken:**
- Every request is a cache miss — measured **13 ms hit vs 1835 ms miss**, and cost
  rises in proportion
- Quotas fall back to **per-replica** in-process counters, so the effective limit becomes
  N × configured across N replicas

1. Confirm: `docker exec <redis> redis-cli ping`
2. Restart Redis. **Do not restore from a backup — there isn't one, by design**
   ([BACKUP_RESTORE.md](BACKUP_RESTORE.md)). Restoring stale quota counters applies a window
   that already closed; restoring retired cache entries resurrects answers the version-key
   namespace deliberately superseded.
3. Expect a cold cache: elevated latency and cost until the hit rate recovers. That will
   trip `MedbotCacheHitRateCollapsed` — expected, not a second incident.

**Escalate only if** the breaker stays open after Redis is confirmed healthy: that points at
the client pool, not the server.

---

## Postgres outage

**Alert:** `MedbotPostgresCircuitOpen`

**Measured:** answers are still served and grounded. Latency 5.0 s → **8.5 s** before
the breaker. **Recovery: 4.6 s.**

**⚠ The serious consequence is invisible to users: history writes are silently dropped.**
The audit trail has a hole for the duration and **that data is unrecoverable** — it was
never written anywhere. For a medical assistant this is a compliance issue, not a UX one.

1. Confirm: `docker exec <pg> pg_isready -U medbot -d medbot`
2. Restart Postgres. Data in the volume survives a container restart.
3. **Record the outage window.** It is a known gap in the audit trail and must be reported
   as such, not discovered later during an audit.
4. If the volume is lost, go to [Restore from backup](#restore-from-backup).

**Do not** disable `DATABASE_URL` to "make the errors stop". That is refused
outside `local` — without it there is no audit trail and no GDPR deletion path.

---

## Qdrant outage

**Alert:** `MedbotRetrievalUnavailable`

**Measured:** requests return `503 retrieval-unavailable`. **Recovery: 5.1 s.**

**Check the alias before the process.** `gale_live` pointing at a dropped or empty
collection produces this alert with Qdrant perfectly healthy — and that is the more likely
cause after a failed ingest.

```bash
curl -s localhost:1104/aliases                       # gale_live -> ?
curl -s localhost:1104/collections/<target>          # points_count > 0 ?
```

1. If the alias is wrong, repoint it — that is an atomic swap and the fastest possible fix
.
2. If the collection is genuinely gone, restore from snapshot: **3.5 s**, versus **~22 min**
   to re-index ([BACKUP_RESTORE.md](BACKUP_RESTORE.md)). Always prefer the snapshot.
3. If Qdrant itself is down, restart it; the volume persists.

**This alert exists because of a chaos-drill finding.** Zero retrieval candidates used to return
`no_answer` with a 200 — a broken index answered every question with a confident *"I don't
have reliable information"*, no alert fired, and the service looked perfectly healthy while
being uniformly wrong. If you ever see mass abstention **without** this alert, suspect the
regression has returned.

---

## Index rebuild and alias rollback

The alias is the rollback mechanism. A bad index is never repaired in place.

```bash
# Build into a NEW collection and swap only after verification (D11)
uv run medworker-ingest --direct --alias gale_live

# Roll back: point the alias at the previous collection
curl -X POST localhost:1104/collections/aliases -H 'content-type: application/json' \
  -d '{"actions":[{"rename_alias":{"old_alias_name":"gale_live","new_alias_name":"gale_live"}}]}'
```

**Rollback is instant; rebuilding is ~22 minutes.** Keep the previous collection until the
new one has served real traffic. **Never delete the old collection in the same change that
promotes the new one** — that turns a 1-second rollback into a 22-minute one.

After any swap, bump the cache version key. Otherwise cached answers from the old corpus
outlive the index that produced them.

---

## Abuse spike

**Alert:** `MedbotAbuseSuspected`

**Measured:** guardrail refusals cost **6 ms** and zero tokens, so the system absorbs
abuse cheaply — 245 RPS of unsafe traffic with 0 failures.

1. Identify the bucket: `medbot_rate_limited_total{scope="ip_minute"}` vs `"minute"`.
   **`ip_*` is the meaningful one.** Session-scoped limits are self-selected — before the IP bucket,
   session-only limiting was bypassable by simply not sending the cookie (measured: **0/30**
   requests limited).
2. Per-IP limits are sized for carrier-grade NAT (300/min), so sustained rejections mean a
   single address far beyond shared-user behaviour.
3. Block upstream at the CDN/WAF. Lowering `RATE_LIMIT_IP_PER_MINUTE` also throttles
   legitimate users behind the same NAT.
4. If the source rotates IPs, per-IP limiting cannot help — that needs upstream reputation
   filtering. Note it rather than tightening limits until real users are affected.

---

## Saturation

**Alert:** `MedbotApproachingSaturation`

**Measured, single worker:** cache path saturates at **~310 RPS**; the full pipeline
at **~2 RPS**. Past saturation **throughput plateaus and latency grows while the error rate
stays 0%** — so latency is the leading indicator and errors are lagging.

1. Check the stage split first: `medbot_stage_duration_seconds{stage="rerank"}`. Reranking
   measured **54% of pipeline cost**, on CPU.
2. If rerank dominates, scale the **ml-service**, not the API. Adding API replicas to
   fix a CPU-reranking bottleneck buys the wrong resource — the extrapolation showed
   this ending in 100+ replicas running a model that belongs on one GPU.
3. If the cache hit rate is low, that multiplies pipeline load directly: at 13 ms vs 1835 ms,
   every lost hit is ~140× more work.

---

## Restore from backup

**Measured:** Postgres RTO **0.5 s**; Qdrant RTO **3.5 s**. Both verified against
source counts, including the six daily partitions.

```bash
make backup-drill        # restores to PARALLEL targets; never touches live data
```

**Before restoring in a real incident, understand the RPO.** With logical dumps, RPO equals
the dump interval — a nightly dump means **up to 24 hours of conversations and audit trail
lost**. If PITR is configured (a Phase 6 requirement), recover to a timestamp instead.

Restore order:
1. **Postgres first** — it is the only system of record.
2. **Qdrant from snapshot** (3.5 s) rather than re-indexing (~22 min).
3. **Redis: start empty.** Never restore it.

---

## Cost thresholds

Reviewed against measurement rather than left at their Phase-1 guesses:

| Control | Setting | Basis |
|---|---|---|
| `DAILY_SPEND_LIMIT_USD` | 5.0 | Sized for development. Phase-1 full load is ~$830/day — **this must be raised deliberately before production or the breaker trips on day one** |
| Cost/query alert | $0.001 p95 | Phase-1 NFR |
| Cache-hit floor | 10% | Below this, cost tracks the 140× miss penalty |
| Self-hosted venues | $0/token | Cost alerts only bind on hosted venues — a chain that has failed over to Groq is a *cost* event as well as an availability one |

**The kill switch fails closed to its last known state and the env floor always applies**
. An operator who disabled generation must not have it silently re-enable on restart.

---

## Log retention and PII

**What is redacted:** the structlog processor strips PII before emission, and
questions are logged only as a fingerprint hash, never as text. **A medical question is
itself sensitive** — "what are the symptoms of HIV" in a log line is a health disclosure
regardless of who asked it.

| Stream | Retention | Reason |
|---|---|---|
| Application logs (JSON, stdout) | 30 days | Debugging window; no raw questions |
| Chat history (Postgres) | 90 days via `DROP PARTITION` | Retention is a partition drop, not a `DELETE` — it does not bloat the table or need a vacuum |
| Metrics (Prometheus) | 15 days raw | Sized for burn-rate windows (max 6 h) plus post-incident review |
| Backups | See Phase 6 | Must be off-host with object-lock; currently local only |

**GDPR erasure** is `DELETE /api/v1/session` and asserts against the database, not the API
response. It deliberately **ignores the circuit breaker**: erasure is not
best-effort work, and skipping it because a breaker is open would report success without
deleting anything.

**Client IPs are never stored raw** — only a salted hash (`client_hash`), so per-IP abuse
detection works without retaining personal data.
