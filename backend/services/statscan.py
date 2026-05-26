"""
StatsCan + Geocoder.ca client for the Neighborhood Electrification Readiness pipeline.

Live sources tried (in order):
  1. Geocoder.ca   — free FSA → lat/lon lookup (no key needed). Real, called live.
  2. StatsCan WDS  — census Profile via PCCF/Geosearch is gated and slow; we
                     don't hit it during a request. Instead we keep a calibrated
                     baked-in FSA registry for the demo cities, sourced from
                     2021 Census of Population (Profile by FSA tables 98-401-X
                     and 98-401-X2021006). This keeps demos snappy and gives
                     us methodology-quality numbers per FSA.

Unknown FSAs fall back to province-level synthesized profiles, with
`is_synthesized=True` so the UI shows the disclaimer.
"""
from __future__ import annotations

import httpx
from typing import Optional

from backend.models.electrification import (
    DwellingMix,
    HeatingMix,
    NeighborhoodProfile,
)
from backend.utils.cache import weather_cache  # reuse the existing async cache
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# ── Baked-in FSA registry ─────────────────────────────────────────────── #
# Calibrated from 2021 Census of Population (Profile by FSA, Table 98-401-X
# 2021006) and ECCC Climate Normals 1981–2010. Numbers rounded for demo
# stability. Add more FSAs here as needed.

_PROVINCE_FALLBACK = {
    "ON": {
        "median_household_income_cad": 91_000.0,
        "avg_household_size": 2.5,
        "vehicles_per_household": 1.4,
        "avg_dwelling_age_years": 38.0,
        "heating_degree_days_18c": 4050.0,
        "dwelling_mix": DwellingMix(
            single_detached=0.55, semi_detached=0.10, row=0.10,
            apartment_low_rise=0.10, apartment_high_rise=0.13, other=0.02,
        ),
        "heating_mix": HeatingMix(
            natural_gas=0.62, electric_baseboard=0.12, electric_forced_air=0.08,
            heat_pump=0.04, oil=0.05, wood=0.04, other=0.05,
        ),
    },
    "QC": {
        "median_household_income_cad": 76_000.0,
        "avg_household_size": 2.3,
        "vehicles_per_household": 1.3,
        "avg_dwelling_age_years": 42.0,
        "heating_degree_days_18c": 4500.0,
        "dwelling_mix": DwellingMix(
            single_detached=0.45, semi_detached=0.07, row=0.10,
            apartment_low_rise=0.22, apartment_high_rise=0.13, other=0.03,
        ),
        "heating_mix": HeatingMix(
            natural_gas=0.10, electric_baseboard=0.55, electric_forced_air=0.12,
            heat_pump=0.10, oil=0.05, wood=0.05, other=0.03,
        ),
    },
    "AB": {
        "median_household_income_cad": 109_000.0,
        "avg_household_size": 2.6,
        "vehicles_per_household": 1.7,
        "avg_dwelling_age_years": 30.0,
        "heating_degree_days_18c": 5100.0,
        "dwelling_mix": DwellingMix(
            single_detached=0.60, semi_detached=0.05, row=0.10,
            apartment_low_rise=0.15, apartment_high_rise=0.08, other=0.02,
        ),
        "heating_mix": HeatingMix(
            natural_gas=0.85, electric_baseboard=0.05, electric_forced_air=0.03,
            heat_pump=0.02, oil=0.01, wood=0.02, other=0.02,
        ),
    },
}


# FSA registry generated from StatsCan 2021 Census Profile (catalogue
# 98-401-X2021013). Covers ~1,638 Canadian FSAs. Re-generate via:
#   python -m backend.scripts.ingest_fsa_census
from backend.services._fsa_data_generated import _FSA_REGISTRY  # noqa: E402


# Apply the NRCan SHEU 2019 heating-equipment overlay to PROVINCE_DEFAULTS.
# Falls back silently if the generated file isn't present yet (first-time
# import before ingest_sheu_2019 has been run).
try:
    from backend.services._sheu_heating_mix_generated import (  # noqa: E402
        SHEU_HEATING_MIX_BY_PROVINCE as _SHEU_MIX,
    )
    for _prov, _mix in _SHEU_MIX.items():
        _defaults = _PROVINCE_FALLBACK.get(_prov)
        if not _defaults:
            continue
        _defaults["heating_mix"] = HeatingMix(
            natural_gas=_mix.get("natural_gas", 0.0),
            electric_baseboard=_mix.get("electric_baseboard", 0.0),
            electric_forced_air=_mix.get("electric_forced_air", 0.0),
            heat_pump=_mix.get("heat_pump", 0.0),
            oil=_mix.get("oil", 0.0),
            wood=_mix.get("wood", 0.0),
            other=_mix.get("other", 0.0),
        )
except ImportError:
    pass


CITY_DEFAULT_FSAS: dict[str, list[str]] = {
    "Toronto": ["M5V", "M5A", "M4Y", "M6K"],
    "Mississauga": ["L5B", "L5M"],
    "Brampton": ["L6P", "L6Y"],
    "Ottawa": ["K1S"],
    "Montréal": ["H2X"],
    "Edmonton": ["T5J"],
    # Added 2026-05-18 alongside the full StatsCan FSA registry. Each entry
    # is a representative urban-core / mixed-neighbourhood sample for the
    # city; the registry itself carries every FSA, but these picks drive
    # the "all neighborhoods in X" prompt shortcut.
    "Calgary": ["T2N", "T2P", "T3H"],
    "Halifax": ["B3H", "B3J", "B3K"],
    "Vancouver": ["V6B", "V5K", "V6Z"],
    "Winnipeg": ["R3C", "R3M", "R3T"],
    # Vaughan FSAs per Canada Post addressing scheme (L4H/L4J/L4K/L4L cover
    # Maple, Concord, Thornhill; L6A covers central Vaughan). All five are
    # in the full StatsCan FSA registry — this is only the city-shortcut.
    "Vaughan": ["L4H", "L4J", "L4K", "L4L", "L6A"],
}


def list_supported_fsas() -> list[dict]:
    """Catalog payload for /api/electrification/fsas."""
    out = []
    for fsa, data in _FSA_REGISTRY.items():
        out.append({
            "fsa": fsa,
            "label": data["label"],
            "city": data["city"],
            "province": data["province"],
            "households": data["households"],
        })
    return sorted(out, key=lambda r: (r["city"], r["fsa"]))


# ── Zippopotam.us live API ────────────────────────────────────────────── #
#
# Previously this hit geocoder.ca's `?geoit=json` endpoint, which silently
# stopped returning JSON in 2026 — every request now gets HTML back, json()
# raises, the bare except swallows it, and every FSA ends up coordless. The
# fallback at get_profile() also doesn't help because _FSA_REGISTRY entries
# don't carry lat/lon. Net effect: the electrification map renders empty for
# every run. Zippopotam is purpose-built for postal-code lookups, knows
# Canadian FSAs natively (each FSA gets a distinct centroid, not the parent
# city's), and needs no auth/key.


async def geocode_fsa(fsa: str) -> Optional[tuple[float, float]]:
    """Live FSA → (lat, lon) lookup via zippopotam.us. Cached on success."""
    fsa = fsa.upper().strip()
    cache_key = f"geocoder:fsa:{fsa}"
    cached = await weather_cache.aget(cache_key)
    if cached and isinstance(cached, list) and len(cached) == 2:
        return float(cached[0]), float(cached[1])
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"https://api.zippopotam.us/CA/{fsa}")
            # 404 = FSA not in their dataset (e.g. some rural / military FSAs).
            # Anything else non-200 is a service hiccup.
            if r.status_code != 200:
                return None
            payload = r.json()
        places = payload.get("places") or []
        if not places:
            return None
        lat = places[0].get("latitude")
        lon = places[0].get("longitude")
        if lat and lon:
            result = (float(lat), float(lon))
            await weather_cache.aset(cache_key, list(result))
            return result
    except Exception as e:
        logger.warning(f"zippopotam FSA lookup failed for {fsa}: {e}")
    return None


# ── Profile resolution ────────────────────────────────────────────────── #


async def get_profile(fsa: str) -> NeighborhoodProfile:
    """Resolve a NeighborhoodProfile for an FSA, live-geocoding when possible."""
    key = fsa.upper().strip()
    coords = await geocode_fsa(key)

    if key in _FSA_REGISTRY:
        data = _FSA_REGISTRY[key]
        prof = NeighborhoodProfile(
            fsa=key,
            label=data["label"],
            city=data["city"],
            province=data["province"],
            households=int(data["households"]),
            median_household_income_cad=float(data["median_household_income_cad"]),
            avg_household_size=float(data["avg_household_size"]),
            dwelling_mix=data["dwelling_mix"],
            heating_mix=data["heating_mix"],
            vehicles_per_household=float(data["vehicles_per_household"]),
            avg_dwelling_age_years=float(data["avg_dwelling_age_years"]),
            heating_degree_days_18c=float(data["heating_degree_days_18c"]),
            sources=[
                "StatsCan Census 2021 Profile (Table 98-401-X2021006)",
                "ECCC Climate Normals 1981–2010",
            ],
            is_synthesized=False,
        )
    else:
        # Synthesize from province defaults — guess province from FSA letter.
        prov = _province_from_fsa_letter(key)
        defaults = _PROVINCE_FALLBACK.get(prov, _PROVINCE_FALLBACK["ON"])
        prof = NeighborhoodProfile(
            fsa=key,
            label=f"FSA {key} (synthesized from {prov} averages)",
            city="Unknown",
            province=prov,
            households=15_000,
            median_household_income_cad=float(defaults["median_household_income_cad"]),
            avg_household_size=float(defaults["avg_household_size"]),
            dwelling_mix=defaults["dwelling_mix"],
            heating_mix=defaults["heating_mix"],
            vehicles_per_household=float(defaults["vehicles_per_household"]),
            avg_dwelling_age_years=float(defaults["avg_dwelling_age_years"]),
            heating_degree_days_18c=float(defaults["heating_degree_days_18c"]),
            sources=[f"Province ({prov}) averages, Census 2021"],
            is_synthesized=True,
        )

    if coords:
        prof.latitude, prof.longitude = coords
    elif key in _FSA_REGISTRY:
        # Live geocoder lookup failed (rural / military FSAs occasionally
        # aren't in zippopotam's dataset). Fall back to baked-in registry
        # coords if the entry provides them, so the map still renders a
        # marker. Most _FSA_REGISTRY rows don't carry coords today, so this
        # is a no-op for them — the live lookup is the load-bearing path.
        data = _FSA_REGISTRY[key]
        if "latitude" in data and "longitude" in data:
            prof.latitude = float(data["latitude"])
            prof.longitude = float(data["longitude"])

    # Override the province-default HDD with the closest ECCC Climate
    # Normals 1981-2010 station, when we have a coordinate for the FSA.
    # Falls back to the province default if no station within 200 km.
    if prof.latitude is not None and prof.longitude is not None:
        from backend.services.climate_lookup import cached_hdd18
        nearest = cached_hdd18(round(prof.latitude, 2), round(prof.longitude, 2))
        if nearest:
            prof.heating_degree_days_18c = float(nearest["hdd18_annual"])
            prof.sources.append(
                f"ECCC Climate Normals 1981-2010, station {nearest['name']} "
                f"(id {nearest['climate_id']}, {nearest['distance_km']} km away)"
            )
    return prof


def _province_from_fsa_letter(fsa: str) -> str:
    """Rough province inference from the leading FSA letter."""
    if not fsa:
        return "ON"
    letter = fsa[0].upper()
    return {
        "K": "ON", "L": "ON", "M": "ON", "N": "ON", "P": "ON",
        "G": "QC", "H": "QC", "J": "QC",
        "T": "AB",
        "V": "BC",
        "R": "MB",
        "S": "SK",
        "B": "NS",
        "E": "NB",
        "C": "PE",
        "A": "NL",
        "Y": "YT", "X": "NT",
    }.get(letter, "ON")


def default_fsas_for_city(city: str) -> list[str]:
    """Pick the demo FSA bundle for a city. Empty if city unknown."""
    for k, v in CITY_DEFAULT_FSAS.items():
        if k.lower() == city.lower():
            return list(v)
    return []
