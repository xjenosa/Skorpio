"""
Electricity Maps client — real-time grid carbon intensity. When a
specific ISO snapshot is missing, we fall back to a high-quality
predictive surface. Electricity Maps gives us hourly carbon intensity
forecasts indexed by BA code or country.

Docs: https://api-portal.electricitymaps.com/
"""
import re
from pathlib import Path
from typing import Optional

import httpx

from backend.config import settings
from backend.utils.cache import grid_cache
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class ElectricityMapsClient:
    def __init__(self):
        self.base = settings.electricitymaps_base_url
        self.api_key = settings.electricitymaps_api_key
        self.snapshot_dir = settings.transmission_dir
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    async def get_carbon_intensity(self, zone: str) -> Optional[dict]:
        """Return current carbon intensity (gCO₂eq/kWh) for a zone."""
        if not re.match(r"^[A-Za-z0-9\-_]+$", zone):
            logger.warning(f"Invalid ElectricityMaps zone code: {zone}")
            return None
        cache_key = f"carbon:{zone}"
        cached = await grid_cache.aget(cache_key)
        if cached:
            return cached
        if not self.api_key:
            return None
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(
                    f"{self.base}/carbon-intensity/latest",
                    params={"zone": zone},
                    headers={"auth-token": self.api_key},
                )
                if r.status_code != 200:
                    return None
                payload = r.json()
        except Exception as e:
            logger.warning(f"ElectricityMaps carbon intensity error: {e}")
            return None

        result = {
            "zone": payload.get("zone", zone),
            "datetime": payload.get("datetime"),
            "g_co2_per_kwh": payload.get("carbonIntensity"),
            "source": "ElectricityMaps",
        }
        await grid_cache.aset(cache_key, result)
        return result

    async def get_power_breakdown(self, zone: str) -> Optional[dict]:
        """Generation breakdown by fuel type for the current hour."""
        cache_key = f"breakdown:{zone}"
        cached = await grid_cache.aget(cache_key)
        if cached:
            return cached
        if not self.api_key:
            return None
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(
                    f"{self.base}/power-breakdown/latest",
                    params={"zone": zone},
                    headers={"auth-token": self.api_key},
                )
                if r.status_code != 200:
                    return None
                payload = r.json()
        except Exception as e:
            logger.warning(f"ElectricityMaps breakdown error: {e}")
            return None

        await grid_cache.aset(cache_key, payload)
        return payload

    async def get_snapshot(self, zone: str) -> Optional[str]:
        """
        Persist a copy of the latest carbon-intensity payload to disk so the
        Placement Scoring engine has a deterministic on-disk input.
        Returns the local file path.
        """
        payload = await self.get_carbon_intensity(zone)
        if not payload:
            return None
        path = self.snapshot_dir / f"EM-{zone}.json"
        try:
            path.write_text(_to_json(payload))
            return str(path)
        except Exception as e:
            logger.warning(f"ElectricityMaps snapshot write failed: {e}")
            return None


def _to_json(payload: dict) -> str:
    import json
    return json.dumps(payload, indent=2)


electricitymaps_client = ElectricityMapsClient()
