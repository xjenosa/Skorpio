"""
Placement Scoring Engine.

Computes a levelized cost of placing a workload at a candidate site,
conditioned on the local grid state.

The output "pose file" is a small GeoJSON describing the site polygon and
the line from the site to the chosen point-of-interconnection (POI).
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from backend.config import settings
from backend.utils.logger import get_logger

logger = get_logger(__name__)


def workload_to_loadprofile(workload_capacity_mw: float, out_path: str) -> bool:
    """
    Write a 24-hour synthetic load profile for the workload to `out_path`
    as a small JSON file — the per-workload input file the scoring engine
    needs.
    """
    try:
        profile = {
            "capacity_mw": workload_capacity_mw,
            # Naive flat profile; real product uses workload-class shape (training
            # = ~constant, inference = peaked daytime).
            "hourly_kw": [workload_capacity_mw * 1000.0 for _ in range(24)],
        }
        Path(out_path).write_text(json.dumps(profile))
        return True
    except Exception as e:
        logger.warning(f"Load-profile write failed: {e}")
        return False


def prepare_region_topology(grid_telemetry_path: str, out_path: str) -> bool:
    """
    Convert a grid-telemetry snapshot to a normalised topology JSON file
    consumed by the scoring engine.
    """
    try:
        # If the input already exists, treat it as the canonical topology.
        if Path(grid_telemetry_path).exists():
            with open(grid_telemetry_path) as f:
                payload = f.read()
            Path(out_path).write_text(payload)
            return True
    except Exception as e:
        logger.warning(f"Topology preparation failed: {e}")
    return False


def estimate_interconnect_center(grid_telemetry_path: str) -> tuple[float, float]:
    """
    Estimate the centroid of available interconnect substations from a region
    telemetry snapshot. Falls back to (0, 0) if the file is malformed.
    """
    try:
        with open(grid_telemetry_path) as f:
            data = json.load(f)
        subs = data.get("substations", [])
        if not subs:
            return (0.0, 0.0)
        lat = sum(s.get("lat", 0) for s in subs) / len(subs)
        lon = sum(s.get("lon", 0) for s in subs) / len(subs)
        return (round(lat, 4), round(lon, 4))
    except Exception:
        return (0.0, 0.0)


def parse_scoring_output(output_text: str) -> list[dict]:
    """
    Parse the scoring binary's stdout. The CLI prints one row per scenario:
        mode  lcoe_usd_mwh  uptime_lb  uptime_ub
    """
    results = []
    in_table = False
    for line in output_text.split("\n"):
        if "-----+------------+----------+----------" in line:
            in_table = True
            continue
        if in_table:
            parts = line.split()
            if len(parts) >= 4:
                try:
                    results.append({
                        "mode": int(parts[0]),
                        "lcoe_usd_mwh": float(parts[1]),
                        "uptime_lb": float(parts[2]),
                        "uptime_ub": float(parts[3]),
                    })
                except ValueError:
                    continue
            elif parts:
                in_table = False
    return results


def topology_pose_to_geojson(topology_path: str, geojson_path: str) -> bool:
    """
    Convert the scoring binary's binary pose to a GeoJSON FeatureCollection
    the frontend map can render.
    """
    try:
        with open(topology_path) as f:
            data = json.load(f)

        features = []
        for s in data.get("substations", []):
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [s.get("lon", 0), s.get("lat", 0)]},
                "properties": {
                    "facility": s.get("name", ""),
                    "voltage_kv": s.get("voltage_kv"),
                    "headroom_mw": s.get("headroom_mw"),
                },
            })
        for line in data.get("transmission", []):
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": line.get("path", [])},
                "properties": {"voltage_kv": line.get("voltage_kv"), "owner": line.get("owner", "")},
            })

        Path(geojson_path).write_text(json.dumps({
            "type": "FeatureCollection",
            "features": features,
        }))
        return True
    except Exception as e:
        logger.warning(f"Topology→GeoJSON conversion failed: {e}")
        return False


async def run_scorer(
    topology_path: str,
    load_profile_path: str,
    interconnect_center: tuple[float, float],
    search_radius_km: tuple[float, float, float] = (40.0, 40.0, 0.0),
    horizon_months: int = None,
    num_scenarios: int = None,
    out_path: str = None,
    timeout: int = None,
) -> list[dict]:
    """
    Run the external `skorpio-scorer` binary as a subprocess and return the
    parsed scenario table. Falls back to a deterministic mock when the binary
    is not installed (useful in dev).
    """
    horizon_months = horizon_months or settings.scoring_horizon_months
    num_scenarios = num_scenarios or 9
    timeout = timeout or settings.scoring_timeout_seconds

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out_path = out_path or tmp.name

    cmd = [
        "skorpio-scorer",
        "--topology", topology_path,
        "--load", load_profile_path,
        "--center_lat", str(interconnect_center[0]),
        "--center_lon", str(interconnect_center[1]),
        "--radius_lat_km", str(search_radius_km[0]),
        "--radius_lon_km", str(search_radius_km[1]),
        "--horizon_months", str(horizon_months),
        "--num_scenarios", str(num_scenarios),
        "--out", out_path,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            logger.warning("Placement scoring timed out")
            return []
        return parse_scoring_output(stdout.decode("utf-8", errors="replace"))

    except FileNotFoundError:
        logger.warning("skorpio-scorer binary not found — returning deterministic mock")
        import random
        import zlib
        # zlib.crc32 (not hash()) — Python's hash() is randomized per process
        # (PEP 456), making the "deterministic mock" claim above false across
        # container restarts. See REPORTS_COHESION.md §8c.
        rng = random.Random(zlib.crc32(load_profile_path.encode()))
        return [
            {
                "mode": 1,
                "lcoe_usd_mwh": round(rng.uniform(28.0, 72.0), 1),
                "uptime_lb": round(rng.uniform(0.985, 0.999), 4),
                "uptime_ub": round(rng.uniform(0.995, 0.9999), 4),
            }
        ]
