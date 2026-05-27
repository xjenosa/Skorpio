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
from backend.services.canada_grid import (
    fetch_ieso_hoep_cad_per_mwh,
    get_provincial_snapshot,
)


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

        # Live HOEP enrichment — only relevant for Ontario scenarios. Adds a
        # citation with the most recent cleared wholesale price so the
        # synthesis agent and chat tools can pair the simulated peak with
        # a real wholesale clearing price. Non-fatal on any failure.
        if spec.province == "ON":
            try:
                hoep = await fetch_ieso_hoep_cad_per_mwh()
                if hoep and hoep.get("hoep_cad_per_mwh") is not None:
                    network.sources.append(
                        "IESO HOEP (Hourly Ontario Energy Price, live): "
                        f"${hoep['hoep_cad_per_mwh']:.2f}/MWh at "
                        f"{hoep.get('trading_date', '?')} hour "
                        f"{hoep.get('trading_hour', '?')}"
                    )
            except Exception as e:
                self.logger.debug(f"IESO HOEP enrichment skipped: {e}")

        # Live ECCC alert feed — flags any active cold-weather / winter
        # storm warnings overlapping the city's bounding box. Lights up
        # the "Active alerts" chip whether or not anything is active.
        try:
            from backend.services.eccc_alerts import fetch_active_alerts
            alert_payload = await fetch_active_alerts(spec.city)
            if alert_payload is not None:
                count = alert_payload.get("count", 0)
                if count > 0:
                    events = sorted({a.get("event", "Alert") for a in alert_payload["alerts"]})
                    network.sources.append(
                        f"ECCC active alerts (live): {count} alert(s) "
                        f"intersecting {spec.city}: {', '.join(events)}"
                    )
                else:
                    network.sources.append(
                        f"ECCC active alerts (live): no active alerts for {spec.city}"
                    )
        except Exception as e:
            self.logger.debug(f"ECCC alert enrichment skipped: {e}")

        # Live ArcGIS Living Atlas — RTMA current surface conditions. Pairs
        # the simulated cold-event envelope with what the city's temperature
        # is doing right now. Chip lights up only when the layer returns a
        # usable feature; misconfigured URL or empty response leaves the
        # chip dark rather than throwing.
        try:
            from backend.services.arcgis_rtma import fetch_current_conditions
            rtma = await fetch_current_conditions(spec.city)
            if rtma and rtma.get("temp_c") is not None:
                wind_bit = (
                    f", {rtma['wind_kmh']:.1f} km/h wind"
                    if rtma.get("wind_kmh") is not None else ""
                )
                network.sources.append(
                    f"ArcGIS Living Atlas RTMA (live): {spec.city} "
                    f"{rtma['temp_c']:.1f}°C{wind_bit}"
                )
        except Exception as e:
            self.logger.debug(f"ArcGIS RTMA enrichment skipped: {e}")

        # Live ArcGIS Living Atlas — NWS Watches & Warnings. Cross-border
        # complement to ECCC alerts; useful when severe-weather polygons
        # span the US-Canada line during winter storms.
        try:
            from backend.services.arcgis_nws_alerts import fetch_active_nws_alerts
            nws = await fetch_active_nws_alerts(spec.city)
            if nws is not None:
                count = nws.get("count", 0)
                if count > 0:
                    events = sorted({a.get("event", "Alert") for a in nws["alerts"] if a.get("event")})
                    network.sources.append(
                        f"ArcGIS Living Atlas NWS Watches & Warnings (live): "
                        f"{count} alert(s) intersecting {spec.city}: {', '.join(events)}"
                    )
                else:
                    network.sources.append(
                        f"ArcGIS Living Atlas NWS Watches & Warnings (live): "
                        f"no active alerts for {spec.city}"
                    )
        except Exception as e:
            self.logger.debug(f"ArcGIS NWS alert enrichment skipped: {e}")

        # Live ArcGIS Living Atlas — NOAA HRRR forecast. Pairs the simulated
        # cold-event peak with the actual short-range forecast: "tonight's
        # low is -7°C, stress test models -25°C."
        try:
            from backend.services.arcgis_hrrr import fetch_18h_forecast
            hrrr = await fetch_18h_forecast(spec.city)
            if hrrr and hrrr.get("forecast_low_c") is not None:
                network.sources.append(
                    f"ArcGIS Living Atlas HRRR forecast (live): {spec.city} "
                    f"next {hrrr.get('forecast_horizon_hours', 18)}h low "
                    f"{hrrr['forecast_low_c']:.1f}°C, high "
                    f"{hrrr.get('forecast_high_c', hrrr['forecast_low_c']):.1f}°C"
                )
        except Exception as e:
            self.logger.debug(f"ArcGIS HRRR enrichment skipped: {e}")

        # Live ArcGIS Living Atlas — MODIS snow cover. Context, not a
        # simulator input: shows whether the city is already in winter
        # conditions before the stress event hits.
        try:
            from backend.services.arcgis_snow_cover import fetch_snow_cover
            snow = await fetch_snow_cover(spec.city)
            if snow and snow.get("snow_cover_pct") is not None:
                network.sources.append(
                    f"ArcGIS Living Atlas MODIS snow cover (live): {spec.city} "
                    f"{snow['snow_cover_pct']:.1f}% snow cover"
                )
        except Exception as e:
            self.logger.debug(f"ArcGIS snow-cover enrichment skipped: {e}")

        # ArcGIS city enrichment — anchor the synthesized per-feeder customer
        # counts to a real Census Subdivision household total. The feeder
        # topology is still modeled (we don't have real GIS), but the
        # network-wide customer count now matches the actual municipality
        # rather than the topology generator's heuristic. Adds an Esri
        # source citation so the report shows it isn't fully synthesized.
        try:
            from backend.services.arcgis_enrichment import enrich_city, is_configured as _arcgis_ok
            if _arcgis_ok():
                city_data = await enrich_city(spec.city)
                if city_data and city_data.get("households") and network.feeders:
                    target_total = city_data["households"]
                    current_total = sum(f.customer_count for f in network.feeders)
                    if current_total > 0 and target_total > 0:
                        scale = target_total / current_total
                        for f in network.feeders:
                            f.customer_count = max(1, int(round(f.customer_count * scale)))
                        self.logger.info(
                            "Scaled %d feeders to match ArcGIS city household total "
                            "(%d → %d, factor %.3f)",
                            len(network.feeders), current_total, target_total, scale,
                        )
                    network.sources.append(
                        "ArcGIS GeoEnrichment (Esri Canada): "
                        f"{city_data.get('city_name', spec.city)}: "
                        f"{target_total:,} households, "
                        f"population {city_data.get('population', 0):,}"
                    )
                    network.is_synthesized = False
        except Exception as e:
            self.logger.debug(f"ArcGIS city enrichment skipped: {e}")

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
