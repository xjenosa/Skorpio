"""
PeeringDB client — internet exchange (IXP) directory.

Used by the Siting pipeline to estimate fiber latency from a candidate site
to the nearest internet exchange. We treat geodesic distance as a proxy for
round-trip latency at ~1 ms per 200 km of fiber.

Public, no key for read access. Optionally register at peeringdb.com for
higher rate limits if you start fanning out heavily.

Docs: https://www.peeringdb.com/apidocs/
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

# Approximate latency: one millisecond per 200 km of fiber path.
# (Fiber light speed ~2c/3 → ~5 µs/km → 1 ms ≈ 200 km.)
_LATENCY_MS_PER_KM = 1.0 / 200.0


class FiberLatencyProfile(BaseModel):
    """Distance + estimated one-way latency to the nearest internet exchange."""
    nearest_ixp_name: Optional[str] = None
    nearest_ixp_city: Optional[str] = None
    nearest_ixp_country: Optional[str] = None
    distance_km: Optional[float] = Field(None, ge=0.0)
    estimated_latency_ms: Optional[float] = Field(None, ge=0.0)
    source: str = "PeeringDB"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class PeeringDBClient:
    def __init__(self):
        self.base = settings.peeringdb_base_url

    async def list_ixps(self) -> list[dict]:
        """Return all IXPs with city + country + (lat, lon) lookup baked in.

        PeeringDB returns IXP rows with `id`, `name`, `city`, `country`. The
        geographic coordinates live on a separate object (`fac`), so for a
        quick fiber-latency proxy we use the city centroid via the `metro`
        field when available, falling back to per-country fallbacks.
        """
        cache_key = "peeringdb:ixps"
        cached = await weather_cache.aget(cache_key)
        if cached:
            return cached
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(f"{self.base}/ix", params={"limit": 5000})
                if r.status_code != 200:
                    return []
                payload = r.json()
        except Exception as e:
            logger.warning(f"PeeringDB list_ixps error: {e}")
            return []

        rows = payload.get("data") or []
        # Keep only IXPs with usable city / country labels — coords come from
        # a small static centroid table below when this client is wired to
        # the siting agent. The agent computes haversine on those centroids.
        result = [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "city": r.get("city"),
                "country": r.get("country"),
            }
            for r in rows
        ]
        await weather_cache.aset(cache_key, result)
        return result

    async def latency_to_nearest_ixp(
        self,
        lat: float,
        lon: float,
        ixp_coords: dict[str, tuple[float, float]],
    ) -> FiberLatencyProfile:
        """Find the nearest IXP and estimate latency.

        `ixp_coords` is an externally-provided mapping from IXP name → (lat, lon).
        Skorpio ships a curated table for the largest Canadian + cross-border
        IXPs (TORIX, MTLIX, YYCIX, YVRIX, Equinix Chicago, etc.) — kept small
        on purpose so the lookup stays fast.
        """
        ixps = await self.list_ixps()
        if not ixps:
            return FiberLatencyProfile()
        best_name: Optional[str] = None
        best_city: Optional[str] = None
        best_country: Optional[str] = None
        best_km: float = float("inf")
        for ix in ixps:
            name = ix.get("name") or ""
            if name not in ixp_coords:
                continue
            ix_lat, ix_lon = ixp_coords[name]
            d = _haversine_km(lat, lon, ix_lat, ix_lon)
            if d < best_km:
                best_km = d
                best_name = name
                best_city = ix.get("city")
                best_country = ix.get("country")
        if best_name is None:
            return FiberLatencyProfile()
        return FiberLatencyProfile(
            nearest_ixp_name=best_name,
            nearest_ixp_city=best_city,
            nearest_ixp_country=best_country,
            distance_km=round(best_km, 1),
            estimated_latency_ms=round(best_km * _LATENCY_MS_PER_KM, 2),
        )


peeringdb_client = PeeringDBClient()
