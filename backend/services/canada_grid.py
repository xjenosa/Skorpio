"""
Canadian grid data layer.

Combines:
  - Provincial reference constants (always available, hardcoded from public
    NRCan / CER / IESO / AESO / Hydro-Québec annual reports).
  - Live carbon intensity from ElectricityMaps (when ELECTRICITYMAPS_API_KEY
    is set; CA-ON, CA-QC, CA-AB, CA-BC, CA-MB, CA-SK, CA-NS, CA-NB, CA-NL,
    CA-PE, CA-YT, CA-NT, CA-NU are all supported zones).
  - Light HTTP fetches of public IESO / AESO / Hydro-Québec CSV/JSON
    reports for live demand. Endpoints are *public, no auth required*; if
    a fetch fails the client returns the provincial reference snapshot so
    the rest of the pipeline never breaks on demo day.

Why this layout: the Skorpio agent is expected to reason about Canadian
sites whether or not live data is reachable. Static reference values keep
the demo deterministic; live data layered on top sharpens the answer when
networks cooperate.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Optional

import httpx

from backend.config import settings
from backend.services.electricitymaps import electricitymaps_client
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# ── Provincial reference data ─────────────────────────────────────────── #
# Sources: Canada Energy Regulator (CER) Provincial Energy Profiles 2024,
# NRCan EIST tables, ElectricityMaps annual Canada report. Numbers are
# annual-mean order-of-magnitude — fine as a backstop, replace with the
# live snapshot when one is available.

@dataclass(frozen=True)
class ProvincialProfile:
    iso_code: str               # CA-ON, CA-QC, ...
    name: str
    capital: str
    grid_operator: str
    typical_carbon_g_co2_kwh: int
    installed_capacity_gw: float
    fuel_mix: dict[str, float]  # fractions, sum ~1.0
    population_million: float
    timezone: str


PROVINCES: dict[str, ProvincialProfile] = {
    "CA-ON": ProvincialProfile(
        iso_code="CA-ON",
        name="Ontario",
        capital="Toronto",
        grid_operator="IESO",
        typical_carbon_g_co2_kwh=30,   # mostly nuclear + hydro
        installed_capacity_gw=42.0,
        fuel_mix={"nuclear": 0.55, "hydro": 0.24, "gas": 0.10, "wind": 0.08, "solar": 0.02, "biomass": 0.01},
        population_million=15.6,
        timezone="America/Toronto",
    ),
    "CA-QC": ProvincialProfile(
        iso_code="CA-QC",
        name="Québec",
        capital="Québec City",
        grid_operator="Hydro-Québec",
        typical_carbon_g_co2_kwh=2,    # almost entirely hydro
        installed_capacity_gw=45.0,
        fuel_mix={"hydro": 0.94, "wind": 0.05, "biomass": 0.01},
        population_million=8.9,
        timezone="America/Toronto",
    ),
    "CA-AB": ProvincialProfile(
        iso_code="CA-AB",
        name="Alberta",
        capital="Edmonton",
        grid_operator="AESO",
        typical_carbon_g_co2_kwh=550,  # gas-heavy, transitioning off coal
        installed_capacity_gw=20.0,
        fuel_mix={"gas": 0.62, "wind": 0.20, "coal": 0.08, "hydro": 0.05, "solar": 0.03, "biomass": 0.02},
        population_million=4.8,
        timezone="America/Edmonton",
    ),
    "CA-BC": ProvincialProfile(
        iso_code="CA-BC",
        name="British Columbia",
        capital="Victoria",
        grid_operator="BC Hydro",
        typical_carbon_g_co2_kwh=15,
        installed_capacity_gw=20.0,
        fuel_mix={"hydro": 0.92, "biomass": 0.04, "wind": 0.03, "gas": 0.01},
        population_million=5.5,
        timezone="America/Vancouver",
    ),
    "CA-MB": ProvincialProfile(
        iso_code="CA-MB",
        name="Manitoba",
        capital="Winnipeg",
        grid_operator="Manitoba Hydro",
        typical_carbon_g_co2_kwh=10,
        installed_capacity_gw=6.5,
        fuel_mix={"hydro": 0.97, "wind": 0.02, "gas": 0.01},
        population_million=1.4,
        timezone="America/Winnipeg",
    ),
    "CA-SK": ProvincialProfile(
        iso_code="CA-SK",
        name="Saskatchewan",
        capital="Regina",
        grid_operator="SaskPower",
        typical_carbon_g_co2_kwh=620,
        installed_capacity_gw=5.4,
        fuel_mix={"gas": 0.42, "coal": 0.30, "hydro": 0.18, "wind": 0.08, "other": 0.02},
        population_million=1.2,
        timezone="America/Regina",
    ),
    "CA-NB": ProvincialProfile(
        iso_code="CA-NB",
        name="New Brunswick",
        capital="Fredericton",
        grid_operator="NB Power",
        typical_carbon_g_co2_kwh=280,
        installed_capacity_gw=4.0,
        fuel_mix={"nuclear": 0.32, "hydro": 0.21, "gas": 0.18, "coal": 0.13, "wind": 0.10, "biomass": 0.06},
        population_million=0.83,
        timezone="America/Halifax",
    ),
    "CA-NS": ProvincialProfile(
        iso_code="CA-NS",
        name="Nova Scotia",
        capital="Halifax",
        grid_operator="NS Power",
        typical_carbon_g_co2_kwh=580,
        installed_capacity_gw=2.8,
        fuel_mix={"coal": 0.45, "gas": 0.18, "wind": 0.18, "hydro": 0.10, "biomass": 0.07, "other": 0.02},
        population_million=1.0,
        timezone="America/Halifax",
    ),
    "CA-NL": ProvincialProfile(
        iso_code="CA-NL",
        name="Newfoundland & Labrador",
        capital="St. John's",
        grid_operator="NL Hydro",
        typical_carbon_g_co2_kwh=30,
        installed_capacity_gw=7.5,
        fuel_mix={"hydro": 0.95, "diesel": 0.03, "wind": 0.02},
        population_million=0.53,
        timezone="America/St_Johns",
    ),
    "CA-PE": ProvincialProfile(
        iso_code="CA-PE",
        name="Prince Edward Island",
        capital="Charlottetown",
        grid_operator="Maritime Electric",
        typical_carbon_g_co2_kwh=180,  # imports heavily from NB
        installed_capacity_gw=0.3,
        fuel_mix={"wind": 0.99, "diesel": 0.01},
        population_million=0.17,
        timezone="America/Halifax",
    ),
}


def get_province(iso_code: str) -> Optional[ProvincialProfile]:
    return PROVINCES.get(iso_code.upper())


def all_province_codes() -> list[str]:
    return list(PROVINCES.keys())


# ── Live snapshots ────────────────────────────────────────────────────── #

@dataclass
class ProvincialSnapshot:
    iso_code: str
    name: str
    grid_operator: str
    carbon_g_co2_kwh: int
    capacity_gw: float
    fuel_mix: dict[str, float]
    population_million: float
    timezone: str
    sources: list[str]


async def get_provincial_snapshot(iso_code: str) -> Optional[ProvincialSnapshot]:
    """Best-effort: live carbon from ElectricityMaps when available, otherwise
    the provincial reference. Always returns something for known provinces."""
    profile = get_province(iso_code)
    if not profile:
        return None

    sources = ["CER provincial energy profile"]
    carbon = profile.typical_carbon_g_co2_kwh

    em = await electricitymaps_client.get_carbon_intensity(profile.iso_code)
    if em and em.get("g_co2_per_kwh") is not None:
        carbon = int(em["g_co2_per_kwh"])
        sources.append("ElectricityMaps")

    return ProvincialSnapshot(
        iso_code=profile.iso_code,
        name=profile.name,
        grid_operator=profile.grid_operator,
        carbon_g_co2_kwh=carbon,
        capacity_gw=profile.installed_capacity_gw,
        fuel_mix=profile.fuel_mix,
        population_million=profile.population_million,
        timezone=profile.timezone,
        sources=sources,
    )


# ── Live demand fetchers ─────────────────────────────────────────────── #

async def fetch_ieso_realtime_demand_mw() -> Optional[float]:
    """Pull Ontario real-time market totals from IESO public reports.

    Endpoint is open (no auth). Schema: 17-column CSV; the column we want is
    "Total Energy" near the end. If anything goes wrong (timeout, schema
    drift), returns None and the caller falls back to the static profile.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(settings.ieso_realtime_totals_url)
        if resp.status_code != 200:
            logger.warning(f"IESO realtime fetch returned {resp.status_code}")
            return None
        # IESO CSVs have a header section (~3-5 metadata lines) before the
        # tabular data; we sniff for the "Total Energy" column.
        rows = list(csv.reader(io.StringIO(resp.text)))
        header_idx = next(
            (i for i, r in enumerate(rows) if "Total Energy" in r),
            None,
        )
        if header_idx is None or header_idx + 1 >= len(rows):
            return None
        header = rows[header_idx]
        col = header.index("Total Energy")
        # Last data row = most recent interval.
        data_rows = [r for r in rows[header_idx + 1:] if len(r) > col and r[col].strip()]
        if not data_rows:
            return None
        return float(data_rows[-1][col])
    except Exception as e:
        logger.warning(f"IESO realtime fetch failed: {e}")
        return None


async def fetch_aeso_demand_mw() -> Optional[float]:
    """Pull Alberta system demand from the AESO Current Supply Demand report.

    AESO's public CSV endpoint is occasionally renamed; if this fetch fails
    we surface None and reference data takes over.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(settings.aeso_csd_url)
        if resp.status_code != 200:
            return None
        # Schema: short CSV with "Alberta Internal Load" near top.
        for line in resp.text.splitlines():
            if "Alberta Internal Load" in line:
                parts = [p.strip() for p in line.split(",") if p.strip()]
                for p in parts[::-1]:
                    try:
                        return float(p)
                    except ValueError:
                        continue
        return None
    except Exception as e:
        logger.warning(f"AESO demand fetch failed: {e}")
        return None


async def fetch_hydroquebec_demand_mw() -> Optional[float]:
    """Pull Québec system demand from Hydro-Québec's open data portal."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(settings.hydroquebec_demand_url)
        if resp.status_code != 200:
            return None
        payload = resp.json()
        # Most HQ open-data feeds use a "details" array; we hunt for a
        # numeric "valeurs" entry and pick the latest.
        if isinstance(payload, dict):
            details = payload.get("details") or payload.get("data") or []
            if isinstance(details, list) and details:
                last = details[-1]
                for k in ("valeur", "value", "demande"):
                    if k in last:
                        return float(last[k])
        return None
    except Exception as e:
        logger.warning(f"Hydro-Québec demand fetch failed: {e}")
        return None
