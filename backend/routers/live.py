"""
Live telemetry + ad-hoc lookups: transmission file serving, ElectricityMaps
carbon snapshots, live carbon intensity, live weather, arXiv search, and
the operator metrics that power the Dashboard.

Grouped here because they share the same "lightweight ad-hoc read"
character — none of them spawn pipelines, none touch the running-task
registry, all return small JSON payloads from upstream caches or the DB.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.session import get_db
from backend.services.arxiv import arxiv_client
from backend.services.electricitymaps import electricitymaps_client
from backend.services.open_meteo import open_meteo_client
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["live"])


# ── ArXiv search ──────────────────────────────────────────────────────── #


@router.get("/api/arxiv/search")
async def arxiv_search(q: str, max: int = 5):
    """Search arXiv for energy / grid preprints relevant to a query."""
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query too short")
    return await arxiv_client.search(q.strip(), max_results=min(max, 20))


# ── Transmission topology + carbon snapshot files ─────────────────────── #


@router.get("/api/transmission/{filename}")
async def get_transmission_file(filename: str):
    """Serve a transmission topology / siting plan file (GeoJSON, JSON)."""
    if not re.match(r"^[\w\-\.]+$", filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = settings.transmission_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(path), media_type="application/json")


@router.get("/api/electricitymaps/{zone}")
async def get_carbon_snapshot(zone: str):
    """Persist (and return) the latest carbon intensity snapshot for a zone."""
    if not re.match(r"^[A-Za-z0-9\-_]+$", zone):
        raise HTTPException(status_code=400, detail="Invalid zone code")
    local_path = await electricitymaps_client.get_snapshot(zone)
    if not local_path:
        raise HTTPException(status_code=404, detail=f"No carbon snapshot available for {zone}")
    return JSONResponse({"filename": f"EM-{zone}.json", "zone": zone})


# ── TopBar / Dashboard live telemetry ─────────────────────────────────── #

# Lat/lon + canonical display label for the cities the TopBar / Dashboard
# can target. Keys are lower-case so the frontend may pass any casing.
_CITY_COORDS: dict[str, tuple[float, float, str]] = {
    "toronto":   (43.6532, -79.3832, "Toronto, ON"),
    "ottawa":    (45.4215, -75.6972, "Ottawa, ON"),
    "montreal":  (45.5019, -73.5674, "Montréal, QC"),
    "quebec":    (46.8139, -71.2080, "Québec City, QC"),
    "calgary":   (51.0447, -114.0719, "Calgary, AB"),
    "edmonton":  (53.5461, -113.4938, "Edmonton, AB"),
    "vancouver": (49.2827, -123.1207, "Vancouver, BC"),
    "winnipeg":  (49.8951, -97.1384, "Winnipeg, MB"),
    "halifax":   (44.6488, -63.5752, "Halifax, NS"),
}


@router.get("/api/grid-carbon/{zone}")
async def grid_carbon_live(zone: str):
    """Live carbon intensity (gCO₂eq/kWh) for an ElectricityMaps zone."""
    if not re.match(r"^[A-Za-z0-9\-_]+$", zone):
        raise HTTPException(status_code=400, detail="Invalid zone code")
    if not settings.electricitymaps_api_key:
        return JSONResponse(
            {"data_missing": True, "reason": "ELECTRICITYMAPS_API_KEY not configured"},
            status_code=503,
        )
    payload = await electricitymaps_client.get_carbon_intensity(zone)
    if not payload:
        return JSONResponse(
            {"data_missing": True, "reason": f"No live data for zone {zone}"},
            status_code=503,
        )
    return payload


@router.get("/api/weather")
async def weather_live(city: str = "toronto"):
    """Live weather for one of the supported Canadian cities (Open-Meteo)."""
    key = city.strip().lower()
    if key not in _CITY_COORDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported city '{city}'. Allowed: {sorted(_CITY_COORDS)}",
        )
    lat, lon, label = _CITY_COORDS[key]
    payload = await open_meteo_client.current(lat, lon)
    if not payload:
        return JSONResponse(
            {"data_missing": True, "reason": f"No live weather for {city}"},
            status_code=503,
        )
    # Override the city label with the canonical Skorpio name — the
    # upstream field sometimes returns just "Toronto" without province.
    payload["city"] = label
    return payload


# ── Dashboard operator metrics ────────────────────────────────────────── #

_TERMINAL_STAGES: frozenset[str] = frozenset({"completed", "failed"})
_PIPELINE_LABELS: dict[str, str] = {
    "datacenter-siting":           "Datacenter Siting",
    "datacenter-expansion":        "Expansion Planner",
    "winter-peak-stress":          "Winter Peak Stress",
    "electrification-readiness":   "Electrification Readiness",
    "grid-investment-optimizer":   "Grid Investment Optimizer",
}


@router.get("/api/metrics")
async def operator_metrics(
    timeframe_hours: int = 24,
    db: AsyncSession = Depends(get_db),
):
    """Real Skorpio metrics from the jobs table, used by the Dashboard.

    ``timeframe_hours`` picks the window for success-rate, average duration,
    and per-day counts. Anything other than the three accepted values
    (24, 168, 720) silently snaps to 24h.
    """
    if timeframe_hours not in (24, 24 * 7, 24 * 30):
        timeframe_hours = 24

    now = datetime.utcnow()
    cutoff = now - timedelta(hours=timeframe_hours)

    # Jobs table is small at demo scale (~100s of rows); pull everything
    # and aggregate in Python instead of writing per-window SQL.
    from backend.db.models import Job
    rows = (await db.execute(select(Job))).scalars().all()

    total_runs = len(rows)
    active_runs = sum(1 for j in rows if j.stage not in _TERMINAL_STAGES)
    in_window = [j for j in rows if j.created_at >= cutoff]
    runs_in_window = len(in_window)
    completed_in_window = [j for j in in_window if j.stage == "completed"]
    failed_in_window = [j for j in in_window if j.stage == "failed"]
    success_rate = (
        len(completed_in_window) / runs_in_window if runs_in_window else None
    )

    # Average duration only meaningful for completed runs with both
    # started_at and updated_at populated.
    durations = [
        (j.updated_at - j.started_at).total_seconds()
        for j in completed_in_window
        if j.started_at and j.updated_at
    ]
    avg_duration_seconds = (sum(durations) / len(durations)) if durations else None

    # Per-pipeline mix across the whole table.
    mix: dict[str, int] = {}
    for j in rows:
        pid = j.pipeline_id or "unknown"
        mix[pid] = mix.get(pid, 0) + 1
    pipeline_mix = [
        {"pipeline_id": pid, "label": _PIPELINE_LABELS.get(pid, pid), "count": count}
        for pid, count in sorted(mix.items(), key=lambda kv: -kv[1])
    ]

    # Daily counts within the window — small bar series for the dashboard.
    daily: dict[str, int] = {}
    for j in in_window:
        day = j.created_at.strftime("%Y-%m-%d")
        daily[day] = daily.get(day, 0) + 1
    daily_run_counts = [{"date": d, "count": c} for d, c in sorted(daily.items())]

    # Most recent failures with the error message trimmed to a one-liner.
    recent_failures = [
        {
            "job_id": j.id,
            "workload_spec": j.workload_spec,
            "pipeline_id": j.pipeline_id,
            "error": (j.error or "")[:240],
            "updated_at": j.updated_at.isoformat() if j.updated_at else None,
        }
        for j in sorted(
            (j for j in rows if j.stage == "failed"),
            key=lambda j: j.updated_at or datetime.min,
            reverse=True,
        )[:5]
    ]

    return {
        "as_of": now.isoformat(),
        "timeframe_hours": timeframe_hours,
        "total_runs": total_runs,
        "active_runs": active_runs,
        "runs_in_window": runs_in_window,
        "completed_in_window": len(completed_in_window),
        "failed_in_window": len(failed_in_window),
        "success_rate": success_rate,
        "avg_duration_seconds": avg_duration_seconds,
        "pipeline_mix": pipeline_mix,
        "daily_run_counts": daily_run_counts,
        "recent_failures": recent_failures,
    }
