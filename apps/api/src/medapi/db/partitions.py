"""Partition lifecycle for `messages`.

  ensure_future_partitions()  creates tomorrow's partition before midnight. A partitioned
                              table with no matching partition rejects the insert, so
                              every write fails at 00:00:00 with "no partition of relation
                              messages found for row". Idempotent and cheap; run hourly.

  drop_expired_partitions()   retention. DROP TABLE on one day's partition rather than a
                              DELETE over ~135M rows: instant, lock-light, reclaims disk.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger("medapi.db.partitions")

PARENT = "messages"
_PARTITION_RE = re.compile(rf"^{PARENT}_(\d{{4}})_(\d{{2}})_(\d{{2}})$")


def partition_name(day: date) -> str:
    return f"{PARENT}_{day:%Y_%m_%d}"


async def ensure_future_partitions(conn: AsyncConnection, *, days_ahead: int = 7) -> list[str]:
    """Create partitions for today..today+days_ahead. Idempotent.

    days_ahead defaults to a week rather than a day, so one failed cron run can't take
    writes down. An empty partition costs nothing.
    """
    created: list[str] = []
    today = datetime.now(UTC).date()
    for offset in range(days_ahead + 1):
        day = today + timedelta(days=offset)
        name = partition_name(day)
        # Postgres DDL can't take bind params: `CREATE TABLE ... FOR VALUES FROM (:start)`
        # fails with "the server expects 0 arguments". So the bounds are formatted in.
        # Safe by construction, since they come from `date` objects, never user input.
        start = day.isoformat()
        end = (day + timedelta(days=1)).isoformat()
        await conn.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF {PARENT} "
                f"FOR VALUES FROM ('{start}') TO ('{end}')"
            )
        )
        created.append(name)
    return created


async def list_partitions(conn: AsyncConnection) -> list[str]:
    rows = await conn.execute(
        text(
            "SELECT c.relname FROM pg_class c "
            "JOIN pg_inherits i ON i.inhrelid = c.oid "
            "JOIN pg_class p ON p.oid = i.inhparent "
            "WHERE p.relname = :parent ORDER BY c.relname"
        ),
        {"parent": PARENT},
    )
    return [r[0] for r in rows]


async def drop_expired_partitions(conn: AsyncConnection, *, retention_days: int = 30) -> list[str]:
    """Retention. Returns the partitions dropped.

    Parses names rather than trusting a caller-supplied cutoff string, because the table
    name gets interpolated into DDL and has to come from a source we control. The regex is
    the validation boundary.
    """
    cutoff = datetime.now(UTC).date() - timedelta(days=retention_days)
    dropped: list[str] = []
    for name in await list_partitions(conn):
        match = _PARTITION_RE.match(name)
        if not match:
            logger.warning("skipping unrecognized partition name: %s", name)
            continue
        day = date(int(match[1]), int(match[2]), int(match[3]))
        if day < cutoff:
            await conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
            dropped.append(name)
            logger.info("dropped expired partition %s (retention=%sd)", name, retention_days)
    return dropped
