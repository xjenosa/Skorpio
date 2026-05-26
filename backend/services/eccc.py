"""
Environment and Climate Change Canada (ECCC) client.

Single client for two ECCC OGC API collections served at api.weather.gc.ca:
  - hydrometric-stations + hydrometric-realtime  → water flow & water availability
  - climate-normals                              → 1981–2010 station normals

Used by:
  - Siting pipeline    → replaces hardcoded water L/MWh with real flow data
  - Winter Peak        → real historical cold base rates per location
  - Investment         → flood risk signal from current flow vs. historical norm

Public, no key. Docs:
  https://api.weather.gc.ca/openapi
  https://api.weather.gc.ca/collections/hydrometric-stations
  https://api.weather.gc.ca/collections/climate-normals
"""
from __future__ import annotations

import math
from typing import Optional

import httpx
from pydantic import BaseModel, Field

from backend.config import settings
from backend.utils.cache import weather_cache
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class WaterProfile(BaseModel):
    """Water availability at the nearest ECCC hydrometric station."""
    station_id: Optional[str] = None
    station_name: Optional[str] = None
    distance_km: Optional[float] = Field(None, ge=0.0)
    discharge_cms: Optional[float] = Field(None, ge=0.0)  # cubic metres / second
    measurement_time: Optional[str] = None
    source: str = "ECCC HYDAT / Hydrometric"


class ClimateNormal(BaseModel):
    """1981–2010 climate normal at the nearest ECCC station."""
    station_id: Optional[str] = None
    station_name: Optional[str] = None
    distance_km: Optional[float] = Field(None, ge=0.0)
    mean_temp_c_annual: Optional[float] = None
    heating_degree_days: Optional[float] = Field(None, ge=0.0)
    cooling_degree_days: Optional[float] = Field(None, ge=0.0)
    total_precip_mm: Optional[float] = Field(None, ge=0.0)
    source: str = "ECCC Climate Normals 1981–2010"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class ECCCClient:
    def __init__(self):
        self.base = settings.eccc_base_url

    # ── Hydrometric: water flow rates ──────────────────────────────────── #

    async def nearest_hydrometric_station(
        self, lat: float, lon: float, province: Optional[str] = None
    ) -> Optional[dict]:
        cache_key = f"eccc:hydro_stns:{province or 'ALL'}"
        cached = await weather_cache.aget(cache_key)
        if cached:
            stations = cached
        else:
            try:
                params = {"limit": 2000}
                if province:
                    params["PROVINCE_TERRITORY_CODE"] = province
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.get(
                        f"{self.base}/collections/hydrometric-stations/items",
                        params=params,
                    )
                    if r.status_code != 200:
                        return None
                    payload = r.json()
            except Exception as e:
                logger.warning(f"ECCC hydrometric stations error: {e}")
                return None
            stations = [
                {
                    "station_id": (f.get("properties") or {}).get("STATION_NUMBER"),
                    "station_name": (f.get("properties") or {}).get("STATION_NAME"),
                    "lat": (f.get("geometry") or {}).get("coordinates", [None, None])[1],
                    "lon": (f.get("geometry") or {}).get("coordinates", [None, None])[0],
                }
                for f in payload.get("features", [])
            ]
            stations = [s for s in stations if s["lat"] and s["lon"]]
            await weather_cache.aset(cache_key, stations)

        best: Optional[dict] = None
        best_km: float = float("inf")
        for s in stations:
            d = _haversine_km(lat, lon, s["lat"], s["lon"])
            if d < best_km:
                best_km = d
                best = {**s, "distance_km": round(d, 1)}
        return best

    async def water_at(self, lat: float, lon: float, province: Optional[str] = None) -> WaterProfile:
        stn = await self.nearest_hydrometric_station(lat, lon, province)
        if not stn:
            return WaterProfile()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{self.base}/collections/hydrometric-realtime/items",
                    params={"STATION_NUMBER": stn["station_id"], "limit": 1, "sortby": "-DATETIME"},
                )
                if r.status_code != 200:
                    return WaterProfile(
                        station_id=stn["station_id"],
                        station_name=stn["station_name"],
                        distance_km=stn["distance_km"],
                    )
                payload = r.json()
        except Exception as e:
            logger.warning(f"ECCC hydrometric realtime error: {e}")
            return WaterProfile(
                station_id=stn["station_id"],
                station_name=stn["station_name"],
                distance_km=stn["distance_km"],
            )

        feats = payload.get("features") or []
        if not feats:
            return WaterProfile(
                station_id=stn["station_id"],
                station_name=stn["station_name"],
                distance_km=stn["distance_km"],
            )
        props = feats[0].get("properties") or {}
        return WaterProfile(
            station_id=stn["station_id"],
            station_name=stn["station_name"],
            distance_km=stn["distance_km"],
            discharge_cms=props.get("DISCHARGE"),
            measurement_time=props.get("DATETIME"),
        )

    # ── Climate normals: 1981–2010 averages ────────────────────────────── #

    async def climate_normal_at(self, lat: float, lon: float) -> ClimateNormal:
        cache_key = f"eccc:normal:{round(lat, 1)}:{round(lon, 1)}"
        cached = await weather_cache.aget(cache_key)
        if cached:
            return ClimateNormal(**cached)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                # The climate-normals collection is indexed by station; we use
                # a bounding box around the requested point to find candidates.
                bbox = f"{lon - 0.5},{lat - 0.5},{lon + 0.5},{lat + 0.5}"
                r = await client.get(
                    f"{self.base}/collections/climate-normals/items",
                    params={"bbox": bbox, "limit": 50},
                )
                if r.status_code != 200:
                    return ClimateNormal()
                payload = r.json()
        except Exception as e:
            logger.warning(f"ECCC climate normals error: {e}")
            return ClimateNormal()

        best: Optional[dict] = None
        best_km: float = float("inf")
        for f in payload.get("features", []):
            geom = f.get("geometry") or {}
            coords = geom.get("coordinates") or [None, None]
            if not coords[0] or not coords[1]:
                continue
            d = _haversine_km(lat, lon, coords[1], coords[0])
            if d < best_km:
                best_km = d
                best = f

        if not best:
            return ClimateNormal()
        props = best.get("properties") or {}
        result = ClimateNormal(
            station_id=props.get("STN_ID"),
            station_name=props.get("STATION_NAME"),
            distance_km=round(best_km, 1),
            mean_temp_c_annual=props.get("VALUE") if props.get("NORMAL_ID") == "MEAN_TEMP" else None,
            heating_degree_days=props.get("VALUE") if props.get("NORMAL_ID") == "HDD" else None,
            cooling_degree_days=props.get("VALUE") if props.get("NORMAL_ID") == "CDD" else None,
            total_precip_mm=props.get("VALUE") if props.get("NORMAL_ID") == "TOTAL_PRECIP" else None,
        )
        await weather_cache.aset(cache_key, result.model_dump())
        return result


eccc_client = ECCCClient()
