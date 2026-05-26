"""
Helpers exposing the ingested OEB Yearbook + OSM substation data to the
rest of the pipeline. Both datasets are static lookups by canonical
utility key.

  - oeb_utility(name)               — customer count, peak load (MW),
                                       service area, SAIFI/SAIDI
  - substations_for_utility(name)   — list of real substation locations
  - apply_oeb_overlay(city_profile) — bump city_profile.total_customers
                                       and winter_peak_mw with OEB-published
                                       numbers when the utility matches

Sources: OEB Yearbook of Electricity Distributors 2021 open-data; OSM
Overpass API (power=substation, country=CA, ≥25 kV).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from backend.services._oeb_utilities_generated import OEB_UTILITIES_BY_NAME
from backend.services._substations_generated import SUBSTATIONS_BY_OPERATOR


# Aliases between the names callers tend to use ("Hydro Ottawa", "alectra")
# and the canonical OEB / OSM keys.
_OEB_ALIASES: dict[str, str] = {
    "toronto hydro": "Toronto Hydro-Electric System Limited",
    "alectra": "Alectra Utilities Corporation",
    "alectra utilities": "Alectra Utilities Corporation",
    "hydro ottawa": "Hydro Ottawa Limited",
    "hydro one": "Hydro One Networks Inc.",
    "hydro one networks": "Hydro One Networks Inc.",
}

_SUBSTATION_ALIASES: dict[str, str] = {
    "toronto hydro-electric system limited": "toronto hydro",
    "alectra utilities corporation": "alectra",
    "hydro ottawa limited": "hydro ottawa",
    "hydro one networks inc.": "hydro one",
    "hydro-québec": "hydro-québec",
    "hydroquébec": "hydro-québec",
    "hydro quebec": "hydro-québec",
    "epcor distribution": "epcor",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def oeb_utility(name: str) -> Optional[dict]:
    """OEB Yearbook 2021 record for an Ontario distributor. `name` can be a
    friendly key ("Hydro Ottawa") or the OEB-published company name; we try
    both before giving up."""
    key = _norm(name)
    canonical = _OEB_ALIASES.get(key) or name
    return OEB_UTILITIES_BY_NAME.get(canonical)


def substations_for_utility(name: str) -> list[dict]:
    """OSM substations tagged to this utility, sorted descending by
    voltage. Empty list when OSM has no coverage for the operator."""
    key = _SUBSTATION_ALIASES.get(_norm(name), _norm(name))
    return list(SUBSTATIONS_BY_OPERATOR.get(key, []))


def apply_oeb_overlay(profile: Any) -> Any:
    """Bump a feeder_topology CityProfile-shaped object's customer count
    and winter peak load with the matching OEB number when one exists.
    The profile is mutated in place and returned for chaining."""
    rec = oeb_utility(getattr(profile, "utility", ""))
    if not rec:
        return profile
    if rec.get("customers"):
        profile.total_customers = int(rec["customers"])
    if rec.get("winter_peak_mw"):
        profile.winter_peak_mw = float(rec["winter_peak_mw"])
    return profile
