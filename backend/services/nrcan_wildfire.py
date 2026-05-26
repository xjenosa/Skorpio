"""
NRCan Wildland Fire client — live wildfire perimeters + Fire Weather Index.

Used by the Investment pipeline to replace the hardcoded provincial wildfire
probability in `climate_hazards.py` with location-specific live signals.

Public, no key. Data is published by the Canadian Wildland Fire Information
System (CWFIS) and refreshed daily during fire season.

Docs:
  https://cwfis.cfs.nrcan.gc.ca/maps/fwi
  https://cwfis.cfs.nrcan.gc.ca/geoserver/web/
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


class WildfireRisk(BaseModel):
    """Wildfire risk profile for one geographic point."""
    nearest_fire_km: Optional[float] = Field(None, ge=0.0)
    nearest_fire_id: Optional[str] = None
    nearest_fire_hectares: Optional[float] = Field(None, ge=0.0)
    active_fire_count_100km: int = Field(0, ge=0)
    source: str = "NRCan CWFIS"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class NRCanWildfireClient:
    def __init__(self):
        self.base = settings.nrcan_wildfire_base_url

    async def active_fires(self) -> list[dict]:
        """Return all active fires currently being tracked across Canada."""
        cache_key = "nrcan:active_fires"
        cached = await weather_cache.aget(cache_key)
        if cached:
            return cached
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(
                    self.base,
                    params={
                        "service": "WFS",
                        "version": "1.0.0",
                        "request": "GetFeature",
                        "typeName": "public:activefires_current",
                        "outputFormat": "application/json",
                    },
                )
                if r.status_code != 200:
                    return []
                payload = r.json()
        except Exception as e:
            logger.warning(f"NRCan active fires error: {e}")
            return []

        fires: list[dict] = []
        for feature in payload.get("features", []):
            geom = feature.get("geometry", {}) or {}
            coords = geom.get("coordinates")  # [lon, lat]
            props = feature.get("properties", {}) or {}
            if not coords or len(coords) < 2:
                continue
            fires.append({
                "fire_id": props.get("firename") or props.get("name") or "unknown",
                "lat": coords[1],
                "lon": coords[0],
                "hectares": props.get("hectares") or props.get("size_ha") or 0.0,
                "stage": props.get("stage_of_control") or props.get("stage"),
            })
        await weather_cache.aset(cache_key, fires)
        return fires

    async def risk_at(self, lat: float, lon: float) -> WildfireRisk:
        """Return wildfire risk profile for one location."""
        fires = await self.active_fires()
        if not fires:
            return WildfireRisk()
        nearest: Optional[dict] = None
        nearest_km: float = float("inf")
        within_100: int = 0
        for f in fires:
            d = _haversine_km(lat, lon, f["lat"], f["lon"])
            if d <= 100.0:
                within_100 += 1
            if d < nearest_km:
                nearest_km = d
                nearest = f
        return WildfireRisk(
            nearest_fire_km=round(nearest_km, 1) if nearest else None,
            nearest_fire_id=nearest["fire_id"] if nearest else None,
            nearest_fire_hectares=nearest["hectares"] if nearest else None,
            active_fire_count_100km=within_100,
        )


nrcan_wildfire_client = NRCanWildfireClient()
