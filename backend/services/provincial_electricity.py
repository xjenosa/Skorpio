"""
Helpers exposing the StatsCan Table 25-10-0021 provincial annual electricity
supply/disposition data to the rest of the pipeline. Annual aggregates only
(MWh per sector per year per province).

  - residential_mwh(province)        — last reported residential sales
  - total_generation_mwh(province)   — last reported in-province generation
  - reporting_year(province)         — year these values are for
  - sanity_check_city_peak(profile)  — log a warning if a synthesized city
                                       winter peak implies more annual MWh
                                       than the province actually generates
"""

from __future__ import annotations

from typing import Optional

from backend.services._provincial_electricity_generated import (
    PROVINCIAL_ELECTRICITY_BY_PROVINCE,
)
from backend.utils.logger import get_logger

logger = get_logger(__name__)


def _rec(province: str) -> Optional[dict]:
    return PROVINCIAL_ELECTRICITY_BY_PROVINCE.get((province or "").upper().strip())


def residential_mwh(province: str) -> Optional[int]:
    rec = _rec(province)
    return rec["components_mwh"].get("residential_mwh") if rec else None


def total_generation_mwh(province: str) -> Optional[int]:
    rec = _rec(province)
    return rec["components_mwh"].get("total_generation_mwh") if rec else None


def reporting_year(province: str) -> Optional[int]:
    rec = _rec(province)
    return rec["year"] if rec else None


def sanity_check_city_peak(profile) -> None:
    """If a synthesized city winter_peak_mw would imply > province residential
    annual MWh at a 0.45 typical load factor, log a warning. Doesn't mutate
    the profile — just flags clearly-implausible calibration numbers."""
    res = residential_mwh(getattr(profile, "province", ""))
    if not res:
        return
    # Annualized MWh ≈ peak_kw × hours_in_year × load_factor.
    implied = float(profile.winter_peak_mw) * 8760 * 0.45
    if implied > res * 1.5:
        logger.warning(
            "City %s winter_peak_mw=%.1f implies %.1e MWh/yr, > 1.5× the "
            "entire province %s residential annual of %d MWh — calibration "
            "may be too high.",
            profile.city, profile.winter_peak_mw, implied,
            profile.province, res,
        )
