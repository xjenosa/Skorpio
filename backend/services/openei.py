"""
OpenEI client. A free, loosely-curated association store the Grid
Intelligence agent queries to surface the *initial set* of candidate
utilities and tariffs for a given region.

Docs: https://openei.org/services/api/
"""
from typing import Optional

import httpx

from backend.config import settings
from backend.utils.cache import grid_cache
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class OpenEIClient:
    def __init__(self):
        self.base = settings.openei_base_url
        self.api_key = settings.openei_api_key

    async def utilities_for_region(
        self,
        iso_code: str,
        min_score: float = 0.1,
        max_results: int = 30,
    ) -> list[dict]:
        """
        Return utility-region associations.
        Falls back to a keyword search if exact match fails.
        """
        cache_key = f"openei:{iso_code}:{min_score}:{max_results}"
        cached = await grid_cache.aget(cache_key)
        if cached is not None:
            return cached

        associations: list[dict] = []
        try:
            params = {
                "version": "latest",
                "format": "json",
                "limit": max_results,
                "region": iso_code,
                "api_key": self.api_key,
            }
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(f"{self.base}/utility_companies", params=params)
                if r.status_code == 200:
                    raw = r.json().get("items", [])
                    associations = [
                        {
                            "utility_code": item.get("eia_id", ""),
                            "utility_name": item.get("name", ""),
                            "score": item.get("relevance", 0.5),
                            "iso_code": iso_code,
                            "bulletins": item.get("docket_ids", []),
                            "sources": item.get("source", ""),
                        }
                        for item in raw
                        if item.get("relevance", 0) >= min_score
                        and item.get("name")
                    ]
                elif r.status_code == 404:
                    logger.info(f"OpenEI: no results for '{iso_code}'")
                elif r.status_code in (401, 403):
                    logger.warning(f"OpenEI API auth failure (status {r.status_code})")
                else:
                    logger.warning(f"OpenEI API returned {r.status_code}")
        except httpx.RequestError as e:
            logger.warning(f"OpenEI request failed: {e}")

        associations.sort(key=lambda x: x["score"], reverse=True)
        await grid_cache.aset(cache_key, associations)
        return associations

    async def get_region_info(self, iso_code: str) -> Optional[dict]:
        """Return region metadata from OpenEI."""
        try:
            params = {"region": iso_code, "format": "json", "api_key": self.api_key}
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(f"{self.base}/regions", params=params)
                if r.status_code == 200:
                    results = r.json().get("items", [])
                    return results[0] if results else None
        except Exception as e:
            logger.warning(f"OpenEI region info error: {e}")
        return None


openei_client = OpenEIClient()
