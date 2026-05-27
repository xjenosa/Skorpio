"""
ArcGIS Living Atlas — NOAA RTMA / NDFD current surface conditions.

Queries the Esri-hosted Living Atlas feature service for the nearest grid
cell to a city's lat/lon and returns current outdoor temperature + wind
(plus optional dewpoint / RH if the layer exposes them). Used to light up
a "Live conditions" chip on the Winter Peak report, pairing the simulated
cold-event envelope with what the weather is actually doing right now.

The exact Esri layer URL is configurable via `settings.arcgis_rtma_layer_url`
because Esri occasionally re-hosts these public layers. Verify the
endpoint in the Living Atlas portal before relying on the chip lighting
up in a demo; this module fails-soft to None if the call doesn't return
a usable feature, so a wrong URL just keeps the chip dark.

Reuses the OAuth client_credentials flow plumbed in arcgis_enrichment.py
when the layer requires an access token. Some Living Atlas weather layers
are public (no token); the module passes the token when available and
omits it otherwise.
"""
from __future__ import annotations

from typing import Optional

import httpx

from backend.config import settings
from backend.services.arcgis_enrichment import _get_access_token, is_configured
from backend.utils.cache import weather_cache
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# Lat/lon for the cities served by the Winter Peak pipeline.
# Mirrors the bbox map in eccc_alerts.py but the RTMA layer is queried by
# a single point, not a polygon.
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


async def fetch_current_conditions(city: str) -> Optional[dict]:
    """Return live surface conditions at the city centroid.

    Result shape (when the layer answers):
        {
            "city": "Mississauga",
            "temp_c": -3.2,
            "wind_kmh": 18.0,        # optional, may be None
            "observed_at": "<iso>",  # optional, may be None
            "source": "ArcGIS Living Atlas — NOAA RTMA",
        }

    Returns None when:
      - The city isn't in the centroid table
      - The configured layer URL is wrong / unreachable
      - The layer returned no features for the queried point
      - Any HTTP / JSON / parsing error
    """
    key = city.lower().split(",")[0].strip()
    point = _CITY_POINT.get(key)
    if not point:
        logger.debug(f"No centroid configured for RTMA lookup: {city}")
        return None

    cache_key = f"arcgis-rtma:{key}"
    cached = await weather_cache.aget(cache_key)
    if cached is not None:
        return cached

    lat, lon = point
    # Esri ArcGIS REST query — point-in-polygon (envelope intersection)
    # against the layer. The exact field names vary by layer; we ask for
    # all fields and pick the temperature / wind values from a small set
    # of common aliases below.
    params: dict[str, str] = {
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

    headers: dict[str, str] = {}
    if is_configured():
        # Best-effort: attach a token if we have one. Many Living Atlas
        # weather layers are public and don't require it, but a token
        # never hurts.
        async with httpx.AsyncClient() as token_client:
            token = await _get_access_token(token_client)
            if token:
                params["token"] = token

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(
                settings.arcgis_rtma_layer_url, params=params, headers=headers,
            )
        if resp.status_code != 200:
            logger.warning(
                f"ArcGIS RTMA fetch returned {resp.status_code} for {city}"
            )
            return None
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(f"ArcGIS RTMA fetch failed for {city}: {exc}")
        return None

    features = payload.get("features") or []
    if not features:
        return None
    attrs = features[0].get("attributes") or {}

    # Common field aliases across Living Atlas / NDFD / RTMA layers.
    # We accept either Celsius or Fahrenheit values; F→C converts if the
    # field name hints at it. Wind expected in km/h or m/s.
    temp_c = _first_numeric(attrs, [
        "TEMP_C", "tempC", "TempC", "temp_c", "air_temp_c",
        "TEMPERATURE", "Temperature",
    ])
    if temp_c is None:
        temp_f = _first_numeric(attrs, ["TEMP_F", "tempF", "TempF", "temp_f"])
        if temp_f is not None:
            temp_c = (temp_f - 32.0) * 5.0 / 9.0

    wind_kmh = _first_numeric(attrs, [
        "WIND_KMH", "windKmh", "WindKmh", "wind_kmh",
    ])
    if wind_kmh is None:
        wind_ms = _first_numeric(attrs, ["WIND_MS", "windMs", "wind_ms"])
        if wind_ms is not None:
            wind_kmh = wind_ms * 3.6

    observed_at = (
        attrs.get("OBSERVED_AT")
        or attrs.get("observedAt")
        or attrs.get("observation_time")
        or attrs.get("DATE")
    )

    if temp_c is None:
        # No temperature field recognized — layer schema doesn't match
        # what we expected. Surface None rather than a half-empty record.
        return None

    result = {
        "city": city,
        "temp_c": round(float(temp_c), 1),
        "wind_kmh": round(float(wind_kmh), 1) if wind_kmh is not None else None,
        "observed_at": observed_at,
        "source": "ArcGIS Living Atlas — NOAA RTMA",
    }
    await weather_cache.aset(cache_key, result)
    return result


def _first_numeric(d: dict, candidates: list[str]) -> Optional[float]:
    """Return the first numeric-looking value in `d` matching one of the
    keys in `candidates`. Used to absorb Living Atlas layer field-name
    drift across re-hostings.
    """
    for key in candidates:
        if key in d and d[key] is not None:
            try:
                return float(d[key])
            except (TypeError, ValueError):
                continue
    return None
