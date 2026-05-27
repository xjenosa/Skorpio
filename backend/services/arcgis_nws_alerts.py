"""
ArcGIS Living Atlas — NWS Active Watches & Warnings.

Complement to ECCC's Canadian-side alerts feed. The NWS layer covers the
continental US with cross-border polygons that occasionally extend into
Canadian border regions during severe-weather events, so it adds genuine
signal even for Ontario / Quebec scenarios when active.

Public Esri-hosted feature service — no token required. Verify the layer
URL in Esri Living Atlas before relying on the chip in a demo; the
service fails-soft to None if the layer doesn't return any features.
"""
from __future__ import annotations

from typing import Optional

import httpx

from backend.config import settings
from backend.utils.cache import weather_cache
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# Same bbox map as eccc_alerts so we can compare apples-to-apples across
# the two feeds. Kept as a separate copy on purpose: the two services are
# free to diverge in coverage (NWS may want a wider bbox to catch
# cross-border polygons, ECCC stays tighter).
_CITY_BBOX: dict[str, tuple[float, float, float, float]] = {
    "mississauga": (-80.10, 43.30, -79.30, 43.95),
    "toronto":     (-79.80, 43.45, -79.00, 43.95),
    "ottawa":      (-76.10, 45.10, -75.30, 45.70),
    "edmonton":    (-114.00, 53.25, -113.00, 53.85),
    "montreal":    (-74.10, 45.20, -73.30, 45.85),
    "brampton":    (-80.00, 43.50, -79.40, 43.95),
    "hamilton":    (-80.20, 42.95, -79.50, 43.50),
    "vaughan":     (-79.85, 43.60, -79.25, 44.05),
    "markham":     (-79.70, 43.70, -79.05, 44.10),
    "vancouver":   (-123.50, 49.05, -122.75, 49.50),
    "calgary":     (-114.50, 50.75, -113.65, 51.30),
    "winnipeg":    (-97.60, 49.65, -96.70, 50.15),
    "halifax":     (-64.00, 44.45, -63.20, 44.90),
}


async def fetch_active_nws_alerts(city: str) -> Optional[dict]:
    """Return active NWS watches & warnings intersecting a city's bbox.

    Result shape mirrors `eccc_alerts.fetch_active_alerts`:
        {
            "city": <str>,
            "alerts": [{"event": "...", "severity": "...", ...}, ...],
            "count": <int>,
            "source": "ArcGIS Living Atlas — NWS Watches & Warnings",
        }

    Returns None on network / parse errors. Returns count=0 dict when the
    feed responds successfully with no overlap.
    """
    key = city.lower().split(",")[0].strip()
    bbox = _CITY_BBOX.get(key)
    if not bbox:
        logger.debug(f"No bbox configured for NWS alert lookup: {city}")
        return None

    cache_key = f"arcgis-nws-alerts:{key}"
    cached = await weather_cache.aget(cache_key)
    if cached is not None:
        return cached

    # Esri envelope query: pass the bbox as a geometry envelope and filter
    # to active alerts (where clause stays open since the layer is
    # already pre-filtered to active rows).
    lon_min, lat_min, lon_max, lat_max = bbox
    params = {
        "f": "json",
        "where": "1=1",
        "geometry": f"{lon_min},{lat_min},{lon_max},{lat_max}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "Event,Severity,Headline,Effective,Expires,AreaDesc",
        "returnGeometry": "false",
        "resultRecordCount": "25",
    }

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(settings.arcgis_nws_alerts_layer_url, params=params)
        if resp.status_code != 200:
            logger.warning(
                f"ArcGIS NWS alerts fetch returned {resp.status_code} for {city}"
            )
            return None
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(f"ArcGIS NWS alerts fetch failed for {city}: {exc}")
        return None

    features = payload.get("features") or []
    alerts: list[dict] = []
    for feat in features:
        attrs = feat.get("attributes") or {}
        alerts.append({
            "event": attrs.get("Event") or attrs.get("event"),
            "severity": attrs.get("Severity") or attrs.get("severity"),
            "headline": attrs.get("Headline") or attrs.get("headline"),
            "effective": attrs.get("Effective") or attrs.get("effective"),
            "expires": attrs.get("Expires") or attrs.get("expires"),
            "area_desc": attrs.get("AreaDesc") or attrs.get("areaDesc"),
        })

    result = {
        "city": city,
        "alerts": alerts,
        "count": len(alerts),
        "source": "ArcGIS Living Atlas — NWS Watches & Warnings",
    }
    await weather_cache.aset(cache_key, result)
    return result
