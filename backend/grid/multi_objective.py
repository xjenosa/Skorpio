"""
Multi-objective Pareto optimisation for siting candidates.

Scores sites across 6 objectives (all normalised 0-1, higher = better):
  cost_economics          — inverted levelized cost of electricity (LCOE)
  carbon_intensity        — cleanliness of the marginal MWh
  latency_fit             — how well the site meets the workload latency cap
  transmission_headroom   — capacity-to-spare on the POI / local network
  deployment_speed        — inverted time-to-power
  operational_resilience  — water / weather / policy resilience

Then runs non-dominated sorting (NSGA-II style) to assign Pareto front ranks.
"""
from __future__ import annotations
from typing import Optional

from backend.models.site import Site, ParetoObjectives, ObjectiveWeights


# ── Individual objective predictors ────────────────────────────────────────── #

def normalize_lcoe(lcoe_usd_mwh: float) -> float:
    """Map $/MWh → 0-1 linearly ($20 → 1.0, $100 → 0.0)."""
    clamped = max(20.0, min(100.0, lcoe_usd_mwh))
    return round((100.0 - clamped) / 80.0, 2)


def predict_carbon_intensity(profile, region_carbon_g_co2_kwh: Optional[float]) -> float:
    """
    Cleanliness of the marginal MWh. 80 gCO₂/kWh → 1.0, 700 gCO₂/kWh → 0.0.
    """
    if region_carbon_g_co2_kwh is None:
        return 0.5
    clamped = max(80.0, min(700.0, region_carbon_g_co2_kwh))
    return round((700.0 - clamped) / 620.0, 2)


def predict_latency_fit(profile, target_latency_ms: Optional[float]) -> float:
    """
    1.0 if the site beats the target by 2x, 0.0 if it misses by 2x.
    """
    if profile is None or profile.fiber_latency_ms is None or not target_latency_ms:
        return 0.5
    ratio = target_latency_ms / max(profile.fiber_latency_ms, 0.01)
    if ratio >= 2.0:
        return 1.0
    if ratio <= 0.5:
        return 0.0
    return round((ratio - 0.5) / 1.5, 2)


def predict_headroom(profile, target_capacity_mw: float) -> float:
    """Transmission headroom relative to the workload capacity."""
    if profile is None or profile.transmission_headroom_mw is None or not target_capacity_mw:
        return 0.5
    ratio = profile.transmission_headroom_mw / max(target_capacity_mw, 1.0)
    if ratio >= 2.0:
        return 1.0
    if ratio <= 0.5:
        return 0.0
    return round((ratio - 0.5) / 1.5, 2)


def predict_deployment_speed(profile) -> float:
    """Time-to-power: 6 months → 1.0, 36 months → 0.0."""
    if profile is None or profile.deployment_months is None:
        return 0.5
    clamped = max(6.0, min(36.0, profile.deployment_months))
    return round((36.0 - clamped) / 30.0, 2)


def predict_resilience(profile) -> float:
    """Composite of PUE, water draw and policy flags."""
    if profile is None:
        return 0.5
    score = 1.0
    if profile.has_policy_blockers:
        score -= 0.30
    if profile.has_alerts:
        score -= 0.20
    if profile.pue is not None:
        if profile.pue > 1.45:
            score -= 0.20
        elif profile.pue > 1.30:
            score -= 0.10
    if profile.water_l_per_mwh is not None and profile.water_l_per_mwh > 2.0:
        score -= 0.10
    return round(max(0.0, min(1.0, score)), 2)


# ── Main objective computation ──────────────────────────────────────────────── #

def compute_pareto_objectives(
    site: Site,
    lcoe_usd_mwh: Optional[float],
    region_carbon_g_co2_kwh: Optional[float],
    target_latency_ms: Optional[float],
    target_capacity_mw: float,
) -> ParetoObjectives:
    profile = site.profile

    return ParetoObjectives(
        cost_economics        = normalize_lcoe(lcoe_usd_mwh) if lcoe_usd_mwh is not None else 0.5,
        carbon_intensity      = predict_carbon_intensity(profile, region_carbon_g_co2_kwh),
        latency_fit           = predict_latency_fit(profile, target_latency_ms),
        transmission_headroom = predict_headroom(profile, target_capacity_mw),
        deployment_speed      = predict_deployment_speed(profile),
        operational_resilience = predict_resilience(profile),
    )


# ── Pareto non-dominated sorting ────────────────────────────────────────────── #

def _dominates(a: list[float], b: list[float]) -> bool:
    """True if solution `a` Pareto-dominates `b`."""
    at_least_one_better = False
    for ai, bi in zip(a, b):
        if ai < bi:
            return False
        if ai > bi:
            at_least_one_better = True
    return at_least_one_better


def assign_pareto_ranks(scores: list[list[float]]) -> list[int]:
    """
    NSGA-II non-dominated sorting.
    Returns integer ranks per solution (1 = Pareto front, 2 = second front, …).
    """
    n = len(scores)
    if n == 0:
        return []

    domination_count = [0] * n
    dominated_set    = [[] for _ in range(n)]
    ranks            = [0] * n
    current_front: list[int] = []

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if _dominates(scores[i], scores[j]):
                dominated_set[i].append(j)
            elif _dominates(scores[j], scores[i]):
                domination_count[i] += 1
        if domination_count[i] == 0:
            ranks[i] = 1
            current_front.append(i)

    front_num = 1
    while current_front:
        next_front: list[int] = []
        for i in current_front:
            for j in dominated_set[i]:
                domination_count[j] -= 1
                if domination_count[j] == 0:
                    ranks[j] = front_num + 1
                    next_front.append(j)
        front_num += 1
        current_front = next_front

    return ranks


# ── Weighted scoring ────────────────────────────────────────────────────────── #

def compute_weighted_score(obj: ParetoObjectives, weights: ObjectiveWeights) -> float:
    return round(
        obj.cost_economics         * weights.cost_economics
        + obj.carbon_intensity     * weights.carbon_intensity
        + obj.latency_fit          * weights.latency_fit
        + obj.transmission_headroom * weights.transmission_headroom
        + obj.deployment_speed     * weights.deployment_speed
        + obj.operational_resilience * weights.operational_resilience,
        3,
    )
