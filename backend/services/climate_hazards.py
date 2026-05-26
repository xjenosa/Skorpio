"""
Climate hazard exposure model for the Investment Optimizer.

Probability + impact estimates per (hazard × asset_type × province) come
from public sources:
  - ECCC Canada in a Changing Climate (CCCS) chapter projections
  - IBC / CatIQ insurance loss reports 2013–2024
  - OEB ice-storm reliability filings (2013 Dec, 2022 Dec)
  - PSC wildfire-grid exposure mapping (BC Hydro 2023)
  - Hydro-Québec 1998 ice storm post-mortem

These are pragmatic, citable estimates — not a peer-reviewed climate model.
The pipeline returns a synthesized risk profile per asset that the optimizer
uses to rank hardening projects by avoided loss per dollar.
"""
from __future__ import annotations

from backend.models.investment import ClimateRiskProfile, GridAsset, HazardExposure


# ── Hazard base rates by province (annual probability per asset) ──────── #


PROVINCE_HAZARD_BASE_PROB: dict[str, dict[str, float]] = {
    "ON": {"ice_storm": 0.08, "heat_wave": 0.14, "wildfire": 0.02, "flood": 0.05, "wind": 0.12},
    "QC": {"ice_storm": 0.12, "heat_wave": 0.10, "wildfire": 0.03, "flood": 0.06, "wind": 0.10},
    "AB": {"ice_storm": 0.04, "heat_wave": 0.12, "wildfire": 0.10, "flood": 0.04, "wind": 0.15},
    "BC": {"ice_storm": 0.02, "heat_wave": 0.18, "wildfire": 0.18, "flood": 0.10, "wind": 0.10},
    "MB": {"ice_storm": 0.07, "heat_wave": 0.10, "wildfire": 0.06, "flood": 0.05, "wind": 0.10},
    "NS": {"ice_storm": 0.10, "heat_wave": 0.06, "wildfire": 0.04, "flood": 0.07, "wind": 0.22},
    "NB": {"ice_storm": 0.09, "heat_wave": 0.06, "wildfire": 0.04, "flood": 0.06, "wind": 0.18},
}


# ── Asset susceptibility multipliers ─────────────────────────────────── #


ASSET_HAZARD_SUSCEPT: dict[str, dict[str, float]] = {
    "transmission_line": {"ice_storm": 1.5, "wind": 1.4, "wildfire": 1.2, "heat_wave": 0.6, "flood": 0.3},
    "substation":        {"ice_storm": 0.7, "wind": 0.5, "wildfire": 0.9, "heat_wave": 1.3, "flood": 1.4},
    "feeder":            {"ice_storm": 1.4, "wind": 1.3, "wildfire": 1.1, "heat_wave": 0.7, "flood": 0.6},
    "transformer":       {"ice_storm": 0.5, "wind": 0.4, "wildfire": 0.8, "heat_wave": 1.5, "flood": 1.6},
}


# Per-event reliability impact (customer-hours lost when this hazard hits this asset).
ASSET_HAZARD_CHOL: dict[str, dict[str, float]] = {
    "transmission_line": {"ice_storm": 120_000, "wind": 80_000, "wildfire": 60_000, "heat_wave": 20_000, "flood": 30_000},
    "substation":        {"ice_storm": 90_000, "wind": 40_000, "wildfire": 70_000, "heat_wave": 35_000, "flood": 60_000},
    "feeder":            {"ice_storm": 16_000, "wind": 12_000, "wildfire": 10_000, "heat_wave": 4_000, "flood": 5_000},
    "transformer":       {"ice_storm": 3_500, "wind": 2_500, "wildfire": 3_000, "heat_wave": 6_000, "flood": 4_500},
}


# Repair + recovery cost per event (CAD), scaled by asset replacement cost share.
ASSET_HAZARD_LOSS_SHARE: dict[str, float] = {
    "ice_storm": 0.06, "wind": 0.04, "wildfire": 0.12, "heat_wave": 0.03, "flood": 0.08,
}


# CCCS multiplier on hazard frequency for the target year (2030 / 2035 / 2050).
def climate_scaling(target_year: int) -> float:
    if target_year <= 2025:
        return 1.0
    if target_year <= 2030:
        return 1.15
    if target_year <= 2035:
        return 1.30
    return 1.60


# Asset-age multiplier on loss given an event (older assets fail harder).
def age_multiplier(age_years: int) -> float:
    if age_years <= 20:
        return 0.7
    if age_years <= 40:
        return 1.0
    if age_years <= 60:
        return 1.3
    return 1.6


def assess_asset(
    asset: GridAsset,
    province: str,
    target_year: int,
    priority_hazards: list[str] | None = None,
) -> ClimateRiskProfile:
    """Build a ClimateRiskProfile for one asset under the target year."""
    base = PROVINCE_HAZARD_BASE_PROB.get(province, PROVINCE_HAZARD_BASE_PROB["ON"])
    suscept = ASSET_HAZARD_SUSCEPT.get(asset.asset_type, ASSET_HAZARD_SUSCEPT["feeder"])
    chol = ASSET_HAZARD_CHOL.get(asset.asset_type, ASSET_HAZARD_CHOL["feeder"])

    scale = climate_scaling(target_year)
    age_mult = age_multiplier(asset.age_years)
    priorities = set(h.lower() for h in (priority_hazards or []))

    exposures: list[HazardExposure] = []
    total_annual = 0.0
    for hazard in ("ice_storm", "heat_wave", "wildfire", "flood", "wind"):
        prob = base.get(hazard, 0.0) * suscept.get(hazard, 1.0) * scale
        if priorities and hazard in priorities:
            prob *= 1.10                          # mild boost for user-flagged hazards
        prob = min(0.95, prob)
        if prob < 0.005:
            continue
        loss_share = ASSET_HAZARD_LOSS_SHARE.get(hazard, 0.04)
        per_event_loss = asset.replacement_cost_cad * loss_share * age_mult
        annual_loss = prob * per_event_loss
        per_event_chol = chol.get(hazard, 5_000) * age_mult
        exposures.append(HazardExposure(
            hazard=hazard,
            annual_probability=round(prob, 3),
            expected_loss_cad=round(per_event_loss, 0),
            customer_hours_lost=round(per_event_chol, 0),
            rationale=(
                f"{hazard.replace('_', ' ').title()} risk for {asset.asset_type.replace('_', ' ')} "
                f"in {province}; age {asset.age_years}y, climate scaling {scale:.2f}×."
            ),
        ))
        total_annual += annual_loss

    if total_annual >= 4_000_000:
        tier = "critical"
    elif total_annual >= 1_500_000:
        tier = "high"
    elif total_annual >= 500_000:
        tier = "medium"
    else:
        tier = "low"

    return ClimateRiskProfile(
        asset_id=asset.asset_id,
        target_year=target_year,
        hazard_exposures=exposures,
        aggregate_annual_loss_cad=round(total_annual, 0),
        risk_tier=tier,
    )
