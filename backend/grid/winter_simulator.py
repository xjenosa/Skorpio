"""
Hourly winter-peak load simulator.

Given a distribution network and a cold event, compute the hour-by-hour
electrical load profile for each scenario (Conservative / Moderate /
Aggressive electrification).

Decomposes total load into:
  - base_load          (lighting, appliances, water heat — non-temp-driven)
  - heat_pump          (compressor draw after COP penalty)
  - backup_resistance  (auxiliary heat when HP can't keep up)
  - baseboard          (legacy direct-resistance heating)
  - ev                 (charging draw with cold-weather penalty)
  - other              (commercial, industrial, etc.)
"""
from backend.models.winter_peak import (
    ColdEvent,
    DistributionNetwork,
    Feeder,
    HourlyLoadPoint,
    HourlyLoadProfile,
    ScenarioPreset,
    Substation,
)
from backend.services.heat_pump_cop import (
    cop_at_temp,
    ev_cold_load_factor,
    hp_electrical_split,
)
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# ── Per-customer assumptions ──────────────────────────────────────────── #
# These are residential averages, calibrated against StatsCan SHEU 2019 +
# NRCan Comprehensive Energy Use Database 2023.

DESIGN_HEATING_LOAD_KW = 8.0            # design-day heat load for an average detached home (-25°C indoor 21°C)
BASE_LOAD_KW_PER_CUSTOMER = 1.6         # always-on residential (lights + plugs + water heat baseline)
EV_BASE_DRAW_KW = 7.2                   # average L2 charger draw, AVERAGED across the day (not peak hour)
EV_COINCIDENCE_FACTOR = 0.45            # fraction of EV-owning households charging at any given evening hour
HEAT_PUMP_COP_TYPE = "standard_ashp"    # default; mix in cold-climate later if needed


# ── Hour-of-day diurnal shape ─────────────────────────────────────────── #


def _diurnal_factor(hour_of_day: int) -> float:
    """
    Multiplicative factor on baseload by hour of day. Two peaks (morning
    + evening), trough overnight. Calibrated to typical residential profile.
    """
    # Approximate shape: morning ramp 6-9am, afternoon dip, evening peak 17-21
    shape = {
        0: 0.70, 1: 0.65, 2: 0.62, 3: 0.60, 4: 0.62, 5: 0.70,
        6: 0.85, 7: 1.05, 8: 1.10, 9: 1.00, 10: 0.92, 11: 0.90,
        12: 0.92, 13: 0.92, 14: 0.92, 15: 0.95, 16: 1.05, 17: 1.20,
        18: 1.30, 19: 1.32, 20: 1.25, 21: 1.15, 22: 1.00, 23: 0.85,
    }
    return shape.get(hour_of_day % 24, 1.0)


def _ev_hour_factor(hour_of_day: int) -> float:
    """
    EV charging concentrates evening (overnight L2 charging). Negligible
    midday for residential.
    """
    if hour_of_day in (18, 19, 20, 21, 22, 23):
        return 1.5                                   # peak charging window
    if hour_of_day in (0, 1, 2, 3, 4, 5):
        return 0.9                                   # overnight tail
    if hour_of_day in (6, 7, 8):
        return 0.4                                   # morning top-up
    return 0.15                                      # daytime trickle


# ── Per-feeder hourly load ────────────────────────────────────────────── #


def _feeder_hour_load(
    feeder: Feeder,
    temp_c: float,
    hour_of_day: int,
    scenario: ScenarioPreset,
) -> dict:
    """
    Compute one feeder's load at one hour. Returns a kW breakdown.

    Scenario applies adoption uplift to the feeder's baseline mix:
        new_hp_share = base_hp + (1 - base_hp) * scenario.heat_pump_adoption_pct
    Customers shift FROM their existing system INTO heat pumps. Baseboard
    is preserved (electric homes typically swap to HP, gas doesn't switch).
    """
    cust = feeder.customer_count
    mix = feeder.primary_heating_mix

    # Apply scenario uplift: scenario adoption represents *target* HP share.
    # Adoption can only grow, never shrink (hence max).
    target_hp_share = max(mix.get("heat_pump", 0.0), scenario.heat_pump_adoption_pct)
    # New HP customers come proportionally from gas + oil + (some) baseboard
    delta_hp = target_hp_share - mix.get("heat_pump", 0.0)
    available_to_convert = mix.get("gas", 0.0) + mix.get("oil", 0.0) + mix.get("baseboard", 0.0) * 0.4
    delta_hp = min(delta_hp, available_to_convert)
    target_hp_share = mix.get("heat_pump", 0.0) + delta_hp

    # Baseboard share stays the same minus the small fraction that converted
    baseboard_converted = (mix.get("baseboard", 0.0) * 0.4) * (delta_hp / max(0.001, available_to_convert))
    new_baseboard_share = max(0.0, mix.get("baseboard", 0.0) - baseboard_converted)

    # Per-customer thermal load at this temperature (linear with delta_T)
    delta_t = max(0.0, 21.0 - temp_c)
    thermal_kw_per_home = DESIGN_HEATING_LOAD_KW * (delta_t / 46.0)

    # Heat pump electric draw (per HP-equipped home). The compressor pulls
    # its rated electrical input while running and delivers thermal output
    # = input × COP. When the temperature-derated capacity can't cover the
    # full thermal demand, auxiliary resistance fills the gap on top of the
    # compressor load (not in place of it). See hp_electrical_split() for
    # the lockout behavior at extreme cold.
    hp_electric_per_home, backup_electric_per_home = hp_electrical_split(
        temp_c, thermal_kw_per_home, HEAT_PUMP_COP_TYPE,
    )

    # Aggregate by share
    n_hp = cust * target_hp_share
    n_baseboard = cust * new_baseboard_share

    heat_pump_kw = n_hp * hp_electric_per_home
    backup_kw = n_hp * backup_electric_per_home
    baseboard_kw = n_baseboard * thermal_kw_per_home

    # Base load (non-temperature-sensitive)
    diurnal = _diurnal_factor(hour_of_day)
    base_kw = cust * BASE_LOAD_KW_PER_CUSTOMER * diurnal

    # EV load
    ev_share = max(feeder.ev_penetration_pct / 100.0, scenario.ev_adoption_pct)
    ev_factor = ev_cold_load_factor(temp_c)
    ev_hour_factor = _ev_hour_factor(hour_of_day)
    ev_kw = cust * ev_share * EV_BASE_DRAW_KW * EV_COINCIDENCE_FACTOR * ev_factor * ev_hour_factor

    # Convert to MW
    return {
        "base_load_mw": base_kw / 1000.0,
        "heat_pump_load_mw": heat_pump_kw / 1000.0,
        "backup_resistance_mw": backup_kw / 1000.0,
        "baseboard_load_mw": baseboard_kw / 1000.0,
        "ev_load_mw": ev_kw / 1000.0,
    }


# ── Network-wide simulation ──────────────────────────────────────────── #


def simulate_network(
    network: DistributionNetwork,
    cold_event: ColdEvent,
    scenario: ScenarioPreset,
    other_load_baseline_mw: float | None = None,
) -> HourlyLoadProfile:
    """
    Run the hourly load simulation across the whole network for one scenario.
    Returns a HourlyLoadProfile with per-hour breakdown and peak summary.
    """
    if other_load_baseline_mw is None:
        # Estimate "other" (commercial + industrial baseline) as 35% of historical winter peak
        other_load_baseline_mw = network.baseline_winter_peak_mw * 0.35

    points: list[HourlyLoadPoint] = []
    for hourly_temp in cold_event.hourly_curve:
        h = hourly_temp.hour_offset
        temp = hourly_temp.temp_c
        hod = h % 24

        agg_base = 0.0
        agg_hp = 0.0
        agg_backup = 0.0
        agg_baseboard = 0.0
        agg_ev = 0.0
        for f in network.feeders:
            row = _feeder_hour_load(f, temp, hod, scenario)
            agg_base += row["base_load_mw"]
            agg_hp += row["heat_pump_load_mw"]
            agg_backup += row["backup_resistance_mw"]
            agg_baseboard += row["baseboard_load_mw"]
            agg_ev += row["ev_load_mw"]

        # Other load: commercial, industrial, lighting — also has diurnal shape
        # but flatter because commercial runs daytime; industrial runs continuously.
        other = other_load_baseline_mw * (0.85 + 0.20 * _diurnal_factor(hod))

        total = agg_base + agg_hp + agg_backup + agg_baseboard + agg_ev + other
        points.append(HourlyLoadPoint(
            hour_offset=h,
            temp_c=temp,
            base_load_mw=round(agg_base, 1),
            heat_pump_load_mw=round(agg_hp, 1),
            backup_resistance_mw=round(agg_backup, 1),
            baseboard_load_mw=round(agg_baseboard, 1),
            ev_load_mw=round(agg_ev, 1),
            other_load_mw=round(other, 1),
            total_load_mw=round(total, 1),
        ))

    # Find peak
    peak_idx = max(range(len(points)), key=lambda i: points[i].total_load_mw)
    peak = points[peak_idx]
    nameplate_mw = sum(s.nameplate_mva * 0.95 for s in network.substations)  # MVA * pf
    headroom = nameplate_mw - peak.total_load_mw

    return HourlyLoadProfile(
        scenario_name=scenario.name,
        cold_event_id=cold_event.event_id,
        hours=points,
        peak_load_mw=peak.total_load_mw,
        peak_hour_offset=peak.hour_offset,
        peak_temp_c=peak.temp_c,
        headroom_at_peak_mw=round(headroom, 1),
        headroom_pct_at_peak=round((headroom / nameplate_mw) * 100.0, 1) if nameplate_mw > 0 else 0.0,
    )


def per_feeder_peak_load(
    network: DistributionNetwork,
    cold_event: ColdEvent,
    scenario: ScenarioPreset,
    other_load_baseline_mw: float | None = None,
) -> dict[str, float]:
    """
    Find each feeder's peak hour load (MVA) under the given scenario.
    Used by the risk-scoring agent to compute capacity utilization.

    The simulator's system aggregate adds an "other" overlay representing
    commercial / industrial / large-customer load (~35% of historical
    winter peak). The synthesized topology only has residential feeders,
    so we distribute that overlay across feeders proportional to their
    rated capacity — bigger feeders carry more, matching how downtown
    feeders carry more commercial load than suburban residential ones.

    Without this distribution, per-feeder utilization was understated by
    ~30%, which caused the FeederRisk scorer to keep all feeders below
    its 0.5 at-risk threshold even when the system aggregate was failing.
    """
    if other_load_baseline_mw is None:
        other_load_baseline_mw = network.baseline_winter_peak_mw * 0.35

    # Weight share by rated capacity so larger feeders absorb proportionally
    # more of the commercial overlay. Falls back to equal split if all
    # ratings are zero (defensive).
    total_rated = sum(f.rated_capacity_mva for f in network.feeders)
    if total_rated <= 0:
        share_per_feeder = {f.feeder_id: 1.0 / max(1, len(network.feeders))
                            for f in network.feeders}
    else:
        share_per_feeder = {f.feeder_id: f.rated_capacity_mva / total_rated
                            for f in network.feeders}

    results: dict[str, float] = {}
    for f in network.feeders:
        peak_mw = 0.0
        for hourly_temp in cold_event.hourly_curve:
            row = _feeder_hour_load(f, hourly_temp.temp_c, hourly_temp.hour_offset % 24, scenario)
            hod = hourly_temp.hour_offset % 24
            other_hourly = other_load_baseline_mw * (0.85 + 0.20 * _diurnal_factor(hod))
            other_per_feeder = other_hourly * share_per_feeder[f.feeder_id]
            mw = (row["base_load_mw"] + row["heat_pump_load_mw"] +
                  row["backup_resistance_mw"] + row["baseboard_load_mw"] +
                  row["ev_load_mw"] + other_per_feeder)
            peak_mw = max(peak_mw, mw)
        # Convert MW → MVA assuming 0.95 power factor
        results[f.feeder_id] = round(peak_mw / 0.95, 2)
    return results
