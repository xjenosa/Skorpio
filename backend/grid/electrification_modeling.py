"""
Per-household + per-FSA load impact modeling for the Neighborhood
Electrification Readiness pipeline.

Builds a 24-hour winter peak day load curve combining:
  - Existing electric load (lighting, appliances, water, residual heating)
  - NEW heat pump load from converted gas/oil/baseboard homes
  - NEW EV charging load from added vehicles

Outputs per-household kW curves AND aggregated FSA totals so the readiness
agent can score grid headroom.

Heat pump curves come from services.heat_pump_cop. Hourly residential
shape constants come from NRCan SHEU 2019 + IESO ResLoad load research.
"""
from __future__ import annotations

from backend.models.electrification import (
    AdoptionScenario,
    LoadImpactPoint,
    NeighborhoodLoadImpact,
    NeighborhoodProfile,
)
from backend.services.heat_pump_cop import (
    ev_cold_load_factor,
    hp_electrical_split,
)
from backend.services.ev_data import ev_share_pct as _real_ev_share_pct


# Pre-electrification baseline (% of light-duty fleet already EV). Used to
# count only *incremental* EVs added by the scenario. Falls back to 3% (rough
# 2023 national average) when we don't have a per-province StatsCan record.
_BASELINE_EV_FRACTION_FALLBACK = 0.03


def _baseline_ev_fraction(province: str | None) -> float:
    """Real per-province EV share of light-duty fleet (StatsCan 23-10-0308),
    falling back to a national-average constant when the province is unknown."""
    if not province:
        return _BASELINE_EV_FRACTION_FALLBACK
    pct = _real_ev_share_pct(province)
    if pct is None:
        return _BASELINE_EV_FRACTION_FALLBACK
    # StatsCan returns percent (e.g. 5.20 for 5.2%); convert to fraction.
    return pct / 100.0


# ── Constants ─────────────────────────────────────────────────────────── #


# Typical winter peak day temperatures (°C) for southern Ontario / Québec.
# The hour index is 0 = 6 am to 23 = 5 am. Coldest stretch 5–7 am.
# Adjusted by the FSA's HDD18 to scale colder for northern FSAs.
_BASE_TEMP_PROFILE_C: list[float] = [
    -8, -10, -11, -12, -13, -13,    # 6–11 am, sun rising
    -10, -7, -5, -3, -2, -2,        # 12–5 pm, midday peak
    -3, -5, -8, -11, -14, -16,      # 6–11 pm, evening drop
    -17, -18, -18, -17, -16, -14,   # midnight–5 am, coldest
]


# Existing baseline electric kW per household by hour (winter weekday).
# Excludes heating — this is appliances, lighting, water heat, etc.
#
# The eyeballed default below is a midpoint shape across published Canadian
# residential load research. When the IESO winter-weekday shape is
# available (ingest_ieso_demand), we replace the hourly shape with the
# real Ontario time-of-day pattern while preserving the eyeballed mean
# magnitude — so calibration stays anchored but the time-of-day curve
# is real.
_BASE_LOAD_KW_HOUR: list[float] = [
    1.4, 1.6, 1.5, 1.3, 1.1, 1.0,
    0.9, 0.9, 1.0, 1.1, 1.2, 1.3,
    1.5, 1.8, 2.2, 2.6, 2.9, 3.0,
    2.7, 2.3, 1.9, 1.7, 1.5, 1.4,
]

try:
    from backend.services._ieso_demand_shape_generated import (  # noqa: E402
        IESO_WINTER_WEEKDAY_SHAPE as _IESO_SHAPE,
    )
    # Preserve the original mean — only replace the time-of-day curve.
    _original_mean = sum(_BASE_LOAD_KW_HOUR) / 24.0
    _BASE_LOAD_KW_HOUR = [round(s * _original_mean, 3) for s in _IESO_SHAPE]
except ImportError:
    pass


# EV charging shape — most L2 charging happens 6 pm – 6 am with morning gap.
_EV_CHARGE_SHAPE: list[float] = [
    0.10, 0.10, 0.10, 0.10, 0.05, 0.05,
    0.05, 0.05, 0.10, 0.10, 0.10, 0.10,
    0.20, 0.30, 0.40, 0.55, 0.70, 0.80,
    0.85, 0.80, 0.70, 0.55, 0.40, 0.20,
]
_EV_AVG_DAILY_KWH = 12.0    # ~50 km/day @ 24 kWh/100 km
_EV_PEAK_CHARGER_KW = 7.4   # typical L2 max draw


# Average household design heating load (kW thermal) by dwelling type. From
# NRCan EnerGuide reference homes.
_DESIGN_HEAT_KW = {
    "single_detached": 11.0,
    "semi_detached": 8.5,
    "row": 7.0,
    "apartment_low_rise": 5.5,
    "apartment_high_rise": 4.0,
    "other": 7.0,
}


# Real province-level coldest-24-hour curves from ECCC bulk_data
# observations at canonical city stations (most-recent-2-winter slide).
# Generated via `backend.scripts.ingest_eccc_winter_hourly`. Falls back
# silently to the eyeballed _BASE_TEMP_PROFILE_C when the file isn't
# present yet.
try:
    from backend.services._winter_peak_curves_generated import (  # noqa: E402
        WINTER_PEAK_DAY_TEMP_C as _REAL_WINTER_CURVES,
    )
except ImportError:
    _REAL_WINTER_CURVES = {}


def _temperature_for_hour(hour: int, hdd_18c: float,
                          province: str | None = None) -> float:
    """Temperature curve scaled by FSA's HDD (colder areas → colder day).
    When a real ECCC coldest-day curve exists for the FSA's province,
    use that as the base; otherwise fall back to the rule-of-thumb
    `_BASE_TEMP_PROFILE_C` array."""
    if province and province in _REAL_WINTER_CURVES:
        base = _REAL_WINTER_CURVES[province]["hours_c"][hour]
        return base
    base = _BASE_TEMP_PROFILE_C[hour]
    # Centre on Toronto baseline (~4000 HDD); scale ±0.0025 °C per HDD delta.
    shift = (hdd_18c - 4000.0) * -0.0025
    return base + shift


def _avg_design_heat_kw(profile: NeighborhoodProfile) -> float:
    """Weighted-average design heating load for the FSA's housing mix."""
    mix = profile.dwelling_mix
    return (
        mix.single_detached * _DESIGN_HEAT_KW["single_detached"]
        + mix.semi_detached * _DESIGN_HEAT_KW["semi_detached"]
        + mix.row * _DESIGN_HEAT_KW["row"]
        + mix.apartment_low_rise * _DESIGN_HEAT_KW["apartment_low_rise"]
        + mix.apartment_high_rise * _DESIGN_HEAT_KW["apartment_high_rise"]
        + mix.other * _DESIGN_HEAT_KW["other"]
    )


# ── Public modeling entry point ───────────────────────────────────────── #


def model_load_impact(
    profile: NeighborhoodProfile,
    scenario: AdoptionScenario,
    *,
    hp_type: str = "standard_ashp",
) -> NeighborhoodLoadImpact:
    """
    Build a 24-hour winter peak load impact for one (FSA, scenario) pair.

    Logic:
      - Heat pump load: only fossil/oil/baseboard homes that get *converted* to
        HP add new load. Existing HP homes are already in the baseline.
      - EV load: incremental EVs above the current ~3% baseline.
    """
    design_heat_kw = _avg_design_heat_kw(profile)

    # Pool of homes that could be converted = currently fossil + baseboard
    fossil_share = (
        profile.heating_mix.natural_gas
        + profile.heating_mix.oil
        + profile.heating_mix.wood
        + profile.heating_mix.other
    )
    convertible_share = fossil_share + profile.heating_mix.electric_baseboard
    new_hp_share = convertible_share * scenario.heat_pump_conversion_pct

    baseline_ev = _baseline_ev_fraction(getattr(profile, "province", None))
    incremental_ev_per_hh = max(
        0.0,
        profile.vehicles_per_household * (scenario.ev_adoption_pct - baseline_ev),
    )

    points: list[LoadImpactPoint] = []
    peak_kw = 0.0
    peak_hour = 0

    for h in range(24):
        temp = _temperature_for_hour(
            h, profile.heating_degree_days_18c,
            province=getattr(profile, "province", None),
        )
        base_kw = _BASE_LOAD_KW_HOUR[h]

        # NEW heat pump electric draw, weighted by share of homes converting.
        # The split between compressor and aux resistance is delegated to
        # hp_electrical_split so the same physics model is used here and in
        # the winter-peak grid simulator.
        if new_hp_share > 0:
            delta_t = max(0.0, 21.0 - temp)
            thermal_kw = design_heat_kw * (delta_t / 46.0)
            hp_electric, aux_electric = hp_electrical_split(temp, thermal_kw, hp_type)
            new_hp_kw = (hp_electric + aux_electric) * new_hp_share
        else:
            new_hp_kw = 0.0

        # NEW EV draw, with cold weather multiplier.
        ev_kw_at_household = (
            incremental_ev_per_hh
            * _EV_AVG_DAILY_KWH
            * _EV_CHARGE_SHAPE[h]
            * ev_cold_load_factor(temp)
        )
        ev_kw_at_household = min(ev_kw_at_household, _EV_PEAK_CHARGER_KW * incremental_ev_per_hh)

        total = base_kw + new_hp_kw + ev_kw_at_household
        if total > peak_kw:
            peak_kw = total
            peak_hour = h

        points.append(LoadImpactPoint(
            hour=h,
            base_load_kw_per_household=round(base_kw, 2),
            new_heat_pump_kw_per_household=round(new_hp_kw, 2),
            new_ev_kw_per_household=round(ev_kw_at_household, 2),
            total_kw_per_household=round(total, 2),
        ))

    incremental_peak_mw = (peak_kw - _BASE_LOAD_KW_HOUR[peak_hour]) * profile.households / 1000.0

    # Transformer overload heuristic: typical residential transformer 75 kVA
    # serves ~40 homes. If aggregated peak / 40 > 75, flag it.
    households_per_xfmr = 40
    n_xfmrs = max(1, profile.households // households_per_xfmr)
    xfmr_load_kva = (peak_kw * households_per_xfmr) / 0.95  # PF assumed 0.95
    overloaded = n_xfmrs if xfmr_load_kva > 75 else int(n_xfmrs * max(0.0, (xfmr_load_kva - 60) / 15.0))

    # Panel upgrade trigger — homes with >100A service tip if total household
    # peak > 18 kW (continuous peak ~75% of breaker size).
    panel_upgrade_pct = 0.0
    if peak_kw > 18.0:
        panel_upgrade_pct = min(1.0, (peak_kw - 18.0) / 12.0)
    panel_upgrade_pct *= max(scenario.heat_pump_conversion_pct, scenario.ev_adoption_pct)

    return NeighborhoodLoadImpact(
        fsa=profile.fsa,
        scenario_name=scenario.name,
        hours=points,
        peak_kw_per_household=round(peak_kw, 2),
        peak_hour=peak_hour,
        incremental_peak_mw=round(incremental_peak_mw, 2),
        transformer_overload_count=int(overloaded),
        panel_upgrade_household_pct=round(panel_upgrade_pct, 3),
    )
