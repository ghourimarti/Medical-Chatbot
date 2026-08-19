# P5.4 — Backup & restore drill

> Reproduce: `make backup-drill` · Date: 2026-08-17
> Harness: [tests/chaos/backup_restore.py](../tests/chaos/backup_restore.py)
> **Safety:** every restore targets a *parallel* database/collection. The live database and
> collection are read-only throughout; no volume is ever touched.

## Classify the state before designing the backup

The first question is not "how do we back this up" — it is **"is this a system of record at
all?"** Three stores, and only one holds data that cannot be reconstructed.

| Store | Nature | If lost | Backup? |
|---|---|---|---|
| **Postgres** | **System of record** — sessions, chat history, audit trail | Gone permanently | **Yes — the only true target** |
| **Qdrant** | Derived from the corpus PDF via ingestion | Rebuildable | Only as an RTO optimisation |
| **Redis** | Derived + ephemeral — cache, quota counters | Cold cache, quotas reset | **No — restoring would be harmful** |

Backing up derived state as though it were a system of record is how teams end up
maintaining expensive pipelines to protect data they could regenerate.

## Measured results

| Store | Backup | Restore | **RTO** | Verified |
|---|---|---|---|---|
| Postgres (`pg_dump -Fc`) | 0.2 s / 8.6 KB | 0.3 s | **0.5 s** | ✅ sessions=2, messages=6, **6 partitions** |
| Qdrant (snapshot) | 1.2 s / 78 MB | 2.2 s | **3.5 s** | ✅ 7,080 / 7,080 points |
| Redis | — | — | 0 (start empty) | ✅ by design |

**Partitions are the interesting part of the Postgres verification.** `messages` is
RANGE-partitioned by day (D1), and a dump that restored the parent table but not its daily
partitions would present a perfectly healthy schema holding no rows. The drill asserts the
partition count, not just row counts.

### Qdrant: snapshot vs rebuild — the only question that matters

Since Qdrant is derived, a snapshot protects nothing. It is worth keeping only if restoring
is meaningfully faster than re-indexing, which is a measurement:

| Path | Time |
|---|---|
| Restore from snapshot | **3.5 s** |
| Full re-index (7,080 chunks) | **~22 min** |

**~390x faster.** Measured by timing a 400-chunk ingest (76.2 s) and extrapolating. The
extrapolation is slightly *pessimistic*: PDF parsing is a fixed cost already inside the
400-chunk baseline, so the true full rebuild is somewhat under 22 minutes. The order of
magnitude — seconds versus tens of minutes — is what decides it.

So: keep snapshots, but classify them as an **availability** tool, not a durability one. If
every snapshot were lost, nothing is lost but time.

### Redis: not backing up is the design, not an omission

Restoring Redis would be actively wrong in two specific ways:

- **Stale quota counters** apply a window that already closed. A user who exhausted their
  hourly allowance before the outage stays blocked for an hour that has already passed;
  one with allowance left gets it granted twice.
- **Stale cache entries** resurrect answers the version-key namespace
  (`Settings.cache_namespace`) exists to retire — in a medical assistant, answers that may
  have been superseded deliberately by a prompt or corpus revision.

Correct recovery for Redis is an *empty* Redis. Proven in P5.3: with Redis stopped, the
service kept answering.

## RPO — the honest part

**RTO looks excellent. RPO is the weak leg, and it is not fixable in application code.**

| Store | RPO with today's setup | Acceptable? |
|---|---|---|
| Postgres | **= the dump interval** (24 h if nightly) | ❌ **No** for chat history |
| Qdrant | Effectively 0 — rebuildable from the corpus | ✅ |
| Redis | 0 — nothing to lose | ✅ |

A logical dump captures a point in time; everything written after it is lost on restore. A
nightly `pg_dump` means **up to 24 hours of conversations and audit trail gone** — which for
a medical assistant is both a product failure and a compliance one, since the audit trail
is the evidence that a given answer was ever given.

**The fix is continuous archiving, not more frequent dumps.** WAL archiving with
point-in-time recovery brings RPO to minutes; managed Postgres (RDS/Cloud SQL) provides it
as configuration. This is a **Phase 6 deployment requirement**, recorded here rather than
quietly left as "backups exist".

`pg_dump` keeps its place regardless — PITR protects against hardware and deletion, while a
portable logical dump protects against a corrupted cluster and enables restore onto a
different major version.

## Findings

### 1. The test suite dropped the development database 🔴🔴

[test_db.py](../apps/api/tests/test_db.py) hardcoded
`postgresql+asyncpg://medbot:medbot@localhost:1102/medbot` — **the real development
database** — and its fixture runs `DROP_ALL`. Integration tests are not deselected by
default (`addopts = "--import-mode=importlib"`), so **`make test` silently dropped every
table** in dev.

Found by accident: the backup drill reported `messages=0` minutes after another command had
measured 16 rows, and the only thing run in between was the test suite.

**The blast radius is the real problem.** The DSN is a hardcoded literal whose safety rests
entirely on port 1102 belonging to a disposable container. Anyone port-forwarding a staging
or production Postgres to 1102 — an ordinary thing to do — turns `pytest` into an outage.

Fixed: a dedicated `medbot_test` database, created on demand, **plus** an
`_assert_disposable()` guard that refuses to run destructive DDL against any database not
named `*_test`. The guard has its own test, because a safety rule that lives only in a
constant is one careless edit from being gone.

**Proven:** 6 messages in dev before the full suite, 6 after. Previously: 0.

### 2. DATABASE_URL was never set, so P5.3's Postgres drill was vacuous 🔴

`DATABASE_URL` is absent from `.env` and `.env.example`, so the API ran with history
**disabled** — and the P5.3 drill "proved" resilience by stopping a database the application
was not using. **That result is withdrawn.**

Re-run with Postgres actually wired:

| | Steady | Postgres down |
|---|---|---|
| Latency | 5.0 s | **8.5 s** |
| Answers | grounded | grounded ✅ |
| History writes | persisted | **silently lost** (best-effort, by design) |

This is the identical bug class to the empty `REDIS_URL` found in P5.2 — and I had fixed
only that one instance. **Fixing one occurrence of a pattern without auditing for the
others leaves the same bug in place under a different name.** `DATABASE_URL` is now
required outside `local`, because without it there is no audit trail and no GDPR deletion
path (D1, D9).

### 3. Postgres outage cost +3.5 s per request 🟠

Same root cause as the Redis finding in P5.3: history is read once and written once per
request, and each call paid a full connection timeout before degrading correctly.

The breaker is now shared by all three remote dependencies — venue chain, Redis, and
Postgres — in [circuit.py](../apps/api/src/medapi/circuit.py). Third use is what justified
extracting it.

**Follow-up correction (P5.5 verification).** The breaker was added but not re-measured, and
when it was, it had barely engaged: requests 1–5 still took ~9s and only the 6th dropped to
5s. The threshold had been copied from Redis without adjusting for call rate.

> **Size a breaker's threshold in REQUESTS, not calls.** Its job is to stop the *second*
> slow request, so it should open after roughly one request's worth of failures. Redis is
> called ~10x per request, so 5 opens partway through the first. Postgres is called twice,
> so 5 needed ~3 requests.

With `postgres_circuit_failure_threshold=2`: 2 slow requests, then **4.8s** — matching the
5.4s steady-state baseline. The half-open probe still costs one slow request per cooldown;
that is the price of detecting recovery, and it is deliberate.

**The process lesson matters more than the tuning.** A fix that is written but never
re-measured is a hypothesis. This one would have been reported as complete on the strength
of a code change alone.

**`clear()` deliberately ignores the breaker.** GDPR erasure is not best-effort work;
skipping it because a circuit is open would report success without deleting anything, which
is precisely the failure that method exists to prevent.

## Not covered

- **Backups are local.** The dump lands inside the container and the snapshot inside the
  Qdrant volume. A backup on the same host as the data protects against corruption and
  human error, but **not against losing the host.** Off-host copy (S3 with lifecycle rules
  and object-lock) is a Phase 6 requirement.
- **Verification is by row and point count**, not content integrity. A restore that
  preserved counts but corrupted payloads would pass this drill.
- No restore-onto-a-different-major-version test.
- No test of restoring *while under load*, which is the realistic scenario.
- Backup encryption and retention policy are unaddressed.
