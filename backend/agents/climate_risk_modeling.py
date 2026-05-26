"""
Stage 3 of Investment Optimizer — project hazard exposure for every asset
under the target year, then rank.

ArcGIS Living Atlas overlay: when an asset has lat/lon, we pull two
empirical probabilities from authoritative Canadian sources (NRCan
Historical Flood Events, NRCan CWFIS National Fire Database) and
override the heuristic flood / wildfire probabilities in the resulting
ClimateRiskProfile. Both queries are anonymous and free. The Investment
pipeline keeps its province-average fallback when ArcGIS is offline or
the asset has no coordinates.
"""
import asyncio

from backend.agents.base_agent import BaseAgent
from backend.models.investment import ClimateRiskProfile, GridAsset, HazardExposure, InvestmentSpec
from backend.services.arcgis_hazards import (
    empirical_flood_probability,
    empirical_wildfire_probability,
)
from backend.services.climate_hazards import assess_asset


class ClimateRiskModelingAgent(BaseAgent):
    # Source citations to surface on the InvestmentPlan when at least
    # one asset successfully picked up real empirical data from the
    # corresponding Living Atlas-curated layer. Populated during
    # assess_all and read by the orchestrator.
    last_run_sources: list[str] = []

    async def assess_all(
        self,
        spec: InvestmentSpec,
        assets: list[GridAsset],
        progress_callback=None,
        progress_offset_pct: int = 30,
    ) -> list[ClimateRiskProfile]:
        # Pre-fetch empirical flood + wildfire probabilities for every
        # asset that has coordinates. Run in parallel so the network
        # latency hides behind one batch instead of N sequential GETs.
        # Returns None when the asset has no lat/lon or the live query
        # failed; in either case we silently keep the heuristic value.
        async def _empirical(asset: GridAsset) -> tuple[float | None, float | None]:
            if asset.latitude is None or asset.longitude is None:
                return (None, None)
            flood_t = empirical_flood_probability(asset.latitude, asset.longitude)
            fire_t = empirical_wildfire_probability(asset.latitude, asset.longitude)
            try:
                flood, fire = await asyncio.gather(flood_t, fire_t, return_exceptions=True)
                return (
                    flood if isinstance(flood, (float, int)) else None,
                    fire if isinstance(fire, (float, int)) else None,
                )
            except Exception:
                return (None, None)

        empirical = await asyncio.gather(*(_empirical(a) for a in assets))
        flood_hits = sum(1 for f, _ in empirical if f is not None)
        wildfire_hits = sum(1 for _, w in empirical if w is not None)

        profiles: list[ClimateRiskProfile] = []
        n = max(1, len(assets))
        for i, asset in enumerate(assets):
            profile = assess_asset(
                asset,
                province=spec.province,
                target_year=spec.target_year,
                priority_hazards=spec.priority_hazards,
            )
            # Overlay empirical probabilities onto the heuristic-built
            # exposures. The annual_probability flip cascades into
            # aggregate_annual_loss_cad and the risk_tier classification
            # so the downstream optimizer prioritizes real hot zones.
            flood_emp, fire_emp = empirical[i]
            _overlay_empirical(profile, flood_emp, fire_emp)
            profiles.append(profile)
            if progress_callback:
                pct = progress_offset_pct + int((i / n) * 20)
                await progress_callback(
                    f"Assessed {asset.name} → ${profile.aggregate_annual_loss_cad/1e6:.1f}M/yr ({profile.risk_tier})",
                    pct,
                )

        # Stash the citations for the synthesis agent to surface in
        # InvestmentPlan.sources. Only emit when we actually used real
        # data for at least one asset.
        self.last_run_sources = []
        if flood_hits:
            self.last_run_sources.append(
                "NRCan Historical Flood Events (Esri Living Atlas): "
                f"empirical flood probability applied to {flood_hits} of {n} asset(s)"
            )
        if wildfire_hits:
            self.last_run_sources.append(
                "NRCan CWFIS National Fire Database (Esri Living Atlas): "
                f"empirical wildfire probability applied to {wildfire_hits} of {n} asset(s)"
            )

        # Rank by aggregate annual loss (highest = rank 1)
        ranked = sorted(profiles, key=lambda p: p.aggregate_annual_loss_cad, reverse=True)
        for r, p in enumerate(ranked, start=1):
            p.rank = r
        return profiles


def _overlay_empirical(
    profile: ClimateRiskProfile,
    flood_p: float | None,
    fire_p: float | None,
) -> None:
    """Rewrite flood / wildfire HazardExposure probabilities in-place.

    `annual_probability` is replaced; the per-event loss and CHOL stay
    untouched (those are asset-property-driven, not climate-driven).
    `aggregate_annual_loss_cad` and `risk_tier` are recomputed so the
    downstream ranking sees the corrected exposure.
    """
    if flood_p is None and fire_p is None:
        return

    for ex in profile.hazard_exposures:
        if ex.hazard == "flood" and flood_p is not None:
            ex.annual_probability = round(flood_p, 3)
            ex.rationale = (
                f"Flood probability set from NRCan Historical Flood Events "
                f"(via Esri Living Atlas). Empirical rate at asset location."
            )
        elif ex.hazard == "wildfire" and fire_p is not None:
            ex.annual_probability = round(fire_p, 3)
            ex.rationale = (
                f"Wildfire probability set from NRCan CWFIS National Fire Database "
                f"(via Esri Living Atlas). Empirical rate at asset location."
            )

    new_total = sum(
        ex.annual_probability * ex.expected_loss_cad
        for ex in profile.hazard_exposures
    )
    profile.aggregate_annual_loss_cad = round(new_total, 0)
    if new_total >= 4_000_000:
        profile.risk_tier = "critical"
    elif new_total >= 1_500_000:
        profile.risk_tier = "high"
    elif new_total >= 500_000:
        profile.risk_tier = "medium"
    else:
        profile.risk_tier = "low"
