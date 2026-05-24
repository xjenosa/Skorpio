"""
Skorpio API — FastAPI application entry point.

This file is intentionally thin: lifespan + middleware + router mounting.
Every endpoint lives in a ``backend/routers/*.py`` module organised by
responsibility (pipelines, jobs, chat, live telemetry, snowflake). Shared
module-level state (the in-flight pipeline task registry, request
schemas, model allowlist) lives in ``backend/runtime.py``.

Route map at a glance — see the individual router files for details:

  routers/health.py      — /health
  routers/pipelines.py   — POST /api/{site,winter-peak,electrification,investment,expansion}
                           GET catalogs (/cities, /fsas, /operators, …)
                           POST /api/route (classifier, no run)
  routers/jobs.py        — /api/jobs, /api/jobs/{id} (+ pause/resume/cancel/delete/retag),
                           /api/results/{id}, /api/stream/{id}, CSV export/import
  routers/chat.py        — POST /api/chat/{id} (SSE, with tool-loop + reconcile)
  routers/live.py        — arXiv search, transmission/carbon files,
                           live carbon, live weather, dashboard /api/metrics
  routers/snowflake.py   — /api/snowflake/* (Site Intelligence, optional)
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.auth import router as auth_router
from backend.config import settings
from backend.db.session import engine, init_db
from backend.routers import chat as chat_router
from backend.routers import health as health_router
from backend.routers import jobs as jobs_router
from backend.routers import live as live_router
from backend.routers import pipelines as pipelines_router
from backend.routers import snowflake as snowflake_router
from backend.services.snowflake_client import init_snowflake_tables
from backend.utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise persistent backing stores on startup, tear them down on
    shutdown. Each step is wrapped so a failed Snowflake init (e.g. when
    no credentials are configured) doesn't block the API from coming up
    in offline mode."""
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as exc:
        logger.warning("Database initialization failed: %s. Running in offline mode.", exc)
    try:
        init_snowflake_tables()
    except Exception as exc:
        logger.warning("Snowflake init skipped: %s", exc)
    logger.info("Skorpio API starting up")
    yield
    try:
        await engine.dispose()
    except Exception as exc:
        logger.warning("Database disposal failed: %s", exc)
    logger.info("Skorpio API shutting down")


app = FastAPI(
    title="Skorpio Siting API",
    description=(
        "Autonomous AI-powered datacenter placement from workload spec to "
        "ranked siting plan"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Mount every router. Order doesn't affect routing (FastAPI matches on
# path), but it does affect the order they show up in /docs.
for _r in (
    auth_router,
    health_router.router,
    pipelines_router.router,
    jobs_router.router,
    chat_router.router,
    live_router.router,
    snowflake_router.router,
):
    app.include_router(_r)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "development",
    )
