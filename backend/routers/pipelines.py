"""
Pipeline-launching endpoints + their per-pipeline catalog lookups.

Each pipeline (siting, winter-peak, electrification, investment, expansion)
gets:
  * A ``POST`` endpoint that validates the request, creates a DB row,
    spawns the orchestrator coroutine as a tracked asyncio.Task, and
    returns a 202 with the streaming/status/results URLs.
  * A ``GET`` endpoint that returns the catalog of valid input options for
    that pipeline (cities, FSAs, operators, …) — read by the New Session
    composer to render dropdowns.

Plus a single ``POST /api/route`` classifier that picks the pipeline for
a free-form prompt without actually starting a run.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db import crud
from backend.db.session import get_db
from backend.runtime import (
    ALLOWED_MODELS,
    ElectrificationRequest,
    ExpansionRequest,
    InvestmentRequest,
    RouteRequest,
    SiteRequest,
    SiteResponse,
    WinterPeakRequest,
    run_electrification_task,
    run_expansion_task,
    run_investment_task,
    run_siting_task,
    run_winter_peak_task,
    spawn_pipeline_task,
)
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["pipelines"])


# ── Shared helpers ────────────────────────────────────────────────────── #


def _validate_model_or_400(model: str | None) -> None:
    if model is not None and model not in ALLOWED_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model '{model}'. Allowed: {sorted(ALLOWED_MODELS)}",
        )


def _new_job_id() -> str:
    return str(uuid.uuid4())


def _build_response(job_id: str, message: str) -> SiteResponse:
    return SiteResponse(
        job_id=job_id,
        message=message,
        stream_url=f"/api/stream/{job_id}",
        status_url=f"/api/jobs/{job_id}",
        results_url=f"/api/results/{job_id}",
    )


# ── Siting (datacenter placement, the original pipeline) ──────────────── #


@router.post("/api/site", response_model=SiteResponse, status_code=202)
async def start_siting(
    request: SiteRequest,
    db: AsyncSession = Depends(get_db),
) -> SiteResponse:
    """Submit a workload placement query to start the siting pipeline."""
    _validate_model_or_400(request.model)
    job_id = _new_job_id()
    await crud.create_job(db, job_id, request.workload, pipeline_id="datacenter-siting")
    logger.info(
        "New siting job %s for workload %r (model=%s)",
        job_id, request.workload, request.model or settings.anthropic_model,
    )
    spawn_pipeline_task(job_id, run_siting_task(job_id, request.workload, request.model))
    return _build_response(job_id, f"Siting pipeline started for '{request.workload}'")


# ── Winter peak stress tester ─────────────────────────────────────────── #


@router.post("/api/winter-peak", response_model=SiteResponse, status_code=202)
async def start_winter_peak(
    request: WinterPeakRequest,
    db: AsyncSession = Depends(get_db),
) -> SiteResponse:
    """Submit a winter-peak stress-test query."""
    _validate_model_or_400(request.model)
    job_id = _new_job_id()
    await crud.create_job(db, job_id, request.query, pipeline_id="winter-peak-stress")
    logger.info(
        "New winter-peak job %s: %r (model=%s)",
        job_id, request.query, request.model or settings.anthropic_model,
    )
    spawn_pipeline_task(job_id, run_winter_peak_task(job_id, request.query, request.model))
    return _build_response(job_id, f"Winter Peak stress test started for '{request.query}'")


@router.get("/api/winter-peak/cities")
async def list_winter_peak_cities():
    """Catalog of cities supported by the Winter Peak Stress Tester."""
    from backend.grid.feeder_topology import list_supported_cities
    return {"cities": list_supported_cities()}


@router.get("/api/winter-peak/cold-events")
async def list_winter_peak_cold_events():
    """Catalog of reference cold events available to the simulator."""
    from backend.services.cold_events import list_reference_events
    return {"events": list_reference_events()}


# ── Neighborhood electrification readiness ────────────────────────────── #


@router.post("/api/electrification", response_model=SiteResponse, status_code=202)
async def start_electrification(
    request: ElectrificationRequest,
    db: AsyncSession = Depends(get_db),
) -> SiteResponse:
    """Submit a neighborhood electrification readiness query."""
    _validate_model_or_400(request.model)
    job_id = _new_job_id()
    await crud.create_job(db, job_id, request.query, pipeline_id="electrification-readiness")
    logger.info(
        "New electrification job %s: %r (model=%s)",
        job_id, request.query, request.model or settings.anthropic_model,
    )
    spawn_pipeline_task(job_id, run_electrification_task(job_id, request.query, request.model))
    return _build_response(
        job_id, f"Electrification readiness study started for '{request.query}'"
    )


@router.get("/api/electrification/fsas")
async def list_electrification_fsas():
    """Catalog of FSAs supported by the Neighborhood Electrification pipeline."""
    from backend.services.statscan import list_supported_fsas
    return {"fsas": list_supported_fsas()}


# ── Climate-adapted grid investment optimizer ─────────────────────────── #


@router.post("/api/investment", response_model=SiteResponse, status_code=202)
async def start_investment(
    request: InvestmentRequest,
    db: AsyncSession = Depends(get_db),
) -> SiteResponse:
    """Submit a climate-adapted grid investment optimization query."""
    _validate_model_or_400(request.model)
    job_id = _new_job_id()
    await crud.create_job(db, job_id, request.query, pipeline_id="grid-investment-optimizer")
    logger.info(
        "New investment job %s: %r (model=%s)",
        job_id, request.query, request.model or settings.anthropic_model,
    )
    spawn_pipeline_task(job_id, run_investment_task(job_id, request.query, request.model))
    return _build_response(
        job_id, f"Climate-adapted investment study started for '{request.query}'"
    )


@router.get("/api/investment/utilities")
async def list_investment_utilities():
    """Catalog of utilities supported by the Investment Optimizer."""
    from backend.services.utility_assets import list_supported_utilities
    return {"utilities": list_supported_utilities()}


# ── Datacenter expansion planner ──────────────────────────────────────── #


@router.post("/api/expansion", response_model=SiteResponse, status_code=202)
async def start_expansion(
    request: ExpansionRequest,
    db: AsyncSession = Depends(get_db),
) -> SiteResponse:
    """Submit a datacenter expansion planner query."""
    _validate_model_or_400(request.model)
    job_id = _new_job_id()
    await crud.create_job(db, job_id, request.query, pipeline_id="datacenter-expansion")
    logger.info(
        "New expansion job %s: %r (model=%s)",
        job_id, request.query, request.model or settings.anthropic_model,
    )
    spawn_pipeline_task(job_id, run_expansion_task(job_id, request.query, request.model))
    return _build_response(
        job_id, f"Datacenter expansion study started for '{request.query}'"
    )


@router.get("/api/expansion/operators")
async def list_expansion_operators():
    """Catalog of operators supported by the Expansion Planner."""
    from backend.services.operator_footprint import list_supported_operators
    return {"operators": list_supported_operators()}


# ── Pipeline auto-router (classification, doesn't start a job) ────────── #


@router.post("/api/route")
async def route_prompt(request: RouteRequest):
    """Classify a free-form prompt into one of the five Skorpio pipelines.

    Doesn't submit anything — purely a classification call. Frontend uses
    this when the user hasn't locked a pipeline via chip or override.
    Rejects with 400 if the router flags the prompt as off-topic or
    multi-location (Skorpio runs one location per submission). The body
    includes a user-facing ``reject_reason`` plus the raw router output so
    the frontend can render either the error or auto-route.
    """
    _validate_model_or_400(request.model)
    from backend.agents.router import RouterAgent

    agent = RouterAgent(model=request.model)
    result = await agent.classify(request.prompt)
    if result.get("off_topic") or result.get("multi_location"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "prompt_rejected",
                "reason": result.get("reject_reason") or "Prompt could not be processed.",
                "off_topic": bool(result.get("off_topic")),
                "multi_location": bool(result.get("multi_location")),
                "classification": result,
            },
        )
    return result
