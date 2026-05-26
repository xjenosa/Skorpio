"""
Snowflake-backed Site Intelligence endpoints.

These power the report-side "Similar sites" panel, the PCA(3D) chemical-
space view, and the cross-run leaderboard. All optional — the frontend
treats a 503/empty result as "Snowflake not configured" rather than an
error.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.analytics.snowflake_analytics import snowflake_analytics
from backend.db import crud
from backend.db.session import get_db
from backend.models.report import SitingPlan
from backend.runtime import SnowflakeSeedRequest
from backend.services.snowflake_client import (
    is_available as snowflake_is_available,
    status as snowflake_status,
)
from backend.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/snowflake", tags=["snowflake"])


# ── Status + raw diagnostics ──────────────────────────────────────────── #


@router.get("/status")
async def get_snowflake_status():
    """Return Snowflake readiness diagnostics."""
    return snowflake_status()


@router.get("/debug")
async def snowflake_debug():
    """Raw diagnostic: row counts, table presence, and a round-trip
    insert-then-rollback to surface RBAC / column-mismatch problems."""
    from backend.services.snowflake_client import get_connection

    results: dict = {}
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM SITE_FEATURES")
            results["site_features_count"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM SITING_PLANS")
            results["siting_plans_count"] = cur.fetchone()[0]
            cur.execute("SHOW TABLES LIKE 'SITE_FEATURES'")
            results["table_exists"] = cur.fetchone() is not None

            try:
                cur.execute(
                    """
                    INSERT INTO SITE_FEATURES (
                        job_id, workload, region, site_id, site_name,
                        capacity_mw, pue, fiber_latency_ms, transmission_headroom_mw,
                        lcoe_usd_mwh, spot_lmp_usd_mwh, carbon_g_co2_kwh,
                        deployment_months, water_l_per_mwh,
                        generation_method
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s
                    )
                    """,
                    (
                        "debug-job", "debug", "PJM-W", "DEBUG-S001", "Debug Site",
                        30.0, 1.20, 18.0, 40.0,
                        45.0, 38.0, 220.0,
                        14.0, 1.5,
                        "debug",
                    ),
                )
                conn.rollback()
                results["test_insert"] = "ok"
            except Exception as ie:
                results["test_insert"] = f"FAILED: {ie}"

            try:
                snowflake_analytics.store_sites(
                    job_id="debug-store-test",
                    workload="Debug Workload",
                    scoring_results_per_region={
                        "PJM-W": [{
                            "levelized_cost_usd_mwh": 41.2,
                            "site": {
                                "site_id": "DBG-S001",
                                "name": "Debug Town, OH",
                                "generation_method": "debug",
                                "profile": {
                                    "capacity_mw": 38.4, "pue": 1.18,
                                    "fiber_latency_ms": 12.0,
                                    "transmission_headroom_mw": 50.0,
                                    "spot_lmp_usd_mwh": 40.0,
                                    "deployment_months": 14.0,
                                    "water_l_per_mwh": 1.2,
                                },
                            },
                        }]
                    },
                )
                cur2 = conn.cursor()
                cur2.execute(
                    "SELECT COUNT(*) FROM SITE_FEATURES WHERE job_id = 'debug-store-test'"
                )
                cnt = cur2.fetchone()[0]
                cur2.execute(
                    "DELETE FROM SITE_FEATURES WHERE job_id = 'debug-store-test'"
                )
                conn.commit()
                cur2.close()
                results["store_sites_test"] = f"ok — {cnt} row(s) written"
            except Exception as se:
                results["store_sites_test"] = f"FAILED: {se}"
            cur.close()
        results["ok"] = True
    except Exception as exc:
        results["ok"] = False
        results["error"] = str(exc)
    return results


# ── Seeding for CI smoke tests ────────────────────────────────────────── #


@router.post("/seed_test_data")
async def seed_snowflake_test_data(req: SnowflakeSeedRequest):
    """Insert synthetic Snowflake rows so Site Intelligence can be tested
    without running a full pipeline. Returns 400 if Snowflake isn't
    configured (so CI can detect the skip)."""
    sf_status = snowflake_status()
    if not sf_status.get("available"):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Snowflake unavailable", "status": sf_status},
        )

    rows = []
    for i in range(req.n_sites):
        rows.append({
            "levelized_cost_usd_mwh": round(40.0 - i * 1.2, 2),
            "site": {
                "site_id": f"{req.job_id}-S{i+1:03d}",
                "name": f"Test City {i+1}",
                "generation_method": "seed_test",
                "profile": {
                    "capacity_mw": round(28.0 + i * 2.5, 2),
                    "pue": round(1.18 + i * 0.01, 3),
                    "fiber_latency_ms": round(14.0 + i * 0.4, 1),
                    "spot_lmp_usd_mwh": round(38.0 - i * 0.8, 2),
                    "deployment_months": round(12 + i * 0.5, 1),
                    "water_l_per_mwh": round(1.4 + i * 0.05, 2),
                },
            },
        })

    snowflake_analytics.store_sites(
        job_id=req.job_id,
        workload=req.workload,
        scoring_results_per_region={req.region: rows},
    )
    snowflake_analytics.store_plan(
        job_id=req.job_id,
        workload=req.workload,
        plan={
            "executive_summary": f"Seed plan for {req.workload}.",
            "methodology_notes": "Synthetic seed row for Snowflake CI verification.",
            "safety_flags": [],
            "limitations": [],
            "region_insights": [{
                "transmission_constraints": f"{req.region} transmission scenario for UI smoke test.",
                "market_outlook": f"Seed market context for {req.region}.",
                "regulatory_context": "Synthetic context only.",
            }],
            "top_candidates": [{
                "explanation": "Synthetic candidate rationale.",
            }],
        },
    )
    return {"ok": True, "job_id": req.job_id, "seeded_sites": req.n_sites}


# ── Similar-sites + PCA(3D) site space ────────────────────────────────── #


@router.get("/similar_sites/{job_id}/{site_id}")
async def similar_sites(job_id: str, site_id: str, top_k: int = 10, site_name: str = ""):
    """Top-K nearest sites by L2 distance across all jobs."""
    return snowflake_analytics.similar_sites(
        job_id, site_id, top_k=min(top_k, 50), site_name=site_name,
    )


def _site_space_from_plan(plan: SitingPlan) -> list[dict]:
    """Compute a 3D PCA over the sites stored in a completed plan — used as
    a fallback when Snowflake is unavailable or has no rows for this job."""
    try:
        import numpy as np
        from sklearn.preprocessing import StandardScaler
        from sklearn.decomposition import PCA as SkPCA
    except ImportError:
        return []

    try:
        rows = []
        for c in plan.top_candidates:
            p = c.site.profile
            rows.append({
                "site_id":           c.site.site_id or f"site-{len(rows)}",
                "site_name":         c.site.name,
                "region":            c.region_iso,
                "workload":          plan.workload_name,
                "generation_method": c.site.generation_method or "unknown",
                "capacity_mw":       p.capacity_mw or 0.0,
                "pue":               p.pue or 0.0,
                "fiber_latency_ms":  p.fiber_latency_ms or 0.0,
                "transmission_headroom_mw": p.transmission_headroom_mw or 0.0,
                "lcoe_usd_mwh":      c.levelized_cost_usd_mwh,
                "spot_lmp_usd_mwh":  p.spot_lmp_usd_mwh or 0.0,
                "carbon_g_co2_kwh":  0.0,
                "deployment_months": p.deployment_months or 0.0,
                "water_l_per_mwh":   p.water_l_per_mwh or 0.0,
            })

        if len(rows) < 3:
            return []

        feature_cols = [
            "capacity_mw", "pue", "fiber_latency_ms", "transmission_headroom_mw",
            "lcoe_usd_mwh", "spot_lmp_usd_mwh", "carbon_g_co2_kwh",
            "deployment_months", "water_l_per_mwh",
        ]
        X = np.array([[r[c] for c in feature_cols] for r in rows], dtype=float)
        X_scaled = StandardScaler().fit_transform(X)
        n_components = min(3, X_scaled.shape[1], X_scaled.shape[0])
        coords = SkPCA(n_components=n_components).fit_transform(X_scaled)
        if coords.shape[1] < 3:
            coords = np.hstack([coords, np.zeros((coords.shape[0], 3 - coords.shape[1]))])

        return [
            {
                **{k: rows[i][k] for k in (
                    "site_id", "site_name", "region", "workload",
                    "generation_method", "capacity_mw", "lcoe_usd_mwh",
                )},
                "x": round(float(coords[i, 0]), 4),
                "y": round(float(coords[i, 1]), 4),
                "z": round(float(coords[i, 2]), 4),
            }
            for i in range(len(rows))
        ]
    except Exception as exc:
        logger.warning("Plan-based PCA fallback failed: %s", exc)
        return []


@router.get("/site_space/{job_id}")
async def site_space(job_id: str, db: AsyncSession = Depends(get_db)):
    """3D PCA over all sites in a job. Snowflake first, plan fallback."""
    points = (
        snowflake_analytics.site_space_pca(job_id) if snowflake_is_available() else []
    )
    if not points:
        job = await crud.get_job(db, job_id)
        if job and job.result:
            plan = SitingPlan.model_validate(job.result)
            points = _site_space_from_plan(plan)
    return {"available": bool(points), "points": points}


# ── Cross-run analytics + plan search ─────────────────────────────────── #


@router.get("/analytics")
async def snowflake_cross_run_analytics():
    """Cross-run analytics: generation-method leaderboard, top regions,
    workload rankings."""
    return snowflake_analytics.cross_run_analytics()


@router.get("/search_plans")
async def search_plans(query: str = "", limit: int = 10):
    """Semantic + keyword search over stored SitingPlans."""
    if not query or len(query.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query too short (min 2 chars)")
    return snowflake_analytics.search_plans(query.strip(), limit=min(limit, 50))
