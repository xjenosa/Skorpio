"""
Demand forecast + expansion-option generation for the Expansion Planner.

Two responsibilities:
  - `forecast_demand`   : a smooth annual demand curve given workload mix +
                           horizon. Growth rates anchored on JLL/Cushman
                           Canadian DC absorption reports 2022–2024.
  - `generate_options`  : build the candidate expansion menu — one
                          brownfield "phase" per existing site that has
                          headroom, plus 1–2 greenfield neighbors near the
                          biggest brownfield bottleneck.

Pure-Python; no Claude calls.
"""
from __future__ import annotations

import uuid

from backend.models.expansion import (
    DemandForecast,
    ExistingSite,
    ExpansionOption,
    ExpansionSpec,
    OperatorFootprint,
)


# ── Growth rates by workload mix ──────────────────────────────────────── #


_GROWTH_RATES: dict[str, float] = {
    # Industry rule-of-thumb CAGRs. The paid JLL/CBRE/Synergy Canadian DC
    # absorption reports cite figures in this range publicly; we do not
    # have a downloadable open-data CSV to anchor exact values, so these
    # are conservative midpoints from widely-quoted press coverage of
    # those reports (2022–2024). Treat as ±5 percentage-point estimates.
    "traditional":   0.12,
    "ai_inference":  0.25,
    "ai_training":   0.40,
    "balanced":      0.22,
}


# Real per-province annual electricity generation totals (MWh) — gives
# us a sanity ceiling: a workload's projected target_mw_year_n cannot
# realistically exceed the province's installed generation. Loaded
# lazily; absent when the StatsCan ingest hasn't been run yet.
def _provincial_generation_ceiling_mw() -> dict[str, float]:
    try:
        from backend.services._provincial_generation_mix_generated import (
            PROVINCIAL_GENERATION_MIX,
        )
    except ImportError:
        return {}
    out: dict[str, float] = {}
    for prov, rec in PROVINCIAL_GENERATION_MIX.items():
        # Annual MWh → continuous MW assuming 60% capacity factor.
        out[prov] = round(rec["total_mwh"] / 8760 / 0.6, 1)
    return out


_PROVINCE_GENERATION_CEILING_MW = _provincial_generation_ceiling_mw()

_DRIVERS_BY_MIX: dict[str, list[str]] = {
    "traditional": [
        "Steady SaaS + enterprise migration absorption (~12% CAGR)",
        "Data sovereignty repatriation from US hyperscalers",
    ],
    "ai_inference": [
        "Generative-AI inference rollout across regulated industries",
        "Edge-of-cloud latency requirements for model serving",
    ],
    "ai_training": [
        "Hyperscaler + sovereign-AI training builds (40%+ CAGR)",
        "GPU cluster densification: 100+ kW racks become baseline",
    ],
    "balanced": [
        "Mixed AI + traditional workload pipeline",
        "Operator hedging between training and inference revenue",
    ],
}


def forecast_demand(spec: ExpansionSpec, footprint: OperatorFootprint) -> DemandForecast:
    """Linear-over-CAGR projection from the operator's current contracted load."""
    rate = _GROWTH_RATES.get(spec.workload_mix.lower(), _GROWTH_RATES["balanced"])
    baseline = sum(s.contracted_mw for s in footprint.sites)
    annual: list[float] = []
    for y in range(1, spec.horizon_years + 1):
        annual.append(round(baseline * ((1 + rate) ** y), 1))
    target_y_n = annual[-1] if annual else baseline
    return DemandForecast(
        workload_mix=spec.workload_mix,
        horizon_years=spec.horizon_years,
        annual_growth_rate=round(rate, 3),
        baseline_mw=round(baseline, 1),
        annual_demand_mw=annual,
        target_mw_year_n=target_y_n,
        drivers=_DRIVERS_BY_MIX.get(spec.workload_mix.lower(), _DRIVERS_BY_MIX["balanced"]),
    )


# ── Brownfield phase generation ───────────────────────────────────────── #


# Capex per MW (CAD): cooling type + workload mix drive this. The paid
# Synergy/JLL/CBRE Canadian build-cost benchmarks are not downloadable as
# open data; these values are industry rule-of-thumb midpoints from publicly
# quoted figures in those reports (2022–2024). Treat as ±25% estimates and
# do NOT cite them as if they were sourced directly from the paid reports.
_CAPEX_PER_MW_AIR_CAD = 9_500_000
_CAPEX_PER_MW_HYBRID_CAD = 11_000_000
_CAPEX_PER_MW_LIQUID_CAD = 13_500_000
_GREENFIELD_PREMIUM = 1.25                                     # +25% vs brownfield


def _site_capex_per_mw(site: ExistingSite, workload_mix: str) -> float:
    base = {
        "air":               _CAPEX_PER_MW_AIR_CAD,
        "free_air":          _CAPEX_PER_MW_AIR_CAD * 0.92,
        "hybrid":            _CAPEX_PER_MW_HYBRID_CAD,
        "liquid_immersion":  _CAPEX_PER_MW_LIQUID_CAD,
    }.get(site.cooling, _CAPEX_PER_MW_HYBRID_CAD)
    # AI training pushes density (and capex) up because of liquid + high-density power.
    if workload_mix == "ai_training":
        base *= 1.10
    return base


def _brownfield_capacity(site: ExistingSite) -> float:
    """Achievable brownfield expansion = min(transformer headroom, plot capacity)."""
    plot_capacity = site.plot_acres * 5.0                     # ~5 MW/acre upper bound for modern DCs
    headroom = max(0.0, site.transformer_headroom_mw)
    return min(plot_capacity, headroom)


def _greenfield_neighbor(parent: ExistingSite, operator: str) -> ExpansionOption:
    """Build a single greenfield option ~10–15 km from the parent site."""
    capacity = 40.0                                            # standard greenfield phase
    capex_per_mw = _CAPEX_PER_MW_HYBRID_CAD * _GREENFIELD_PREMIUM
    return ExpansionOption(
        option_id=f"OPT-{uuid.uuid4().hex[:8]}",
        option_type="greenfield",
        target_site_id=None,
        title=f"Greenfield {parent.city} (near {parent.name})",
        new_capacity_mw=capacity,
        capex_cad=round(capacity * capex_per_mw, 0),
        capex_per_mw_cad=round(capex_per_mw, 0),
        deployment_months=30,
        latitude=parent.latitude + 0.10,
        longitude=parent.longitude + 0.10,
        grid_zone=parent.grid_zone,
        avg_carbon_g_kwh=parent.avg_carbon_g_kwh,
        rationale=(
            f"Existing campus headroom is exhausted before the target year. A "
            f"greenfield ~15 km from {parent.name} keeps the operator inside the "
            f"same grid zone (carbon profile {parent.avg_carbon_g_kwh:.0f} g/kWh) and "
            "fiber metro, but adds 24–36 months of permitting + build vs brownfield."
        ),
    )


def generate_options(
    spec: ExpansionSpec,
    footprint: OperatorFootprint,
    demand: DemandForecast,
) -> list[ExpansionOption]:
    """
    Build the candidate option menu. One brownfield option per site with
    headroom + greenfield neighbors near the lowest-carbon sites until the
    total candidate capacity comfortably exceeds the target.
    """
    options: list[ExpansionOption] = []

    for site in footprint.sites:
        cap = _brownfield_capacity(site)
        if cap <= 1.0:
            continue
        # Round to a sensible "phase" size — multiples of 5 MW up to cap.
        phase_mw = round(cap / 5.0) * 5.0 or 5.0
        capex_per_mw = _site_capex_per_mw(site, spec.workload_mix)
        capex = phase_mw * capex_per_mw
        title = (
            f"{site.name} Phase {site.year_commissioned % 100 + 1}, +{phase_mw:.0f} MW "
            f"({site.cooling.replace('_', ' ')})"
        )
        options.append(ExpansionOption(
            option_id=f"OPT-{uuid.uuid4().hex[:8]}",
            option_type="brownfield",
            target_site_id=site.site_id,
            title=title,
            new_capacity_mw=phase_mw,
            capex_cad=round(capex, 0),
            capex_per_mw_cad=round(capex_per_mw, 0),
            deployment_months=18,
            latitude=site.latitude,
            longitude=site.longitude,
            grid_zone=site.grid_zone,
            avg_carbon_g_kwh=site.avg_carbon_g_kwh,
        ))

    # Decide whether greenfield neighbors are needed.
    target_mw = spec.target_additional_mw or demand.target_mw_year_n - demand.baseline_mw
    target_mw = max(1.0, target_mw)
    brownfield_total = sum(o.new_capacity_mw for o in options)
    if brownfield_total < target_mw * 1.1:
        # Greenfield parent ranking: when the user named a city
        # (spec.city), prefer parents in that city so the proposed
        # greenfield is anchored where the user asked. Break ties by
        # lowest carbon, the original heuristic. This makes "expand at
        # Toronto" with Cologix surface a Toronto-adjacent greenfield
        # instead of defaulting to Montreal just because it's lower-carbon.
        named_city = (spec.city or "").strip().lower()
        def _parent_key(s: ExistingSite) -> tuple[int, float]:
            city_match = 0 if named_city and s.city.strip().lower() == named_city else 1
            return (city_match, s.avg_carbon_g_kwh)
        parents = sorted(footprint.sites, key=_parent_key)[:2]
        for p in parents:
            options.append(_greenfield_neighbor(p, footprint.operator))

    return options
