"""
Heat pump performance curves for the Winter Peak Stress Tester.

Models the temperature-dependent Coefficient of Performance (COP) for
the two heat pump archetypes most common in Canadian residential stock:

  - Standard ASHP (air-source, ~5 ton typical): widely deployed, loses
    most of its efficiency below -8°C and engages backup resistance heat.
  - Cold-Climate ASHP (ccASHP, NRCan-certified): retains useful capacity
    down to -25°C; backup engages later.

EV cold-weather draw is also handled here (it's a temperature-dependent
load model and lives next to its sibling concept).

COP curves are anchored on:
  - NRCan Cold Climate Air-Source Heat Pump Specification (CCHP) 2022
  - Northeast Energy Efficiency Partnerships (NEEP) ccASHP database
  - ASHRAE Handbook (HVAC Systems and Equipment 2020), Ch. 49
"""
from typing import Literal

from backend.utils.logger import get_logger

logger = get_logger(__name__)

HeatPumpType = Literal["standard_ashp", "cold_climate_ashp"]


# ── COP curves ────────────────────────────────────────────────────────── #


def cop_at_temp(temp_c: float, hp_type: HeatPumpType = "standard_ashp") -> float:
    """
    Return the heating COP at a given outdoor temperature.

    Above ~7°C, both unit types perform near rated COP (3.5-4.5).
    Below the engineered cutoff, COP drops linearly toward 1.0 (resistance
    heat equivalent), and backup engages.

    Returns 1.0 (resistance-heat equivalent) below the COP=1 crossover.
    """
    if hp_type == "cold_climate_ashp":
        # ccASHP curve — NRCan CCHP spec, NEEP database means
        if temp_c >= 7.0:
            return 4.0
        if temp_c >= -10.0:
            return 4.0 - (7.0 - temp_c) * 0.10        # 4.0 → 2.3 across 7→-10
        if temp_c >= -25.0:
            return 2.3 - (-10.0 - temp_c) * 0.067     # 2.3 → 1.3 across -10→-25
        return 1.1                                    # below -25, ~auxiliary heat dominates
    else:  # standard_ashp
        if temp_c >= 7.0:
            return 3.5
        if temp_c >= -8.0:
            return 3.5 - (7.0 - temp_c) * 0.13        # 3.5 → 1.55 across 7→-8
        return 1.0                                    # below -8°C, defrost + resistance


def backup_engagement_fraction(temp_c: float, hp_type: HeatPumpType = "standard_ashp") -> float:
    """
    Fraction of total heating load served by auxiliary resistance heat
    at a given outdoor temperature. 0.0 = HP only, 1.0 = pure resistance.

    Retained for narrative use (chat tools, report copy) — for actual
    electrical draw attribution use `hp_electrical_split()`, which models
    the compressor as running continuously at its rated input rather than
    handing all load to aux once `backup_engagement_fraction` reaches 1.0.
    """
    if hp_type == "cold_climate_ashp":
        if temp_c >= -10.0:
            return 0.0
        if temp_c >= -25.0:
            return min(1.0, (-10.0 - temp_c) / 15.0)  # 0 at -10°C → 1.0 at -25°C
        return 1.0
    else:  # standard_ashp
        if temp_c >= -8.0:
            return 0.0
        if temp_c >= -20.0:
            return min(1.0, (-8.0 - temp_c) / 12.0)   # 0 at -8°C → 1.0 at -20°C
        return 1.0


# ── Compressor electrical input + lockout ─────────────────────────────── #
# A residential heat pump's compressor pulls a roughly constant electrical
# input while running — typically 3.0-3.5 kW for a 3-ton standard ASHP and
# 3.5-4.0 kW for the larger compressors on cold-climate units. Below the
# manufacturer-set lockout temperature, the compressor is disabled by safety
# controls and all load shifts to auxiliary resistance.
#
# Sources:
#   - NEEP ccASHP database (median rated electrical input by tonnage)
#   - AHRI Standard 210/240 nameplate values for residential ASHPs
#   - ASHRAE Handbook (HVAC Systems and Equipment 2020), Ch. 49

_HP_RATED_ELECTRICAL_KW: dict[HeatPumpType, float] = {
    "standard_ashp": 3.5,
    "cold_climate_ashp": 3.8,
}

_HP_LOCKOUT_TEMP_C: dict[HeatPumpType, float] = {
    "standard_ashp": -25.0,
    "cold_climate_ashp": -30.0,
}


def hp_rated_electrical_kw(hp_type: HeatPumpType = "standard_ashp") -> float:
    """Per-home rated electrical input of the compressor."""
    return _HP_RATED_ELECTRICAL_KW.get(hp_type, 3.5)


def hp_lockout_temp_c(hp_type: HeatPumpType = "standard_ashp") -> float:
    """Outdoor temperature below which the compressor shuts off."""
    return _HP_LOCKOUT_TEMP_C.get(hp_type, -25.0)


def hp_electrical_split(
    temp_c: float,
    thermal_kw_per_home: float,
    hp_type: HeatPumpType = "standard_ashp",
) -> tuple[float, float]:
    """
    Split a household's thermal demand into (heat-pump kW, aux-resistance kW)
    of electrical draw.

    Model: the compressor draws the minimum of (demand / COP) and its rated
    electrical input. Auxiliary resistance covers any remaining thermal gap
    at COP = 1.0. Below the compressor lockout temperature the heat pump
    shuts off and all load shifts to auxiliary.

    This replaces the older `backup_engagement_fraction`-driven attribution,
    which drove the heat-pump component to zero in the deep cold — physically
    wrong for all-electric systems, where the compressor stays running at
    full rated input while aux fills the thermal gap *on top of* it.
    """
    if thermal_kw_per_home <= 0.0:
        return (0.0, 0.0)

    if temp_c <= hp_lockout_temp_c(hp_type):
        return (0.0, thermal_kw_per_home)

    cop = max(1.0, cop_at_temp(temp_c, hp_type))
    rated_kw = hp_rated_electrical_kw(hp_type)

    implied_electric = thermal_kw_per_home / cop
    hp_electric = min(implied_electric, rated_kw)
    hp_thermal_delivered = hp_electric * cop
    aux_electric = max(0.0, thermal_kw_per_home - hp_thermal_delivered)
    return (hp_electric, aux_electric)


# ── EV cold-weather draw ──────────────────────────────────────────────── #


def ev_cold_load_factor(temp_c: float) -> float:
    """
    Multiplicative factor on baseline EV charging load that accounts for:
      - Battery preconditioning (raises charging energy needed for given
        miles).
      - Cabin warming on charge.
      - Reduced regenerative braking efficiency.

    1.0 = no cold penalty (mild day). 1.6 = peak draw at -25°C.
    Source: AAA / Recurrent / Geotab cold-weather range studies, generalised.
    """
    if temp_c >= 10.0:
        return 1.0
    if temp_c >= -5.0:
        return 1.0 + (10.0 - temp_c) * 0.013          # 1.0 → 1.20 across 10→-5
    if temp_c >= -25.0:
        return 1.20 + (-5.0 - temp_c) * 0.020         # 1.20 → 1.60 across -5→-25
    return 1.65


# ── Aggregate household demand ────────────────────────────────────────── #


def household_heating_kw(
    temp_c: float,
    design_heating_load_kw: float = 8.0,
    primary_heating: str = "heat_pump",
    hp_type: HeatPumpType = "standard_ashp",
) -> dict:
    """
    Estimate instantaneous electric heating draw for one household.

    Returns a breakdown:
      heat_pump_kw      - electrical draw of the compressor (after COP)
      backup_kw         - electrical draw of resistance auxiliary
      baseboard_kw      - direct resistance for baseboard-heated homes
      total_electric_kw - sum (the grid actually sees this)

    For gas/oil-heated homes, all electric values are 0 (excluded).
    """
    if temp_c >= 18.0:
        return {"heat_pump_kw": 0.0, "backup_kw": 0.0, "baseboard_kw": 0.0, "total_electric_kw": 0.0}

    # Linear scaling: design_heating_load_kw is sized for -25°C indoor 21°C.
    delta_t = max(0.0, 21.0 - temp_c)
    delta_t_design = 21.0 - (-25.0)
    thermal_load_kw = design_heating_load_kw * (delta_t / delta_t_design)

    if primary_heating == "baseboard":
        return {
            "heat_pump_kw": 0.0,
            "backup_kw": 0.0,
            "baseboard_kw": thermal_load_kw,
            "total_electric_kw": thermal_load_kw,
        }

    if primary_heating == "heat_pump":
        hp_electric, backup_electric = hp_electrical_split(temp_c, thermal_load_kw, hp_type)
        return {
            "heat_pump_kw": round(hp_electric, 2),
            "backup_kw": round(backup_electric, 2),
            "baseboard_kw": 0.0,
            "total_electric_kw": round(hp_electric + backup_electric, 2),
        }

    # gas / oil / district — no electric heating draw (ignition fans negligible)
    return {"heat_pump_kw": 0.0, "backup_kw": 0.0, "baseboard_kw": 0.0, "total_electric_kw": 0.0}
