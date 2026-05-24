"""
Async SQLAlchemy engine + session factory for the Skorpio backend.

Two consumers:
  * FastAPI endpoints via the ``get_db`` dependency — yields one session
    per request, closed automatically.
  * Long-running asyncio tasks (orchestrator pipeline runs, cancellation
    cleanup) via ``AsyncSessionLocal()`` used as an async context
    manager — they manage their own lifetime since they outlive any
    single HTTP request.

``init_db()`` runs once at startup. ``create_all`` is the lazy path —
for production-grade schema changes use Alembic; the small
``ALTER TABLE`` block below handles the columns added after the initial
``create_all`` ran so the existing DB doesn't need a manual migration.
"""

from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import settings
from backend.db.models import Base


# ── Engine + session factory ──────────────────────────────────────────── #

# Connection pool sized for the demo-scale workload: a handful of
# concurrent pipelines + the SSE poll. ``pool_pre_ping`` cheaply tests
# the connection before reuse, which prevents stale-connection errors
# after a Postgres restart in dev.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── FastAPI dependency ────────────────────────────────────────────────── #


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a session scoped to one request.

    Used as ``db: AsyncSession = Depends(get_db)`` in route handlers. The
    async-with block ensures the session is closed (and returned to the
    pool) regardless of whether the handler returns normally or raises.
    """
    session: AsyncSession
    async with AsyncSessionLocal() as session:
        yield session


# ── One-shot startup migration ────────────────────────────────────────── #

# Columns added to the schema after the initial ``create_all`` ran in
# production. Each statement is idempotent (``IF NOT EXISTS``) so it's
# safe to execute on every startup. Promote to Alembic if this list
# grows past ~3 items — at that point inline ad-hoc DDL becomes harder
# to reason about than a versioned migration.
_STARTUP_DDL: tuple[str, ...] = (
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_log JSONB DEFAULT '[]'::jsonb",
    "UPDATE jobs SET progress_log = '[]'::jsonb WHERE progress_log IS NULL",
)


async def init_db() -> None:
    """Create any missing tables and apply lightweight schema patches.

    ``Base.metadata.create_all`` is the lazy path for fresh databases — it
    creates tables that don't exist but won't alter columns. The DDL
    tuple above covers the post-``create_all`` schema additions.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for statement in _STARTUP_DDL:
            await conn.execute(text(statement))
