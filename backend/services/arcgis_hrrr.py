"""
ArcGIS Living Atlas — NOAA HRRR short-range forecast.

Provides forecasted temperature for the next 18-24 hours at high spatial
resolution. Used to pair the simulated cold-event envelope on a Winter
Peak report with the *actual* near-term forecast for the city: "Tonight's
forecasted low is -7°C. This stress test models a peak at -25°C."

Public Esri-hosted feature service — verify the layer URL in Living Atlas
before relying on it in a demo. Fails-soft to None on any layer or parse
issue.
"""
from __future__ import annotations

from typing import Optional

import httpx

from backend.config import settings
from backend.utils.cache import weather_cache
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# City centroids (lat, lon), shared shape with arcgis_rtma.
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


async def fetch_18h_forecast(city: str) -> Optional[dict]:
    """Return the forecasted minimum / maximum temperature for the next
    ~18 hours at a city centroid.

    Result shape:
        {
            "city": <str>,
            "forecast_low_c": <float>,        # min over next 18h
            "forecast_high_c": <float>,       # max over next 18h
            "forecast_horizon_hours": <int>,
            "source": "ArcGIS Living Atlas — NOAA HRRR",
        }

    Returns None if the layer doesn't expose hourly forecast records for
    the queried point.
    """
    key = city.lower().split(",")[0].strip()
    point = _CITY_POINT.get(key)
    if not point:
        return None

    cache_key = f"arcgis-hrrr:{key}"
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
        # HRRR exposes a record per forecast hour; pull enough to cover
        # the rolling 18h window.
        "resultRecordCount": "24",
        "orderByFields": "ForecastHour ASC",
    }

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(settings.arcgis_hrrr_layer_url, params=params)
        if resp.status_code != 200:
            logger.warning(
                f"ArcGIS HRRR fetch returned {resp.status_code} for {city}"
            )
            return None
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(f"ArcGIS HRRR fetch failed for {city}: {exc}")
        return None

    features = payload.get("features") or []
    if not features:
        return None

    temps_c: list[float] = []
    for feat in features:
        attrs = feat.get("attributes") or {}
        t = _first_numeric(attrs, [
            "TEMP_C", "tempC", "Temperature_C", "TempC", "temp_c",
        ])
        if t is None:
            f = _first_numeric(attrs, ["TEMP_F", "tempF", "Temperature_F"])
            if f is not None:
                t = (f - 32.0) * 5.0 / 9.0
        if t is not None:
            temps_c.append(t)

    if not temps_c:
        return None

    horizon = min(18, len(temps_c))
    window = temps_c[:horizon]
    result = {
        "city": city,
        "forecast_low_c": round(min(window), 1),
        "forecast_high_c": round(max(window), 1),
        "forecast_horizon_hours": horizon,
        "source": "ArcGIS Living Atlas — NOAA HRRR",
    }
    await weather_cache.aset(cache_key, result)
    return result


def _first_numeric(d: dict, candidates: list[str]) -> Optional[float]:
    for key in candidates:
        if key in d and d[key] is not None:
            try:
                return float(d[key])
            except (TypeError, ValueError):
                continue
    return None
