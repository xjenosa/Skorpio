"""
Helpers exposing the ingested EV charger + vehicle registration data to
the rest of the pipeline. Both datasets are static and small enough to
hold in memory.

  - chargers_for_fsa(fsa) / chargers_for_city(city, prov) — count + ports
  - ev_share_pct(province)                                  — share of light-duty fleet
  - vehicles_total(province)                                — fleet size

All counts come from authoritative sources via the ingestion scripts in
backend/scripts/.
"""

from __future__ import annotations

from typing import Optional

from backend.services._ev_chargers_generated import (
    EV_CHARGERS_BY_FSA, EV_CHARGERS_BY_CITY,
)
from backend.services._vehicle_registrations_generated import (
    VEHICLE_REGISTRATIONS_BY_PROVINCE,
)


def chargers_for_fsa(fsa: str) -> Optional[dict]:
    return EV_CHARGERS_BY_FSA.get((fsa or "").upper().strip())


def chargers_for_city(city: str, province: str) -> Optional[dict]:
    """City + province combined key matches the way the ingestion script
    rolled rows up (e.g. 'Toronto, ON')."""
    key = f"{(city or '').strip()}, {(province or '').strip().upper()}"
    return EV_CHARGERS_BY_CITY.get(key)


def ev_share_pct(province: str) -> Optional[float]:
    """Latest-year light-duty EV share (BEV + PHEV) per province, % of fleet.
    Source: StatsCan 23-10-0308."""
    rec = VEHICLE_REGISTRATIONS_BY_PROVINCE.get((province or "").upper())
    return rec["ev_share_pct"] if rec else None


def vehicles_total(province: str) -> Optional[int]:
    rec = VEHICLE_REGISTRATIONS_BY_PROVINCE.get((province or "").upper())
    return rec["total_light_duty"] if rec else None


def registration_year(province: str) -> Optional[int]:
    rec = VEHICLE_REGISTRATIONS_BY_PROVINCE.get((province or "").upper())
    return rec["year"] if rec else None
