"""
U.S. Energy Information Administration (EIA) Open Data v2 client. The
broadest, lowest-cost public data source the Grid Intelligence agent
queries for region context.

Docs: https://www.eia.gov/opendata/documentation.php
"""
import asyncio
from typing import Optional

import httpx

from backend.config import settings
from backend.utils.cache import eia_cache
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class EIAClient:
    def __init__(self):
        self.base = settings.eia_base_url
        self.api_key = settings.eia_api_key

    def _params(self, extra: dict) -> dict:
        p = {"api_key": self.api_key, **extra}
        return p

    async def hourly_demand(self, ba_code: str, max_hours: int = 168) -> list[dict]:
        """Return hourly demand (MWh) for a Balancing Authority over the last week."""
        cache_key = f"hourly_demand:{ba_code}:{max_hours}"
        cached = await eia_cache.aget(cache_key)
        if cached:
            return cached

        if not self.api_key:
            logger.info("EIA: no api key — returning empty demand series")
            return []

        params = self._params({
            "frequency": "hourly",
            "data[0]": "value",
            "facets[respondent][]": ba_code,
            "facets[type][]": "D",
            "length": max_hours,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
        })
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    f"{self.base}/electricity/rto/region-data/data",
                    params=params,
                )
                r.raise_for_status()
                series = r.json().get("response", {}).get("data", [])
        except Exception as e:
            logger.warning(f"EIA hourly demand failed for {ba_code}: {e}")
            return []

        await eia_cache.aset(cache_key, series)
        return series

    async def generation_mix(self, ba_code: str) -> list[dict]:
        """
        Return latest generation by fuel type for a BA.
        Shape: [{fueltype, value_mwh, period}, ...]
        """
        cache_key = f"gen_mix:{ba_code}"
        cached = await eia_cache.aget(cache_key)
        if cached:
            return cached

        if not self.api_key:
            return []

        params = self._params({
            "frequency": "hourly",
            "data[0]": "value",
            "facets[respondent][]": ba_code,
            "facets[type][]": "NG",   # net generation
            "length": 200,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
        })
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    f"{self.base}/electricity/rto/fuel-type-data/data",
                    params=params,
                )
                r.raise_for_status()
                series = r.json().get("response", {}).get("data", [])
        except Exception as e:
            logger.warning(f"EIA generation mix failed for {ba_code}: {e}")
            return []

        await eia_cache.aset(cache_key, series)
        return series

    async def lmp_summary(self, region: str) -> Optional[dict]:
        """Return a recent LMP summary for a region (avg, p95)."""
        cache_key = f"lmp_summary:{region}"
        cached = await eia_cache.aget(cache_key)
        if cached:
            return cached
        if not self.api_key:
            return None
        try:
            params = self._params({
                "frequency": "monthly",
                "data[0]": "price",
                "facets[respondent][]": region,
                "length": 12,
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
            })
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    f"{self.base}/electricity/retail-sales/data",
                    params=params,
                )
                if r.status_code != 200:
                    return None
                rows = r.json().get("response", {}).get("data", [])
        except Exception as e:
            logger.warning(f"EIA LMP summary error: {e}")
            return None

        prices = [row.get("price") for row in rows if row.get("price") is not None]
        if not prices:
            return None
        summary = {
            "region": region,
            "avg_lmp_cents_kwh": round(sum(prices) / len(prices), 3),
            "min_lmp_cents_kwh": round(min(prices), 3),
            "max_lmp_cents_kwh": round(max(prices), 3),
            "samples": len(prices),
        }
        await eia_cache.aset(cache_key, summary)
        return summary


eia_client = EIAClient()
