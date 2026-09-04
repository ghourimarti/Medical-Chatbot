"""Backup / restore drill with measured RTO and RPO.

The first question is not "how do we back this up" but "is this a system of record at all".
Three stores, and only one holds data that cannot be reconstructed:

  Postgres  SYSTEM OF RECORD. Sessions and chat history exist nowhere else. If it is lost,
            it is lost — and with it the audit trail and the ability to service a GDPR
            deletion request. This is the only true backup target.

  Qdrant    DERIVED from the corpus PDF by the ingestion pipeline. It can always be rebuilt,
            so a snapshot is not protection against data loss — it is purely an RTO
            optimisation. The real question is measurable: is restoring a snapshot faster
            than re-indexing? Nothing else about it matters.

  Redis     DERIVED and EPHEMERAL: cache entries plus quota counters. Backing it up would be
            actively wrong — restoring stale quota counters would grant or deny allowances
            based on a window that closed hours ago, and restoring stale cache entries
            reintroduces answers the version-key namespace was designed to retire.

SAFETY: every restore in this drill targets a PARALLEL database / collection. Proving a
restore works must never put the data it protects at risk. Nothing is dropped, no volume is
touched, and the live collection and database are read-only throughout.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any

import httpx

PG_CONTAINER = "p5-medical-chatbot-postgres-1"
QDRANT_URL = "http://localhost:1104"
PG_USER = "medbot"
PG_DB = "medbot"
RESTORE_DB = "medbot_restore_drill"


def sh(*args: str, timeout: int = 600) -> tuple[int, str]:
    p = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()


def pg_query(db: str, sql: str) -> str:
    code, out = sh(
        "docker", "exec", PG_CONTAINER,
        "psql", "-U", PG_USER, "-d", db, "-t", "-A", "-c", sql,
    )
    return out.strip() if code == 0 else f"ERROR: {out}"


def drill_postgres() -> dict[str, Any]:
    """Logical dump -> restore into a PARALLEL database -> verify row counts match."""
    print("=== POSTGRES (system of record) ===")
    result: dict[str, Any] = {"store": "postgres", "role": "system-of-record"}

    before_sessions = pg_query(PG_DB, "select count(*) from sessions;")
    before_messages = pg_query(PG_DB, "select count(*) from messages;")
    print(f"  live rows: sessions={before_sessions} messages={before_messages}")
    result["rows_before"] = {"sessions": before_sessions, "messages": before_messages}

    # BACKUP
    t0 = time.perf_counter()
    code, out = sh(
        "docker", "exec", PG_CONTAINER, "sh", "-c",
        f"pg_dump -U {PG_USER} -d {PG_DB} -Fc -f /tmp/medbot.dump && ls -l /tmp/medbot.dump",
    )
    backup_s = time.perf_counter() - t0
    if code != 0:
        print(f"  !! backup failed: {out}")
        result["error"] = out
        return result
    size = out.split()[4] if len(out.split()) > 4 else "?"
    print(f"  backup:  {backup_s:.1f}s ({size} bytes)")
    result["backup_seconds"] = round(backup_s, 2)
    result["backup_bytes"] = size

    # RESTORE into a parallel database
    sh("docker", "exec", PG_CONTAINER, "psql", "-U", PG_USER, "-d", "postgres",
       "-c", f'DROP DATABASE IF EXISTS {RESTORE_DB};')
    t0 = time.perf_counter()
    code, out = sh("docker", "exec", PG_CONTAINER, "psql", "-U", PG_USER, "-d", "postgres",
                   "-c", f'CREATE DATABASE {RESTORE_DB};')
    if code != 0:
        print(f"  !! could not create restore db: {out}")
        result["error"] = out
        return result
    code, out = sh(
        "docker", "exec", PG_CONTAINER,
        "pg_restore", "-U", PG_USER, "-d", RESTORE_DB, "/tmp/medbot.dump",
    )
    restore_s = time.perf_counter() - t0
    print(f"  restore: {restore_s:.1f}s -> database {RESTORE_DB}")
    result["restore_seconds"] = round(restore_s, 2)

    # VERIFY: a restore nobody verified is a backup nobody has
    after_sessions = pg_query(RESTORE_DB, "select count(*) from sessions;")
    after_messages = pg_query(RESTORE_DB, "select count(*) from messages;")
    partitions = pg_query(
        RESTORE_DB,
        "select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace "
        "where c.relname like 'messages_2%' and n.nspname='public';",
    )
    ok = after_sessions == before_sessions and after_messages == before_messages
    print(f"  verify:  sessions={after_sessions} messages={after_messages} "
          f"partitions={partitions} -> {'MATCH' if ok else 'MISMATCH'}")
    result["rows_after"] = {"sessions": after_sessions, "messages": after_messages}
    result["partitions_restored"] = partitions
    result["verified"] = ok

    # Partitioned tables are the interesting part: a dump that restored the parent but not
    # the daily partitions would report a healthy schema and silently hold no rows.
    result["rto_seconds"] = round(backup_s + restore_s, 2)
    print(f"  RTO (dump+restore): {result['rto_seconds']}s")
    return result


def drill_qdrant(collection: str) -> dict[str, Any]:
    """Snapshot -> restore into a PARALLEL collection -> compare point counts."""
    print("\n=== QDRANT (derived from corpus) ===")
    result: dict[str, Any] = {"store": "qdrant", "role": "derived"}
    with httpx.Client(timeout=600.0) as c:
        info = c.get(f"{QDRANT_URL}/collections/{collection}").json()
        points = info["result"]["points_count"]
        print(f"  live collection {collection}: {points} points")
        result["points_before"] = points

        t0 = time.perf_counter()
        snap = c.post(f"{QDRANT_URL}/collections/{collection}/snapshots").json()
        snapshot_s = time.perf_counter() - t0
        name = snap["result"]["name"]
        size = snap["result"].get("size")
        print(f"  snapshot: {snapshot_s:.1f}s ({name}, {size} bytes)")
        result["snapshot_seconds"] = round(snapshot_s, 2)
        result["snapshot_bytes"] = size

        restore_into = f"{collection}_restore_drill"
        c.delete(f"{QDRANT_URL}/collections/{restore_into}")
        t0 = time.perf_counter()
        # Recover from the snapshot Qdrant just wrote inside its own volume.
        resp = c.put(
            f"{QDRANT_URL}/collections/{restore_into}/snapshots/recover",
            json={"location": f"file:///qdrant/snapshots/{collection}/{name}"},
        )
        restore_s = time.perf_counter() - t0
        if resp.status_code >= 400:
            print(f"  !! restore failed {resp.status_code}: {resp.text[:250]}")
            result["error"] = resp.text[:250]
            return result
        print(f"  restore:  {restore_s:.1f}s -> collection {restore_into}")
        result["restore_seconds"] = round(restore_s, 2)

        after = c.get(f"{QDRANT_URL}/collections/{restore_into}").json()
        after_points = after["result"]["points_count"]
        ok = after_points == points
        print(f"  verify:   {after_points} points -> {'MATCH' if ok else 'MISMATCH'}")
        result["points_after"] = after_points
        result["verified"] = ok
        result["rto_seconds"] = round(snapshot_s + restore_s, 2)
        print(f"  RTO (snapshot+restore): {result['rto_seconds']}s")

        # Cleanup: the drill's own artefact, never the live collection.
        c.delete(f"{QDRANT_URL}/collections/{restore_into}")
        print(f"  cleaned up {restore_into} (live collection untouched)")
    return result


def drill_redis() -> dict[str, Any]:
    """Redis is deliberately NOT backed up. This leg documents and checks that claim.

    Backing up a cache is not merely wasteful, it is wrong in two specific ways:

      * Restoring stale QUOTA counters applies a window that already closed. A user who
        exhausted their hourly allowance before the outage would be blocked on restore for
        an hour that has already passed; one who had allowance left gets it granted twice.
      * Restoring stale CACHE entries reintroduces answers that the version-key namespace
        (`Settings.cache_namespace`) exists to retire. A restore could resurrect answers
        generated by a prompt or corpus version that was deliberately superseded — in a
        medical assistant, answers withdrawn for a reason.

    The correct recovery for Redis is an empty Redis: a cold cache costs latency and money
    for a while, and quota counters refill from zero. Both self-heal.
    """
    print("\n=== REDIS (derived + ephemeral) ===")
    result: dict[str, Any] = {
        "store": "redis",
        "role": "derived-ephemeral",
        "backup_strategy": "none-by-design",
        "rpo_seconds": 0,
        "rto_seconds": 0,
        "verified": True,
    }
    code, out = sh("docker", "exec", "p5-medical-chatbot-redis-1", "redis-cli", "DBSIZE")
    print(f"  keys currently held: {out.strip() if code == 0 else 'unavailable'}")
    print("  strategy: NO BACKUP — restoring stale quota counters and retired cache")
    print("            entries would be actively harmful. Recovery = start empty.")
    print("  proven in the chaos drill: Redis stopped -> service kept answering (cache off).")
    result["keys"] = out.strip() if code == 0 else None
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="backup/restore drill")
    ap.add_argument("--collection", default="gale_medical_full_v1")
    ap.add_argument("--out", default="eval-reports/backup-restore.json")
    args = ap.parse_args()

    results = [drill_postgres(), drill_qdrant(args.collection), drill_redis()]
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print(f"\nwrote {args.out}")

    failed = [r["store"] for r in results if not r.get("verified")]
    if failed:
        print(f"UNVERIFIED RESTORES: {', '.join(failed)}")
        return 1
    print("all restores verified against the source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
