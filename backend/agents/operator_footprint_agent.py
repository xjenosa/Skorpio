"""
Stage 2 of Expansion Planner — load the operator's existing footprint.
Enriches per-site carbon intensity from the provincial fuel mix and
IPCC AR5 emission factors.
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
                f"Computing carbon intensity for {len({s.grid_zone for s in footprint.sites if s.grid_zone})} provincial zone(s)...",
                22,
            )
        enriched = await enrich_with_live_carbon(footprint)

        # ArcGIS GeoEnrichment overlay — when the user named a Canadian
        # city in the expansion spec, fetch real Census Subdivision
        # demographics (population + households) and append a source
        # citation to the footprint. This grounds the executive summary's
        # "user named city" routing block in authoritative numbers
        # instead of leaving it as just a place name.
        if spec.city:
            try:
                from backend.services.arcgis_enrichment import enrich_city, is_configured as _arcgis_ok
                if _arcgis_ok():
                    city_data = await enrich_city(spec.city)
                    if city_data:
                        footprint.sources.append(
                            "ArcGIS GeoEnrichment (Esri Canada): "
                            f"{city_data.get('city_name', spec.city)}: "
                            f"{city_data.get('households', 0):,} households, "
                            f"population {city_data.get('population', 0):,}"
                        )
            except Exception as e:
                self.logger.debug(f"ArcGIS city enrichment skipped: {e}")

        if progress_callback:
            await progress_callback(
                f"Loaded {len(footprint.sites)} site(s) · "
                f"{footprint.total_current_capacity_mw:.0f} MW operating · "
                f"{enriched} zone(s) enriched live"
                + (" (synthesized)" if footprint.is_synthesized else ""),
                28,
            )
        return footprint
