"""
ArcGIS / Esri GeoEnrichment client for the Neighborhood Electrification
Readiness pipeline.

Replaces the synthesized / registry-based NeighborhoodProfile fields
(households, median income, dwelling mix, dwelling age) with live
authoritative Canadian demographics pulled from Esri's GeoEnrichment
service. Falls back to None on any failure so callers can keep their
existing synthesis path as a safety net.

Auth flow:
  1. Mint a short-lived access token from the OAuth 2.0 client_credentials
     grant (settings.arcgis_client_id + settings.arcgis_client_secret).
  2. Attach the token to GeoEnrichment REST calls.
  3. Cache the token in-memory until ~5 min before its `expires_in` so we
     don't burn an extra round-trip per FSA fetch.

Cost protection:
  - Each enrich call costs Esri credits against the org's pooled
    subscription. Results are cached on disk (TTL = 30 days) so repeat
    runs for the same FSA are free.
  - A small hardcoded per-process cap (MAX_LIVE_CALLS) prevents a runaway
    pipeline from draining the org pool. Once tripped, the module
    short-circuits subsequent calls and the caller falls back to its
    synthesized path.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx

from backend.config import settings
from backend.models.electrification import DwellingMix
from backend.utils.cache import DiskCache
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# ── Hardcoded analysis variables ──────────────────────────────────────── #
# Canadian Esri Demographics variable IDs (Environics 2025 vintage,
# dataset CAN_ESRI_2025). Verified live against L5B Mississauga during
# the hackathon integration.
#
# Quirk: TOTHH / AVGHHSZ are "key fact" system fields that come back
# ONLY when no analysisVariables list is specified — passing them
# explicitly is rejected as "not defined for country 'CA'". So we make
# TWO calls per FSA (cached together): one bare default-key-facts call,
# one with the Environics codes below.
_EXTRA_VARIABLES = [
    "ECYHRIMED",      # Median household income (CAD)
    "ECYHRIAVG",      # Average household income (CAD)
    # Dwelling structure type counts (population in each type, per
    # Environics convention — used as relative weights to derive a
    # 0-1 dwelling-mix fraction since the absolute counts don't sum to
    # total households):
    "ECYSTYSING",     # Single-detached
    "ECYSTYSEMI",     # Semi-detached
    "ECYSTYROW",      # Row house
    "ECYSTYAPT",      # Apartment (all storey counts; not split in this dataset)
]

MAX_LIVE_CALLS = 25  # per-process cap; resets on backend restart
_live_call_count = 0

# ── Demo-city → StatsCan Census Subdivision (CSD) code map ────────────── #
# CSDs are the natural municipal-boundary unit for ArcGIS GeoEnrichment's
# CAN.CSD layer. Codes from StatsCan's 2021 Census geography. Add cities
# here as the demo pipeline picks up new geographies — unmatched cities
# fall through to None and the caller skips the enrichment.
_CITY_TO_CSD = {
    "mississauga":  "3521005",
    "toronto":      "3520005",
    "brampton":     "3521010",
    "hamilton":     "3525005",
    "vaughan":      "3519028",
    "markham":      "3519036",
    "ottawa":       "3506008",
    "vancouver":    "5915022",
    "burnaby":      "5915025",
    "calgary":      "4806016",
    "edmonton":     "4811061",
    "montreal":     "2466023",
    "winnipeg":     "4611040",
    "halifax":      "1209034",
}

# Long TTL — Canadian Census variables update on a 5-year cycle.
_enrichment_cache = DiskCache("arcgis_enrich", ttl_hours=24 * 30)

# FSA centroids are essentially immutable (Canada Post redraws are rare and
# the centroid barely moves), so geocode results get a year-long TTL.
_geocode_cache = DiskCache("arcgis_geocode", ttl_hours=24 * 365)

# Module-level access token cache (single httpx token, refreshed lazily).
_token_lock = asyncio.Lock()
_token_value: Optional[str] = None
_token_expires_at: float = 0.0  # epoch seconds


def is_configured() -> bool:
    """True when both OAuth credentials are present in the environment."""
    return bool(settings.arcgis_client_id and settings.arcgis_client_secret)


# ── OAuth token plumbing ──────────────────────────────────────────────── #


async def _get_access_token(client: httpx.AsyncClient) -> Optional[str]:
    """Return a valid access token, refreshing in-band if expired.

    Uses the OAuth 2.0 client_credentials grant against Esri's portal
    token endpoint. Tokens come back with `expires_in` seconds (default
    2 weeks for app-auth credentials); we refresh 5 minutes early to
    avoid races between expiry check and request emission.
    """
    global _token_value, _token_expires_at

    if not is_configured():
        return None

    now = time.time()
    if _token_value and now < _token_expires_at - 300:
        return _token_value

    async with _token_lock:
        # Re-check after acquiring the lock — another coroutine may have
        # refreshed while we were waiting.
        now = time.time()
        if _token_value and now < _token_expires_at - 300:
            return _token_value

        try:
            resp = await client.post(
                settings.arcgis_oauth_token_url,
                data={
                    "client_id": settings.arcgis_client_id,
                    "client_secret": settings.arcgis_client_secret,
                    "grant_type": "client_credentials",
                    "f": "json",
                },
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("ArcGIS token mint failed: %s", exc)
            return None

        token = payload.get("access_token")
        expires_in = int(payload.get("expires_in") or 1209600)  # 14d default
        if not token:
            logger.warning("ArcGIS token mint returned no access_token: %s", payload)
            return None

        _token_value = token
        _token_expires_at = time.time() + expires_in
        logger.info("Minted ArcGIS access token (expires in %ds)", expires_in)
        return _token_value


# ── GeoEnrichment call ────────────────────────────────────────────────── #


async def enrich_fsa(fsa: str) -> Optional[dict]:
    """Fetch enriched demographics for one Canadian FSA.

    Returns a dict shaped for the NeighborhoodProfile overlay (see
    `_extract_from_features` for the keys), or None if ArcGIS is
    unconfigured, the call fails, or the credit cap is exhausted.

    Result is cached on disk for 30 days so subsequent runs for the same
    FSA cost zero credits.
    """
    global _live_call_count

    if not is_configured():
        return None

    fsa = fsa.upper().strip()
    cache_key = f"fsa:{fsa}:v1"

    cached = await _enrichment_cache.aget(cache_key)
    if cached is not None:
        logger.debug("ArcGIS cache hit for FSA %s", fsa)
        return cached

    if _live_call_count >= MAX_LIVE_CALLS:
        logger.warning(
            "ArcGIS per-process credit cap (%d) reached — skipping live call for %s",
            MAX_LIVE_CALLS,
            fsa,
        )
        return None

    async with httpx.AsyncClient() as client:
        token = await _get_access_token(client)
        if not token:
            return None

        # Canadian FSAs are queried via the standard FSA layer in the
        # World GeoEnrichment service. The `sourceCountry`/`layer` pair
        # tells Esri to resolve the polygon server-side instead of us
        # shipping a GeoJSON shape over the wire. Country code is the
        # 2-letter `CA`; layer ID uses the 3-letter `CAN.` prefix —
        # verified live during the hackathon integration (the error
        # message for the wrong combo is misleading and conflates them).
        study_areas = [{
            "sourceCountry": "CA",
            "layer": "CAN.FSA",
            "ids": [fsa],
        }]
        common = {
            "studyAreas": _json_dumps(study_areas),
            "returnGeometry": "false",
            "f": "json",
            "token": token,
        }

        # Two parallel calls: default-key-facts (TOTHH, AVGHHSZ, TOTPOP)
        # + extended Environics variables (income, dwelling mix).
        default_resp, extra_resp = await asyncio.gather(
            client.post(settings.arcgis_geoenrichment_url, data=common, timeout=30),
            client.post(
                settings.arcgis_geoenrichment_url,
                data={**common, "analysisVariables": _json_dumps(_EXTRA_VARIABLES)},
                timeout=30,
            ),
            return_exceptions=True,
        )

        attrs: dict = {}
        for label, resp in (("default", default_resp), ("extra", extra_resp)):
            if isinstance(resp, Exception):
                logger.warning("ArcGIS %s call raised for %s: %s", label, fsa, resp)
                continue
            try:
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("ArcGIS %s response unparseable for %s: %s", label, fsa, exc)
                continue
            if "error" in payload:
                logger.warning(
                    "ArcGIS %s error for %s: code=%s message=%s",
                    label, fsa,
                    payload["error"].get("code"),
                    payload["error"].get("message"),
                )
                continue
            sub = _attrs_from_payload(payload)
            if sub:
                attrs.update(sub)

        _live_call_count += 2

        if not attrs:
            logger.warning("ArcGIS enrich for %s returned no usable features", fsa)
            return None

        extracted = _extract_fields(attrs)
        if extracted is None:
            return None

        await _enrichment_cache.aset(cache_key, extracted)
        logger.info(
            "ArcGIS enrich live for %s succeeded (call total %d/%d this process)",
            fsa,
            _live_call_count,
            MAX_LIVE_CALLS,
        )
        return extracted


# ── Response shape parsing ────────────────────────────────────────────── #


async def enrich_city(city: str) -> Optional[dict]:
    """Fetch enriched demographics for one Canadian city (Census Subdivision).

    Returns {"city_name", "households", "population", "avg_household_size"}
    or None when the city isn't in the demo CSD map / ArcGIS isn't
    configured / the call fails. Cached on disk for 30 days.
    """
    global _live_call_count

    if not is_configured():
        return None

    key = (city or "").strip().lower().split(",")[0].strip()
    csd = _CITY_TO_CSD.get(key)
    if not csd:
        return None

    cache_key = f"city:{csd}:v1"
    cached = await _enrichment_cache.aget(cache_key)
    if cached is not None:
        return cached

    if _live_call_count >= MAX_LIVE_CALLS:
        logger.warning("ArcGIS credit cap reached; skipping city enrichment for %s", city)
        return None

    async with httpx.AsyncClient() as client:
        token = await _get_access_token(client)
        if not token:
            return None
        try:
            resp = await client.post(
                settings.arcgis_geoenrichment_url,
                data={
                    "studyAreas": _json_dumps([{
                        "sourceCountry": "CA", "layer": "CAN.CSD", "ids": [csd],
                    }]),
                    "returnGeometry": "false", "f": "json", "token": token,
                },
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("ArcGIS city enrich failed for %s: %s", city, exc)
            return None

        _live_call_count += 1
        if "error" in payload:
            logger.warning(
                "ArcGIS city enrich error for %s: %s",
                city,
                payload["error"].get("message"),
            )
            return None

        attrs = _attrs_from_payload(payload) or {}
        out: dict = {}
        if (v := attrs.get("StdGeographyName")) is not None:
            out["city_name"] = v
        if (v := attrs.get("TOTPOP")) is not None:
            out["population"] = int(v)
        if (v := attrs.get("TOTHH")) is not None:
            out["households"] = int(v)
        if (v := attrs.get("AVGHHSZ")) is not None:
            out["avg_household_size"] = float(v)

        if not out:
            return None
        await _enrichment_cache.aset(cache_key, out)
        logger.info("ArcGIS city enrich for %s: %s", city, out)
        return out


async def geocode_fsa(fsa: str) -> Optional[tuple[float, float]]:
    """Live FSA → (lat, lon) lookup via the ArcGIS World Geocoding Service.

    Returns (lat, lon) or None when ArcGIS isn't configured, the credit
    cap is exhausted, or the FSA isn't resolvable. Cached on disk for a
    year so repeat lookups for the same postal prefix cost zero credits.

    Implementation note: the Geocoding Service accepts a 3-character
    Canadian FSA as the `singleLine` with `countryCode=CAN` and returns
    the FSA centroid. We constrain to `category=Postal` so we don't
    accidentally match a street or place name that happens to share the
    three letters. `forStorage=false` keeps us in the free per-month tier
    of the Geocoding service rather than the storage-billed bucket.
    """
    global _live_call_count

    if not is_configured():
        return None

    fsa = (fsa or "").upper().strip()
    if not fsa:
        return None

    cache_key = f"fsa:{fsa}:v1"
    cached = await _geocode_cache.aget(cache_key)
    if cached is not None and isinstance(cached, list) and len(cached) == 2:
        return float(cached[0]), float(cached[1])

    if _live_call_count >= MAX_LIVE_CALLS:
        logger.warning("ArcGIS credit cap reached; skipping geocode for %s", fsa)
        return None

    async with httpx.AsyncClient() as client:
        token = await _get_access_token(client)
        if not token:
            return None
        try:
            resp = await client.get(
                settings.arcgis_geocoding_url,
                params={
                    "singleLine": fsa,
                    "countryCode": "CAN",
                    "category": "Postal",
                    "outFields": "Match_addr,Addr_type",
                    "maxLocations": 1,
                    "forStorage": "false",
                    "f": "json",
                    "token": token,
                },
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("ArcGIS FSA geocode failed for %s: %s", fsa, exc)
            return None

        _live_call_count += 1

        if "error" in payload:
            logger.warning(
                "ArcGIS geocode error for %s: %s",
                fsa,
                payload["error"].get("message"),
            )
            return None

        candidates = payload.get("candidates") or []
        if not candidates:
            return None
        loc = candidates[0].get("location") or {}
        lat = loc.get("y")
        lon = loc.get("x")
        if lat is None or lon is None:
            return None

        result = (float(lat), float(lon))
        await _geocode_cache.aset(cache_key, list(result))
        logger.info(
            "ArcGIS geocode for FSA %s: %s (call total %d/%d this process)",
            fsa, result, _live_call_count, MAX_LIVE_CALLS,
        )
        return result


def _attrs_from_payload(payload: dict) -> Optional[dict]:
    """Flatten Esri's nested enrich response to a single attribute dict."""
    try:
        return payload["results"][0]["value"]["FeatureSet"][0]["features"][0]["attributes"]
    except (KeyError, IndexError, TypeError):
        return None


def _extract_fields(attrs: dict) -> Optional[dict]:
    """Map raw Esri attributes to NeighborhoodProfile overlay fields."""
    out: dict = {}

    if (v := attrs.get("TOTHH")) is not None:
        out["households"] = int(v)
    if (v := attrs.get("AVGHHSZ")) is not None:
        out["avg_household_size"] = float(v)
    # Prefer median income; fall back to average if median absent.
    if (v := attrs.get("ECYHRIMED")) is not None:
        out["median_household_income_cad"] = float(v)
    elif (v := attrs.get("ECYHRIAVG")) is not None:
        out["median_household_income_cad"] = float(v)

    # Dwelling-structure-type counts (population living in each type, per
    # the Environics convention). The absolute counts don't sum to total
    # households since some categories (multi-unit owner-occupied, etc.)
    # aren't broken out separately at the FSA level — we treat the four
    # returned categories as relative weights and normalize to 0-1
    # fractions. Anything below the sum lands in "other" so the
    # report's dwelling-mix donut still closes to 100%.
    raw_counts = {
        "single_detached": attrs.get("ECYSTYSING"),
        "semi_detached":   attrs.get("ECYSTYSEMI"),
        "row":             attrs.get("ECYSTYROW"),
        # CAN_ESRI_2025 doesn't split apartments by storey count, so
        # we lump the lot into apartment_low_rise (the more common
        # case in suburban Canadian FSAs) and leave apartment_high_rise
        # at zero. The report keeps the same donut categories.
        "apartment_low_rise": attrs.get("ECYSTYAPT"),
    }
    counts = {k: float(v) for k, v in raw_counts.items() if v is not None}
    total = sum(counts.values())
    if total > 0:
        mix = {k: v / total for k, v in counts.items()}
        out["dwelling_mix"] = DwellingMix(**mix).model_dump()

    return out or None


# ── Helpers ───────────────────────────────────────────────────────────── #


def _json_dumps(value) -> str:
    """Esri's REST endpoints want JSON-encoded form fields."""
    import json
    return json.dumps(value, separators=(",", ":"))
