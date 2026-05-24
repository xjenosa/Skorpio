"""
Stage 2 of Expansion Planner — load the operator's existing footprint.
Enriches per-site carbon intensity from ElectricityMaps when the key is set.
"""
from backend.agents.base_agent import BaseAgent
from backend.models.expansion import ExpansionSpec, OperatorFootprint
from backend.services.operator_footprint import enrich_with_live_carbon, load_footprint


class OperatorFootprintAgent(BaseAgent):
    async def load(
        self,
        spec: ExpansionSpec,
        progress_callback=None,
    ) -> OperatorFootprint:
        if progress_callback:
            await progress_callback(f"Loading {spec.operator} footprint...", 18)
        footprint = load_footprint(spec.operator)

        if progress_callback:
            await progress_callback(
                f"Fetching live ElectricityMaps carbon intensity for {len({s.grid_zone for s in footprint.sites if s.grid_zone})} zone(s)...",
                22,
            )
        enriched = await enrich_with_live_carbon(footprint)

        if progress_callback:
            await progress_callback(
                f"Loaded {len(footprint.sites)} site(s) · "
                f"{footprint.total_current_capacity_mw:.0f} MW operating · "
                f"{enriched} zone(s) enriched live"
                + (" (synthesized)" if footprint.is_synthesized else ""),
                28,
            )
        return footprint
