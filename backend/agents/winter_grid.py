"""
Winter Grid Intelligence Agent — Stage 2 of the Winter Peak pipeline.

Loads (or builds) the distribution network for the target city.

Today this returns the synthesized topology from feeder_topology.py. When
real utility GIS data becomes available (via partnership), this agent will
prefer real data and fall back to synthesis with a clear UI label.
"""
from backend.agents.base_agent import BaseAgent
from backend.agents.grounding import GROUNDING_RULES
from backend.grid.feeder_topology import build_distribution_network, get_city_profile
from backend.models.winter_peak import DistributionNetwork, WinterPeakSpec
from backend.services.canada_grid import get_provincial_snapshot


SYSTEM_WINTER_GRID = """You are a distribution-grid analyst describing a
city's electrical grid in plain English to a non-technical audience.
Be specific about scale (number of substations, number of customers,
historical winter peak in MW). Be honest about what's modeled vs. measured.""" + GROUNDING_RULES


class WinterGridAgent(BaseAgent):
    """Stage 2: WinterPeakSpec → DistributionNetwork."""

    async def load_network(
        self,
        spec: WinterPeakSpec,
        progress_callback=None,
    ) -> DistributionNetwork:
        """
        Build the synthesized distribution network and (optionally) annotate it
        with live provincial snapshot data from canada_grid.
        """
        if progress_callback:
            await progress_callback(
                f"Loading distribution topology for {spec.city}...",
                15,
            )

        # Map city back to the topology key
        city_key = spec.city.lower().split(",")[0].strip()
        try:
            network = build_distribution_network(city_key)
        except ValueError as e:
            self.logger.warning(f"Topology lookup failed: {e}; defaulting to mississauga")
            network = build_distribution_network("mississauga")

        self.logger.info(
            f"Loaded {network.city} network: "
            f"{len(network.substations)} substations, "
            f"{len(network.feeders)} feeders, "
            f"baseline winter peak {network.baseline_winter_peak_mw} MW"
        )

        # Best-effort enrichment: attach provincial real-time snapshot info to
        # the sources list. Non-fatal if it fails.
        if progress_callback:
            await progress_callback(
                f"Cross-referencing {spec.iso_zone} provincial data...",
                22,
            )
        try:
            snapshot = await get_provincial_snapshot(spec.province)
            if snapshot:
                network.sources.append(
                    f"Provincial snapshot ({spec.province}): "
                    f"current load {snapshot.get('demand_mw', 'n/a')} MW"
                )
        except Exception as e:
            self.logger.debug(f"Provincial snapshot enrichment skipped: {e}")

        return network

    async def describe_network(self, network: DistributionNetwork) -> str:
        """Plain-English description for the report's network section."""
        prompt = f"""Describe this distribution network in 3-4 sentences for a
non-technical reader:

City: {network.city}
Utility: {network.utility}
Province: {network.province}
Substations: {len(network.substations)}
Feeders: {len(network.feeders)}
Total customers (sum across feeders): {sum(f.customer_count for f in network.feeders):,}
Historical winter peak: {network.baseline_winter_peak_mw} MW
Topology source: {'modeled from public utility filings' if network.is_synthesized else 'real utility GIS data'}

Mention scale, the utility name, and (if synthesized) be honest that
per-feeder values are modeled. Avoid acronyms unless defined."""

        try:
            return (await self.ask_claude(SYSTEM_WINTER_GRID, prompt, max_tokens=300)).strip()
        except Exception as e:
            self.logger.warning(f"Network description failed: {e}")
            return (
                f"{network.city} is served by {network.utility} via "
                f"{len(network.substations)} substations and "
                f"{len(network.feeders)} feeders, totalling about "
                f"{sum(f.customer_count for f in network.feeders):,} customers. "
                f"Historical winter peak: {network.baseline_winter_peak_mw} MW."
            )
