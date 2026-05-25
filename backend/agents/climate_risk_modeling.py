"""
Stage 3 of Investment Optimizer — project hazard exposure for every asset
under the target year, then rank.
"""
from backend.agents.base_agent import BaseAgent
from backend.models.investment import ClimateRiskProfile, GridAsset, InvestmentSpec
from backend.services.climate_hazards import assess_asset


class ClimateRiskModelingAgent(BaseAgent):
    async def assess_all(
        self,
        spec: InvestmentSpec,
        assets: list[GridAsset],
        progress_callback=None,
        progress_offset_pct: int = 30,
    ) -> list[ClimateRiskProfile]:
        profiles: list[ClimateRiskProfile] = []
        n = max(1, len(assets))
        for i, asset in enumerate(assets):
            profile = assess_asset(
                asset,
                province=spec.province,
                target_year=spec.target_year,
                priority_hazards=spec.priority_hazards,
            )
            profiles.append(profile)
            if progress_callback:
                pct = progress_offset_pct + int((i / n) * 20)
                await progress_callback(
                    f"Assessed {asset.name} → ${profile.aggregate_annual_loss_cad/1e6:.1f}M/yr ({profile.risk_tier})",
                    pct,
                )

        # Rank by aggregate annual loss (highest = rank 1)
        ranked = sorted(profiles, key=lambda p: p.aggregate_annual_loss_cad, reverse=True)
        for r, p in enumerate(ranked, start=1):
            p.rank = r
        return profiles
