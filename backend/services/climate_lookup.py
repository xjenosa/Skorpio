"""
Nearest-station HDD lookup over the generated ECCC Climate Normals
1981-2010 list. Used by statscan.py to override the province-default HDD
for an FSA with the actual closest station's value.

The dataset is small (~640 stations) so we don't index — a linear scan with
the haversine formula returns in microseconds.
"""

from __future__ import annotations

from functools import lru_cache
from math import asin, cos, radians, sin, sqrt

from backend.services._hdd_stations_generated import HDD_STATIONS

# Soft cap on how far a "nearby" station can be before we refuse the match.
# Above this, the province average is more honest than picking a far-away
# coastal/montane station with a wildly different climate.
MAX_DISTANCE_KM = 200.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (sin(dlat / 2) ** 2
         + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2)
    return 2 * R * asin(sqrt(a))


def nearest_hdd18(lat: float, lon: float) -> dict | None:
    """Return {name, province, climate_id, hdd18_annual, distance_km} for
    the closest ECCC normals station within MAX_DISTANCE_KM, else None."""
    best: tuple[float, dict] | None = None
    for s in HDD_STATIONS:
        d = _haversine_km(lat, lon, s["lat"], s["lon"])
        if best is None or d < best[0]:
            best = (d, s)
    if best is None or best[0] > MAX_DISTANCE_KM:
        return None
    d, s = best
    return {
        "name": s["name"],
        "province": s["province"],
        "climate_id": s["climate_id"],
        "hdd18_annual": s["hdd18_annual"],
        "distance_km": round(d, 1),
    }


@lru_cache(maxsize=2048)
def cached_hdd18(lat_round: float, lon_round: float) -> dict | None:
    """Same as nearest_hdd18 but cached at FSA-centroid resolution (~1 km).
    Round to 2 decimal places before calling to hit the cache."""
    return nearest_hdd18(lat_round, lon_round)
