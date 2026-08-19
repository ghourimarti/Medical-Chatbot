"""Scheduled maintenance (D1, D18).

S7 built partition creation and expiry but left them unscheduled — a retention policy that
nobody runs is a compliance claim, not a control. This is the scheduler.

Two operations, and the ORDER matters: create future partitions BEFORE dropping expired
ones. If dropping fails, writes still work tomorrow. If creation were second and failed,
every write would break at 00:00:00 — turning a housekeeping error into an outage.
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
            # 1) create first — a failure here must not be preceded by destruction
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
