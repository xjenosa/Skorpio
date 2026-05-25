"""
Stage 2 of Investment Optimizer — load the utility's at-risk asset catalog.
"""
from backend.agents.base_agent import BaseAgent
from backend.models.investment import GridAsset, InvestmentSpec
from backend.services.utility_assets import load_assets


class AssetCatalogAgent(BaseAgent):
    async def load_catalog(
        self,
        spec: InvestmentSpec,
        progress_callback=None,
    ) -> tuple[list[GridAsset], bool]:
        """Returns (assets, is_synthesized)."""
        if progress_callback:
            await progress_callback(f"Loading {spec.utility} asset catalog...", 18)
        assets, synthesized = load_assets(spec.utility, spec.province)
        if progress_callback:
            n_crit = sum(1 for a in assets if a.criticality == "critical")
            await progress_callback(
                f"Loaded {len(assets)} asset(s) — {n_crit} critical "
                f"({'synthesized' if synthesized else 'cataloged'})",
                25,
            )
        return assets, synthesized
