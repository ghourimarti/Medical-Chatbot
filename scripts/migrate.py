"""Create/refresh the Postgres schema and its partitions (D1). Idempotent.

The API already does this in its lifespan, so this script is not the only path — it is the
EXPLICIT one, for `make migrate` and for a cold `make upv` where you want the failure to
surface as a migration error rather than as a confusing API startup crash.

It lives in a file rather than inline in the Makefile because multi-line Python inside a
make recipe has to survive both make's and the shell's escaping, and the result is
unreadable and silently fragile.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text


async def main() -> None:
    from medapi.db.partitions import ensure_future_partitions
    from medapi.db.schema_sql import INITIAL_DDL
    from medapi.deps import build_services

    from medcore.config import get_settings

    services = build_services(get_settings())
    if services.engine is None:
        raise SystemExit("DATABASE_URL is not set — nothing to migrate")

    async with services.engine.begin() as conn:
        for ddl in INITIAL_DDL:
            await conn.execute(text(ddl))
        # A partitioned table with no matching partition REJECTS inserts, so tomorrow's
        # partitions are created ahead of time. Without this a deploy at 23:59 starts
        # failing every write at midnight.
        await ensure_future_partitions(conn, days_ahead=7)
    await services.engine.dispose()
    print("schema + 8 days of partitions ready")


if __name__ == "__main__":
    asyncio.run(main())
