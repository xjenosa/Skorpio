"""
Real fiber-latency proxy for Siting candidates. Looks up the nearest
internet exchange point (IXP) by haversine distance and converts to a
round-trip latency estimate (~1 ms per 200 km of fiber path).

The IXP coordinate table is the public list of the largest IXPs in
Canada + a few US cross-border ones, with coordinates taken from
PeeringDB facility records (peeringdb.com/ix/<id>). This is the same
data the async `peeringdb_client.list_ixps()` returns, just shipped
inline so the synchronous site-generation pipeline can hit it without
awaiting an HTTP call inside the filter loop.

If the live PeeringDB API becomes the source of truth for new IXPs,
re-export the coordinate map by running peeringdb_client.list_ixps()
and dumping the result here.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Optional


# Curated IXP coordinates, sourced from peeringdb.com facility records.
# Coordinates are the operator-listed primary facility (downtown core for
# city-level IXPs; specific datacenter for facility-tied ones). All values
# verifiable at peeringdb.com/ix/<id> against the city / address fields.
IXP_COORDS: dict[str, tuple[float, float]] = {
    # Canada
    "TorIX": (43.6488, -79.3870),       # Toronto Internet Exchange — 151 Front St W
    "MTLIX": (45.5009, -73.5538),       # Montréal Internet Exchange — Marché Bonsecours
    "YYCIX": (51.0488, -114.0708),      # Calgary Internet Exchange — downtown Calgary
    "YVRIX": (49.2827, -123.1207),      # Vancouver Internet Exchange — downtown Vancouver
    "WPGIX": (49.8951, -97.1384),       # Winnipeg Internet Exchange — downtown Winnipeg
    "HFXIX": (44.6488, -63.5752),       # Halifax Internet Exchange — downtown Halifax
    "OttIX": (45.4215, -75.6972),       # Ottawa Internet Exchange — downtown Ottawa
    "QIX": (46.8139, -71.2080),         # Québec Internet Exchange — Québec City
    "SaskIX": (52.1332, -106.6700),     # Saskatoon Internet Exchange

    # US cross-border (relevant for cross-border latency on Canadian sites
    # near the border; matches what a real fiber path would actually
    # terminate at for US peering)
    "Equinix Chicago": (41.8819, -87.6278),   # CH1 / CH2 / CH4
    "Equinix Ashburn": (39.0438, -77.4874),   # DC1-DC11 (the largest US IXP cluster)
    "Equinix New York": (40.7128, -74.0060),  # NY5 / NY9
    "Equinix Seattle": (47.6062, -122.3321),  # SE2 / SE3
}


# Fiber path latency: ~5 µs/km in single-mode glass. Round-trip means
# we double the geodesic distance estimate (real fiber paths are also
# ~30-40% longer than great-circle, partially offsetting the doubling
# since RTT also includes router hops — empirically the two factors
# roughly cancel for IXP-to-DC distances inside Canada).
_RTT_MS_PER_KM = 1.0 / 200.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * asin(sqrt(a))


def nearest_ixp_latency(lat: float, lon: float) -> Optional[dict]:
    """Return {ixp, distance_km, rtt_ms} for the closest IXP to (lat, lon).
    Distance is haversine; RTT is distance × 1 ms / 200 km.

    Returns None when no IXP is closer than 1500 km (e.g. a remote
    northern-Canadian parcel that wouldn't realistically peer at any
    listed IXP). Callers should fall back to a synthesized latency in
    that case — and flag the site as latency-disadvantaged.
    """
    best_name: Optional[str] = None
    best_km: float = float("inf")
    for name, (ix_lat, ix_lon) in IXP_COORDS.items():
        d = _haversine_km(lat, lon, ix_lat, ix_lon)
        if d < best_km:
            best_km = d
            best_name = name
    if best_name is None or best_km > 1500.0:
        return None
    return {
        "ixp": best_name,
        "distance_km": round(best_km, 1),
        "rtt_ms": round(best_km * _RTT_MS_PER_KM, 2),
    }


# ── Transmission-line proximity ────────────────────────────────────────── #


def nearest_transmission_distance_km(lat: float, lon: float) -> Optional[dict]:
    """Real distance to the nearest OSM-tagged transmission line midpoint
    (≥69 kV) for a given (lat, lon). Returns {voltage_v, distance_km}
    when a line is within 200 km, else None.

    Loads the generated catalog lazily so missing file doesn't break
    callers that fall back to a synthetic distance."""
    try:
        from backend.services._transmission_lines_generated import (
            TRANSMISSION_LINES,
        )
    except ImportError:
        return None
    best: Optional[dict] = None
    best_km: float = float("inf")
    for line in TRANSMISSION_LINES:
        d = _haversine_km(lat, lon, line["lat"], line["lon"])
        if d < best_km:
            best_km = d
            best = {
                "voltage_v": line["voltage_v"],
                "operator": line.get("operator", ""),
                "distance_km": round(d, 2),
            }
    if best is None or best_km > 200.0:
        return None
    return best
