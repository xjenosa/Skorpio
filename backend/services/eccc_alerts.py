"""
ECCC active weather alerts client.

Queries Environment and Climate Change Canada's GeoMet OGC API for any
*active* public weather alerts (winter storm warnings, extreme cold
warnings, freezing rain, etc.) intersecting a city's bounding box.

Surfaces a live chip on the Winter Peak report and powers the
`/api/eccc/alerts` endpoint for the dashboard.

Public, no key required. Source:
  https://api.weather.gc.ca/openapi
  https://api.weather.gc.ca/collections/alerts-realtime
"""
from __future__ import annotations

from typing import Optional

import httpx

from backend.config import settings
from backend.utils.cache import weather_cache
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# Bounding box (lon_min, lat_min, lon_max, lat_max) per supported city, used
# to query ECCC's alerts collection for any active alerts overlapping the
# service territory. Boxes are intentionally wide (~40 km) so an alert
# polygon that brushes the city still registers.
_CITY_BBOX: dict[str, tuple[float, float, float, float]] = {
    "mississauga": (-79.95, 43.40, -79.40, 43.85),
    "toronto":     (-79.65, 43.55, -79.10, 43.85),
    "ottawa":      (-76.00, 45.20, -75.40, 45.60),
    "edmonton":    (-113.80, 53.35, -113.20, 53.75),
    "montreal":    (-73.95, 45.30, -73.40, 45.75),
    "brampton":    (-79.85, 43.60, -79.55, 43.85),
    "hamilton":    (-80.05, 43.05, -79.65, 43.40),
    "vaughan":     (-79.70, 43.70, -79.40, 43.95),
    "markham":     (-79.55, 43.80, -79.20, 44.00),
    "vancouver":   (-123.30, 49.15, -122.95, 49.40),
    "calgary":     (-114.30, 50.85, -113.85, 51.20),
    "winnipeg":    (-97.40, 49.75, -96.90, 50.05),
    "halifax":     (-63.80, 44.55, -63.40, 44.80),
}


async def fetch_active_alerts(city: str) -> Optional[dict]:
    """Return active ECCC alerts for a city's bounding box.

    Result shape:
        {
            "city": <str>,
            "alerts": [
                {"event": "Extreme cold warning", "severity": "Severe",
                 "headline": "...", "effective": "<iso>", "expires": "<iso>"},
                ...
            ],
            "count": <int>,
            "source": "ECCC GeoMet alerts-realtime"
        }

    Returns None on network error / unparseable response. Returns a dict
    with `count: 0` and an empty alerts list when the feed responds
    successfully with no active alerts — that's a legitimate "all clear"
    that should still light the chip green to show the feed is live.
    """
    key = city.lower().split(",")[0].strip()
    bbox = _CITY_BBOX.get(key)
    if not bbox:
        logger.debug(f"No bbox configured for ECCC alerts lookup: {city}")
        return None

    cache_key = f"eccc-alerts:{key}"
    cached = await weather_cache.aget(cache_key)
    if cached is not None:
        return cached

    bbox_param = ",".join(f"{v:.4f}" for v in bbox)
    url = f"{settings.eccc_base_url}/collections/alerts-realtime/items"
    params = {"bbox": bbox_param, "f": "json", "limit": 25}

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(url, params=params)
        if resp.status_code != 200:
            logger.warning(
                f"ECCC alerts fetch returned {resp.status_code} for {city}"
            )
            return None
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(f"ECCC alerts fetch failed for {city}: {exc}")
        return None

    features = payload.get("features") or []
    alerts: list[dict] = []
    for feat in features:
        props = feat.get("properties") or {}
        alerts.append({
            "event": props.get("event") or props.get("alert_type") or "Alert",
            "severity": props.get("severity"),
            "headline": props.get("headline") or props.get("description"),
            "effective": props.get("effective") or props.get("onset"),
            "expires": props.get("expires"),
            "area_desc": props.get("area_desc") or props.get("areaDesc"),
        })

    result = {
        "city": city,
        "alerts": alerts,
        "count": len(alerts),
        "source": "ECCC GeoMet alerts-realtime",
    }
    # Cached against the shared weather DiskCache (3h TTL). Alerts shift in
    # real time but the cache window is small enough that demo viewers
    # still see "active alert" or "all clear" within a reasonable freshness.
    await weather_cache.aset(cache_key, result)
    return result
