"""
ArcGIS Living Atlas — MODIS daily snow cover.

Returns fractional snow cover (0.0-1.0) at the city centroid. Doesn't
drive the simulator — adds context to the Winter Peak report ("there's
already 14 cm equivalent snow on the ground, so existing heating
demand is already elevated").

Public Esri-hosted feature service. Fails-soft to None on layer/parse
issues.
"""
from __future__ import annotations

from typing import Optional

import httpx

from backend.config import settings
from backend.utils.cache import weather_cache
from backend.utils.logger import get_logger

logger = get_logger(__name__)


_CITY_POINT: dict[str, tuple[float, float]] = {
    "mississauga": (43.5890, -79.6441),
    "toronto":     (43.6532, -79.3832),
    "ottawa":      (45.4215, -75.6972),
    "edmonton":    (53.5461, -113.4938),
    "montreal":    (45.5019, -73.5674),
    "brampton":    (43.7315, -79.7624),
    "hamilton":    (43.2557, -79.8711),
    "vaughan":     (43.8361, -79.4985),
    "markham":     (43.8561, -79.3370),
    "vancouver":   (49.2827, -123.1207),
    "calgary":     (51.0447, -114.0719),
    "winnipeg":    (49.8951, -97.1384),
    "halifax":     (44.6488, -63.5752),
}


async def fetch_snow_cover(city: str) -> Optional[dict]:
    """Return fractional snow cover at a city centroid.

    Result shape:
        {
            "city": <str>,
            "snow_cover_fraction": <float>,  # 0.0-1.0
            "snow_cover_pct": <float>,       # 0-100 (convenience)
            "observed_at": <iso>,
            "source": "ArcGIS Living Atlas — MODIS Snow Cover",
        }
    """
    key = city.lower().split(",")[0].strip()
    point = _CITY_POINT.get(key)
    if not point:
        return None

    cache_key = f"arcgis-snow:{key}"
    cached = await weather_cache.aget(cache_key)
    if cached is not None:
        return cached

    lat, lon = point
    params = {
        "f": "json",
        "where": "1=1",
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
        "resultRecordCount": "1",
    }

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(settings.arcgis_snow_cover_layer_url, params=params)
        if resp.status_code != 200:
            logger.warning(
                f"ArcGIS snow-cover fetch returned {resp.status_code} for {city}"
            )
            return None
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(f"ArcGIS snow-cover fetch failed for {city}: {exc}")
        return None

    features = payload.get("features") or []
    if not features:
        return None
    attrs = features[0].get("attributes") or {}

    raw = None
    for k in ("SnowCover", "snowCover", "SNOW_COVER", "snow_cover",
              "NDSI_Snow_Cover", "fraction", "value"):
        if k in attrs and attrs[k] is not None:
            try:
                raw = float(attrs[k])
                break
            except (TypeError, ValueError):
                continue
    if raw is None:
        return None

    # Different layers report snow cover either as 0-1 (fraction) or
    # 0-100 (percent). Normalize to fraction.
    fraction = raw / 100.0 if raw > 1.0 else raw
    fraction = max(0.0, min(1.0, fraction))

    observed_at = (
        attrs.get("OBSERVED_AT")
        or attrs.get("observation_date")
        or attrs.get("DATE")
    )

    result = {
        "city": city,
        "snow_cover_fraction": round(fraction, 3),
        "snow_cover_pct": round(fraction * 100.0, 1),
        "observed_at": observed_at,
        "source": "ArcGIS Living Atlas — MODIS Snow Cover",
    }
    await weather_cache.aset(cache_key, result)
    return result
