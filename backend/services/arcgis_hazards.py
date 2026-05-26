"""
Real Canadian climate-hazard exposure queries for the Investment pipeline.

Hits two anonymous public ArcGIS REST endpoints — no Esri credentials,
no credit cost:

  - NRCan Historical Flood Events (geo.ca MapServer): point-radius
    query returning the number of recorded floods within N km of a
    grid asset. We use that count, divided by the years of record
    coverage, as an empirical annual probability — replacing the
    synthesized province × asset-type heuristic in climate_hazards.py.
  - Esri Canada / CIFFC Active Wildfire Perimeters (FeatureServer):
    point-in-polygon query asking whether the asset's coordinate is
    currently inside an active wildfire perimeter. A True hit pushes
    the wildfire annual probability to a near-certainty for that
    asset; a clean miss leaves it at the heuristic baseline.

Both endpoints are queried over HTTPS with a short connection budget
and a per-process result cache. Any failure (network, throttling,
500) silently returns None so the caller can keep its synthesized
value rather than crash the pipeline.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from backend.utils.cache import DiskCache
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# ── Endpoints ─────────────────────────────────────────────────────────── #

# NRCan / geo.ca Historical Flood Events layer 0. WKID 3978 source SR,
# but the query endpoint accepts inSR=4326 (WGS84 lat/lon) and projects
# server-side, so we never have to ship coordinates in 3978 metres.
_FLOOD_URL = (
    "https://maps-cartes.services.geo.ca/server_serveur/rest/services/"
    "NRCan/historical_flood_event_fr/MapServer/0/query"
)

# CWFIS WFS — the NRCan public GeoServer that hosts the upstream
# wildfire layers Esri Canada catalogs in Living Atlas. We use the
# National Fire Database point layer (large fires ≥200 ha, 1970-2024)
# as the historical-frequency source, paralleling how we use NRCan's
# Historical Flood Events layer above. No authentication required.
_WILDFIRE_WFS = "https://cwfis.cfs.nrcan.gc.ca/geoserver/wfs"
_WILDFIRE_TYPENAME = "public:NFDB_point"

# Years covered by the NFDB point layer (1970-2024). Used to convert
# "fires within radius" into an empirical annual probability, same
# pattern as the flood calculation above.
_NFDB_YEARS_OF_RECORD = 55

# Search radius for the wildfire count. Wider than the flood radius
# because wildfire footprints (and their grid impact via smoke /
# transmission threat) extend much further than the immediate burn.
_WILDFIRE_RADIUS_KM = 50

# Years of record coverage for the NRCan HFE dataset (1696 → 2025).
# Used to convert "events within radius" into an empirical annual
# probability. Capped at 100 in the rate calc because the bulk of the
# record is sparse pre-1900, and treating the full 329 years as
# uniform would severely understate modern frequencies.
_HFE_YEARS_OF_RECORD = 100

# Radius around each asset that counts as "flood-exposed". 25 km is a
# loose proxy for "in the same hydrological context as past events" —
# tighter than a province-wide rate, looser than a strict watershed
# boundary which we don't have in this query.
_FLOOD_RADIUS_KM = 25


# Long TTL — the historical layer changes weekly at most, active
# wildfires move hourly during fire season but for a hackathon demo a
# 1-hour cache is plenty and keeps repeated runs free of network cost.
_hazard_cache = DiskCache("arcgis_hazards", ttl_hours=1)


# ── Public API ────────────────────────────────────────────────────────── #


async def historical_flood_count(
    lat: float,
    lon: float,
    radius_km: float = _FLOOD_RADIUS_KM,
) -> Optional[int]:
    """Number of recorded historical flood events within radius_km of (lat, lon).

    Returns the raw count, or None when the query fails. Anonymous
    public NRCan endpoint, no credentials consumed.
    """
    cache_key = f"flood_count:{round(lat,4)}:{round(lon,4)}:{int(radius_km)}"
    cached = await _hazard_cache.aget(cache_key)
    if cached is not None:
        return int(cached)

    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "distance": str(radius_km),
        "units": "esriSRUnit_Kilometer",
        "returnCountOnly": "true",
        "f": "json",
    }
    count = await _get_count(_FLOOD_URL, params, label="flood")
    if count is not None:
        await _hazard_cache.aset(cache_key, count)
    return count


async def historical_wildfire_count(
    lat: float,
    lon: float,
    radius_km: float = _WILDFIRE_RADIUS_KM,
) -> Optional[int]:
    """Count of NFDB large-fire records within radius_km of (lat, lon).

    Hits NRCan's CWFIS WFS GeoServer (anonymous, public). The NFDB
    point layer records every large (≥200 ha) wildfire in Canada from
    1970 onward — used here as an empirical proxy for wildfire
    exposure at the asset's location, paralleling the flood query
    above. Returns None on failure so the caller keeps its baseline.
    """
    cache_key = f"wildfire_count:{round(lat,4)}:{round(lon,4)}:{int(radius_km)}"
    cached = await _hazard_cache.aget(cache_key)
    if cached is not None:
        return int(cached)

    # The NFDB layer's geometry is stored in EPSG:3978 (Canada Lambert
    # projected metres), so a WFS bbox in lat/lon needs server-side
    # reprojection — which CWFIS's GeoServer doesn't honour reliably
    # for this layer (returns 0 every time). Pivot to a CQL filter on
    # the layer's own LATITUDE / LONGITUDE attribute columns instead:
    # works in the layer's native attribute space without any
    # reprojection at all. Cosine-compensated lon delta keeps the
    # bounding window roughly square at high latitudes.
    import math
    lat_deg = radius_km / 111.0
    lon_deg = radius_km / max(1.0, 111.0 * math.cos(math.radians(lat)))
    min_lat, max_lat = lat - lat_deg, lat + lat_deg
    min_lon, max_lon = lon - lon_deg, lon + lon_deg
    cql = (
        f"LATITUDE BETWEEN {min_lat} AND {max_lat} "
        f"AND LONGITUDE BETWEEN {min_lon} AND {max_lon}"
    )

    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        # WFS 2.0 uses `typeNames` (plural); 1.0 used `typeName`. The
        # singular form silently returns zero hits against this layer.
        "typeNames": _WILDFIRE_TYPENAME,
        "CQL_FILTER": cql,
        "resultType": "hits",
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(_WILDFIRE_WFS, params=params, timeout=15)
            resp.raise_for_status()
            text = resp.text
    except httpx.HTTPError as exc:
        logger.warning("CWFIS WFS wildfire query failed: %s", exc)
        return None

    # WFS GetFeature with resultType=hits returns XML with a
    # numberMatched attribute on wfs:FeatureCollection, even when
    # the body is otherwise empty. Parse it with a permissive regex
    # rather than pulling in an XML library for one attribute.
    import re
    m = re.search(r'numberMatched=["\'](\d+)["\']', text)
    if not m:
        logger.warning("CWFIS WFS wildfire response missing numberMatched: %s", text[:200])
        return None
    count = int(m.group(1))
    await _hazard_cache.aset(cache_key, count)
    return count


async def empirical_wildfire_probability(lat: float, lon: float) -> Optional[float]:
    """Annual probability proxy: historical_wildfire_count / years_of_record."""
    count = await historical_wildfire_count(lat, lon)
    if count is None:
        return None
    rate = count / _NFDB_YEARS_OF_RECORD
    return float(min(0.95, rate))


async def empirical_flood_probability(lat: float, lon: float) -> Optional[float]:
    """Annual probability proxy: historical_flood_count / years_of_record.

    Capped at 0.95 so the optimizer never sees a deterministic
    inevitability that would distort ROI ranking.
    """
    count = await historical_flood_count(lat, lon)
    if count is None:
        return None
    rate = count / _HFE_YEARS_OF_RECORD
    return float(min(0.95, rate))


# ── Internals ─────────────────────────────────────────────────────────── #


async def _get_count(url: str, params: dict, *, label: str) -> Optional[int]:
    """Shared GET-and-parse for both endpoints. Returns int or None."""
    try:
        async with httpx.AsyncClient() as client:
            return await _get_count_with_client(client, url, params, label=label)
    except Exception as exc:
        logger.warning("ArcGIS hazard %s outer error: %s", label, exc)
        return None


async def _get_count_with_client(
    client: httpx.AsyncClient,
    url: str,
    params: dict,
    *,
    label: str,
) -> Optional[int]:
    """Like _get_count but reuses an existing httpx client (token flow)."""
    try:
        resp = await client.get(url, params=params, timeout=15)
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("ArcGIS hazard %s query failed: %s", label, exc)
        return None

    if "error" in body:
        logger.warning(
            "ArcGIS hazard %s query returned error: %s",
            label, body["error"].get("message"),
        )
        return None

    count = body.get("count")
    if count is None:
        logger.debug("ArcGIS hazard %s query returned no count field: %s", label, body)
        return None
    return int(count)
