"""Async engine and session factory.

Pool sizing matters here. At 350 RPS with ~2,100 concurrent SSE streams the API can't hold
a connection for the life of a stream, so connections are acquired per-operation and
released immediately. That's what keeps the pool small.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def build_engine(dsn: str, *, pool_size: int = 10, max_overflow: int = 20) -> AsyncEngine:
    return create_async_engine(
        dsn,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,  # survives RDS failover / idle connection reaping
        pool_recycle=1800,
        echo=False,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Transaction per operation. Commits on success, rolls back on any exception."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
