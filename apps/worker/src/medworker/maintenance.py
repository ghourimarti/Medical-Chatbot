"""Scheduled maintenance.

Partition creation and expiry existed but were unscheduled, and a retention policy nobody
runs is a claim rather than a control. This is the scheduler.

The order matters: create future partitions before dropping expired ones. If the drop
fails, writes still work tomorrow. If creation ran second and failed, every write would
break at 00:00:00, turning a housekeeping error into an outage.
"""

from __future__ import annotations

import logging
from typing import Any

from medapi.db.engine import build_engine
from medapi.db.partitions import drop_expired_partitions, ensure_future_partitions

logger = logging.getLogger("medworker.maintenance")


async def run_retention(settings: Any) -> dict[str, Any]:
    if not settings.database_url:
        logger.info("no DATABASE_URL; retention skipped")
        return {"skipped": True}

    engine = build_engine(settings.database_url, pool_size=1, max_overflow=0)
    try:
        async with engine.begin() as conn:
            # 1) create first, so a failure here isn't preceded by any destruction
            created = await ensure_future_partitions(conn, days_ahead=7)
            # 2) then expire
            dropped = await drop_expired_partitions(
                conn, retention_days=settings.history_retention_days
            )
        logger.info(
            "retention complete: %s partitions ensured, %s dropped", len(created), len(dropped)
        )
        return {
            "ensured": len(created),
            "dropped": dropped,
            "retention_days": settings.history_retention_days,
        }
    finally:
        await engine.dispose()
