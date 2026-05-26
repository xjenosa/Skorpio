"""
NREL Developer Network client. Returns wind / solar resource maps and
reference cost curves the scoring engine uses to estimate site economics.

Docs: https://developer.nrel.gov/docs/
"""
from typing import Optional

import httpx

from backend.config import settings
from backend.utils.cache import nrel_cache
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class NRELClient:
    def __init__(self):
        self.base = settings.nrel_base_url
        self.api_key = settings.nrel_api_key

    async def wind_resource(self, lat: float, lon: float, height_m: int = 100) -> Optional[dict]:
        """Return annual wind speed (m/s) and capacity factor at a point."""
        cache_key = f"wind:{lat:.3f}:{lon:.3f}:{height_m}"
        cached = await nrel_cache.aget(cache_key)
        if cached:
            return cached
        if not self.api_key:
            return None

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    f"{self.base}/wind-toolkit/v2/wind/wtk-srw-download.json",
                    params={
                        "api_key": self.api_key,
                        "wkt": f"POINT({lon} {lat})",
                        "height": height_m,
                    },
                )
                if r.status_code != 200:
                    return None
                payload = r.json()
        except Exception as e:
            logger.warning(f"NREL wind error at {lat},{lon}: {e}")
            return None

        result = {
            "wind_speed_ms": payload.get("outputs", {}).get("wind_speed_ms"),
            "capacity_factor": payload.get("outputs", {}).get("capacity_factor"),
            "source": "NREL WindToolkit",
        }
        await nrel_cache.aset(cache_key, result)
        return result

    async def solar_resource(self, lat: float, lon: float) -> Optional[dict]:
        """Return annual GHI/DNI/DIF for a point."""
        cache_key = f"solar:{lat:.3f}:{lon:.3f}"
        cached = await nrel_cache.aget(cache_key)
        if cached:
            return cached
        if not self.api_key:
            return None
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    f"{self.base}/solar/solar_resource/v1.json",
                    params={"api_key": self.api_key, "lat": lat, "lon": lon},
                )
                if r.status_code != 200:
                    return None
                payload = r.json()
        except Exception as e:
            logger.warning(f"NREL solar error at {lat},{lon}: {e}")
            return None

        out = payload.get("outputs", {})
        result = {
            "avg_ghi": _avg(out.get("avg_ghi", {})),
            "avg_dni": _avg(out.get("avg_dni", {})),
            "avg_lat_tilt": _avg(out.get("avg_lat_tilt", {})),
            "source": "NREL Solar Resource",
        }
        await nrel_cache.aset(cache_key, result)
        return result

    async def utility_rates(self, lat: float, lon: float) -> Optional[dict]:
        """Return utility commercial / industrial rates at a point."""
        cache_key = f"rates:{lat:.3f}:{lon:.3f}"
        cached = await nrel_cache.aget(cache_key)
        if cached:
            return cached
        if not self.api_key:
            return None
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    f"{self.base}/utility_rates/v3.json",
                    params={"api_key": self.api_key, "lat": lat, "lon": lon},
                )
                if r.status_code != 200:
                    return None
                payload = r.json()
        except Exception as e:
            logger.warning(f"NREL utility rates error at {lat},{lon}: {e}")
            return None

        out = payload.get("outputs", {})
        result = {
            "industrial_rate_usd_kwh": out.get("industrial"),
            "commercial_rate_usd_kwh": out.get("commercial"),
            "utility_name": out.get("utility_name"),
            "source": "NREL Utility Rates",
        }
        await nrel_cache.aset(cache_key, result)
        return result


def _avg(payload: dict) -> Optional[float]:
    if not payload or "annual" not in payload:
        return None
    try:
        return float(payload["annual"])
    except (TypeError, ValueError):
        return None


nrel_client = NRELClient()
