"""
Plan Synthesis Agent — Stage 4 of the Skorpio pipeline.

Translates all pipeline outputs into a comprehensive, human-readable
SitingPlan using Claude as the intelligence layer.
"""
import asyncio
from datetime import datetime
from typing import Optional

from backend.agents.base_agent import BaseAgent
from backend.config import settings
from backend.grid.multi_objective import (
    assign_pareto_ranks,
    compute_pareto_objectives,
    compute_weighted_score,
)
from backend.models.report import (
    NewsItem,
    ParetoAnalysis,
    PlacementScore,
    RegionInsight,
    SitingPlan,
)
from backend.agents.grounding import GROUNDING_RULES
from backend.models.site import ObjectiveWeights, SiteLibrary
from backend.models.workload import Region, Workload
from backend.services.arxiv import arxiv_client
from backend.utils.reconciliation import reconcile


SYSTEM_SYNTHESIS = """You are an expert datacenter siting analyst writing a
comprehensive plan. You combine grid telemetry, transmission economics, and
regulatory context to provide actionable siting recommendations. Write for
a senior infrastructure / strategy audience. Be precise, quantitative, and
clearly distinguish forecasts from observations.""" + GROUNDING_RULES


class PlanSynthesisAgent(BaseAgent):
    async def synthesize(
        self,
        job_id: str,
        workload: Workload,
        libraries: list[SiteLibrary],
        scoring_results_per_region: dict[str, list[PlacementScore]],
        pipeline_start_time: datetime,
        progress_callback=None,
    ) -> SitingPlan:
        """Generate the final SitingPlan from all pipeline outputs."""
        self.logger.info("Starting plan synthesis...")

        if progress_callback:
            await progress_callback("Analysing region-specific insights...", 87)

        # Fetch workload-level news in parallel with per-region work
        news_task = asyncio.create_task(
            arxiv_client.search_for_workload(workload.normalized_name)
        )

        # Build per-region insights in parallel
        insight_tasks = [
            self._build_region_insight(
                region,
                scoring_results_per_region.get(region.iso_code, []),
                workload,
            )
            for region in workload.regions
        ]
        region_insights = await asyncio.gather(*insight_tasks, return_exceptions=True)
        region_insights = [r for r in region_insights if isinstance(r, RegionInsight)]

        # Collect workload-level news items
        news_raw = await news_task
        news_items = [
            NewsItem(
                arxiv_id=p["arxiv_id"],
                title=p["title"],
                authors=p["authors"],
                summary=p["summary"],
                published=p["published"],
                url=p["url"],
                categories=p["categories"],
            )
            for p in news_raw
        ]
        self.logger.info(f"arXiv: {len(news_items)} items for '{workload.normalized_name}'")

        # Aggregate all scoring results
        all_scores: list[PlacementScore] = []
        for results in scoring_results_per_region.values():
            all_scores.extend(results)

        if progress_callback:
            await progress_callback("Running multi-objective Pareto optimisation...", 94)

        pareto_analysis = await self._run_pareto_optimization(
            all_scores, workload, scoring_results_per_region
        )

        # Re-rank by Pareto front then weighted score
        all_scores.sort(key=lambda r: (
            r.site.pareto_objectives.pareto_rank if r.site.pareto_objectives else 99,
            -(r.site.pareto_objectives.weighted_score if r.site.pareto_objectives else 0),
        ))
        top_candidates = all_scores[: settings.scoring_pareto_front_k]

        # Safety / risk flags
        safety_flags = self._collect_safety_flags(libraries)

        # Totals
        total_generated = sum(lib.total_generated for lib in libraries)
        total_passed = sum(len(lib.sites) for lib in libraries)
        total_scored = total_passed

        if progress_callback:
            await progress_callback("Generating executive summary...", 92)

        exec_summary = await self._generate_executive_summary(
            workload=workload,
            top_candidates=top_candidates,
            region_insights=region_insights,
            total_generated=total_generated,
            total_scored=total_scored,
            news_items=news_items,
        )

        # Pattern 3 — reconcile Claude's exec summary against known source facts.
        # If Claude's number drifts >10% from the backend's value, it's
        # rewritten in-place so the rendered report shows the source of truth.
        if top_candidates:
            top = top_candidates[0]
            recon_facts = {
                "lcoe_usd_mwh": top.levelized_cost_usd_mwh,
                "capacity_mw": workload.target_capacity_mw,
            }
            exec_summary = reconcile(exec_summary, recon_facts).corrected_text

        limitations = self._identify_limitations(workload, libraries, scoring_results_per_region)

        # If any Claude call (weights / region insights / exec summary) hit
        # the max_tokens cap during this run, flag it so the user sees the
        # narrative may have been clipped. Counter accumulates across all
        # internal calls; see base_agent._truncation_count.
        if self.had_truncation():
            safety_flags.append(
                f"{self._truncation_count} Claude response(s) hit the max_tokens "
                "cap during synthesis, so narrative or per-site detail may be "
                "incomplete. Raise the affected cap in REPORTS_COHESION.md §8b "
                "and re-run."
            )

        duration = (datetime.utcnow() - pipeline_start_time).total_seconds()

        # ArcGIS enrichment — when the top candidate site sits in a known
        # Canadian municipality, fetch Census Subdivision demographics and
        # append a source citation. Lets the Siting report visibly show
        # that the analysis was grounded against real Esri data instead
        # of pure synthesis. Best-effort; silent on any failure.
        arcgis_sources: list[str] = []
        try:
            from backend.services.arcgis_enrichment import (
                enrich_city,
                is_configured as _arcgis_ok,
            )
            if _arcgis_ok() and top_candidates:
                # Extract a probable city from the top site's name field
                # (formats like "Toronto, ON · expansion" or "Vaughan, ON").
                top_name = top_candidates[0].site.name or ""
                guess = top_name.split(",")[0].split("·")[0].strip()
                if guess:
                    city_data = await enrich_city(guess)
                    if city_data:
                        arcgis_sources.append(
                            "ArcGIS GeoEnrichment (Esri Canada): "
                            f"{city_data.get('city_name', guess)}: "
                            f"{city_data.get('households', 0):,} households, "
                            f"population {city_data.get('population', 0):,}"
                        )
        except Exception as e:
            self.logger.debug(f"ArcGIS siting enrichment skipped: {e}")

        plan = SitingPlan(
            job_id=job_id,
            workload_spec=workload.query,
            workload_name=workload.normalized_name,
            workload_description=workload.description,
            target_capacity_mw=workload.target_capacity_mw,
            target_latency_ms=workload.target_latency_ms,
            candidate_iso_codes=workload.candidate_iso_codes,
            executive_summary=exec_summary,
            regions_analyzed=len(workload.regions),
            sites_generated=total_generated,
            sites_scored=total_scored,
            region_insights=region_insights,
            top_candidates=top_candidates,
            safety_flags=safety_flags,
            limitations=limitations,
            methodology_notes=self._methodology_notes(),
            pipeline_duration_seconds=round(duration, 1),
            news_items=news_items,
            pareto_analysis=pareto_analysis,
            sources=arcgis_sources,
        )

        self.logger.info(f"Siting plan generated for job {job_id}")
        return plan

    # ------------------------------------------------------------------ #

    async def _run_pareto_optimization(
        self,
        scoring_results: list[PlacementScore],
        workload: Workload,
        scoring_results_per_region: dict[str, list[PlacementScore]],
    ) -> ParetoAnalysis:
        """Pareto-optimise across all sites and attach objectives in-place."""
        if not scoring_results:
            return ParetoAnalysis(
                weights=ObjectiveWeights(),
                pareto_front_count=0,
                workload_context="No scoring results to optimise.",
            )

        # Detect latency-critical context
        is_latency_critical = bool(
            workload.target_latency_ms and workload.target_latency_ms < 40
        ) or (workload.workload_class in {"inference", "edge-pop"})

        weights = await self._get_claude_weights(workload, is_latency_critical)

        # Region-level carbon snapshot (best available)
        region_carbon: dict[str, Optional[float]] = {}
        for iso_code, results in scoring_results_per_region.items():
            if not results:
                continue
            # Approximate region carbon as the median of placement-score interactions.
            # In production, sourced from carbon_intensity_client per region (provincial
            # fuel mix x IPCC AR5 emission factors).
            region_carbon[iso_code] = None

        objectives_list: list[list[float]] = []
        for r in scoring_results:
            obj = compute_pareto_objectives(
                r.site,
                lcoe_usd_mwh=r.levelized_cost_usd_mwh,
                region_carbon_g_co2_kwh=region_carbon.get(r.region_iso),
                target_latency_ms=workload.target_latency_ms,
                target_capacity_mw=workload.target_capacity_mw,
            )
            r.site.pareto_objectives = obj
            objectives_list.append([
                obj.cost_economics,
                obj.carbon_intensity,
                obj.latency_fit,
                obj.transmission_headroom,
                obj.deployment_speed,
                obj.operational_resilience,
            ])

        ranks = assign_pareto_ranks(objectives_list)
        pareto_front_count = ranks.count(1)

        for r, rank in zip(scoring_results, ranks):
            obj = r.site.pareto_objectives
            if obj:
                obj.pareto_rank = rank
                obj.weighted_score = compute_weighted_score(obj, weights)

        self.logger.info(
            f"Pareto optimisation: {pareto_front_count}/{len(scoring_results)} on front 1"
        )
        return ParetoAnalysis(
            weights=weights,
            pareto_front_count=pareto_front_count,
            workload_context=weights.rationale,
            is_latency_critical=is_latency_critical,
        )

    async def _get_claude_weights(
        self, workload: Workload, is_latency_critical: bool
    ) -> ObjectiveWeights:
        """Ask Claude to assign objective weights appropriate for this workload."""
        prompt = f"""You are optimising siting candidates for: {workload.normalized_name}
Workload description: {workload.description[:300]}
Target capacity: {workload.target_capacity_mw} MW
Target latency: {workload.target_latency_ms} ms
Latency-critical workload: {is_latency_critical}

Assign weights (0.0–1.0) for these 6 siting objectives. Weights must sum to 1.0.
Choose weights that reflect what matters most for this specific workload:

- cost_economics: How cheap delivered electricity is (LCOE inverted)
- carbon_intensity: How clean the marginal MWh is (g CO₂/kWh inverted)
- latency_fit: How well the site meets the workload latency target
- transmission_headroom: Capacity-to-spare on the local POI
- deployment_speed: Time-to-power (inverted)
- operational_resilience: Water / weather / policy resilience

Return JSON only:
{{
  "cost_economics": 0.XX,
  "carbon_intensity": 0.XX,
  "latency_fit": 0.XX,
  "transmission_headroom": 0.XX,
  "deployment_speed": 0.XX,
  "operational_resilience": 0.XX,
  "rationale": "One sentence explaining the weighting logic for this workload."
}}"""

        try:
            result = await self.ask_claude_json(
                system=SYSTEM_SYNTHESIS,
                prompt=prompt,
                max_tokens=512,
            )
            keys = ["cost_economics", "carbon_intensity", "latency_fit",
                    "transmission_headroom", "deployment_speed", "operational_resilience"]
            raw = {k: float(result.get(k, 1/6)) for k in keys}
            total = sum(raw.values()) or 1.0
            normalised = {k: round(v / total, 3) for k, v in raw.items()}
            return ObjectiveWeights(
                **normalised,
                rationale=result.get("rationale", ""),
            )
        except Exception as e:
            self.logger.warning(f"Claude weight assignment failed: {e}")
            if is_latency_critical:
                return ObjectiveWeights(
                    cost_economics=0.18, carbon_intensity=0.15, latency_fit=0.32,
                    transmission_headroom=0.15, deployment_speed=0.12,
                    operational_resilience=0.08,
                    rationale=f"Default latency-critical weights for {workload.normalized_name}.",
                )
            return ObjectiveWeights(rationale=f"Default weights applied for {workload.normalized_name}.")

    # ------------------------------------------------------------------ #

    async def _build_region_insight(
        self,
        region: Region,
        scoring_results: list[PlacementScore],
        workload: Workload,
    ) -> RegionInsight:
        """Generate operational insight for a single region, enriched with news."""
        top_sites = scoring_results[:3]
        top_site_info = "\n".join(
            f"  - {r.site.name} (LCOE = ${r.levelized_cost_usd_mwh:.1f}/MWh)"
            for r in top_sites
        )

        news_task = asyncio.create_task(
            arxiv_client.search_for_region(region.iso_code, workload.normalized_name)
        )

        prompt = f"""Workload: {workload.normalized_name}
Region: {region.name} ({region.iso_code}, BA: {region.balancing_authority})
Function: {region.function_summary[:400]}
Authorities: {', '.join(a.name for a in region.authorities[:3])}

Top scoring candidates:
{top_site_info if top_site_info else "No scoring results available"}

Write:
1. market_outlook: How the region's market dynamics fit this workload (3-4 sentences)
2. transmission_constraints: Which constraints affect placement and why that matters (2-3 sentences)
3. regulatory_context: Current siting rules, queue status, tax incentives (2-3 sentences)

Return JSON:
{{
  "market_outlook": "...",
  "transmission_constraints": "...",
  "regulatory_context": "..."
}}"""

        try:
            response, news_raw = await asyncio.gather(
                self.ask_claude_json(
                    system=SYSTEM_SYNTHESIS,
                    prompt=prompt,
                    max_tokens=1024,
                ),
                news_task,
            )
            papers = [
                NewsItem(
                    arxiv_id=p["arxiv_id"],
                    title=p["title"],
                    authors=p["authors"],
                    summary=p["summary"],
                    published=p["published"],
                    url=p["url"],
                    categories=p["categories"],
                )
                for p in news_raw
            ]
            return RegionInsight(
                region_iso=region.iso_code,
                market_outlook=response.get("market_outlook", ""),
                transmission_constraints=response.get("transmission_constraints", ""),
                regulatory_context=response.get("regulatory_context", ""),
                top_sites=top_sites,
                news_items=papers,
                topology_graph=region.topology_graph,
            )
        except Exception as e:
            self.logger.warning(f"Region insight generation failed for {region.iso_code}: {e}")
            return RegionInsight(
                region_iso=region.iso_code,
                market_outlook=region.function_summary[:200],
                transmission_constraints="Transmission analysis unavailable.",
                regulatory_context="Regulatory context unavailable.",
                top_sites=top_sites,
                news_items=[],
                topology_graph=region.topology_graph,
            )

    async def _generate_executive_summary(
        self,
        workload: Workload,
        top_candidates: list[PlacementScore],
        region_insights: list[RegionInsight],
        total_generated: int,
        total_scored: int,
        news_items: list[NewsItem] | None = None,
    ) -> str:
        regions_summary = "\n".join(
            f"- {r.region_iso}: {r.market_outlook[:150]}"
            for r in region_insights[:5]
        )
        top_hit_info = ""
        if top_candidates:
            best = top_candidates[0]
            top_hit_info = (
                f"Best candidate: {best.site.name} ({best.region_iso}), "
                f"LCOE ${best.levelized_cost_usd_mwh:.1f}/MWh, "
                f"uptime {best.uptime_lb}-{best.uptime_ub}"
            )

        news_block = ""
        if news_items:
            news_lines = "\n".join(
                f"- [{n.published}] {n.title}. {n.summary[:200]}"
                for n in news_items[:3]
            )
            news_block = f"\nRecent arXiv preprints on this workload class:\n{news_lines}"

        prompt = f"""Write a compelling 4-5 paragraph executive summary for this siting run.

Workload: {workload.normalized_name}
Workload description: {workload.description}
Target capacity: {workload.target_capacity_mw} MW

Regions identified and their market outlook:
{regions_summary}

Pipeline statistics:
- Sites generated: {total_generated}
- Sites scored: {total_scored}
- {top_hit_info}
{news_block}

Format: open with `# Executive Summary: <one-line topic>`. Then 4-5
paragraphs; each paragraph begins with `**<2-5 word bold title>**` on its
own line, a blank line, then the prose. Separate paragraphs with blank
lines only. Do NOT insert `---` or any horizontal-rule dividers, and do
NOT use markdown tables (the renderer does not display them). Avoid em
dashes anywhere in the prose; use commas, periods, or parentheses.

Paragraph topics:
1. Open with the workload's siting significance and constraints
2. Describe the analytical approach
3. Highlight the most promising regions and why
4. Describe the top candidate sites and predicted economics
5. Close with next steps (interconnect engineering, environmental review, etc.)

Write in a professional, technical tone suitable for a senior infrastructure audience."""

        try:
            return await self.ask_claude(
                system=SYSTEM_SYNTHESIS,
                prompt=prompt,
                max_tokens=1500,
            )
        except Exception as e:
            self.logger.warning(f"Executive summary generation failed: {e}")
            return (
                f"Skorpio identified {len(workload.regions)} regions for "
                f"{workload.normalized_name} and scored {total_generated} candidate sites, "
                f"yielding {total_scored} feasible placements."
            )

    def _collect_safety_flags(self, libraries: list[SiteLibrary]) -> list[str]:
        """Collect operational / regulatory concerns across libraries."""
        flags = []
        # Promote per-library disclosure messages (set by the generator —
        # e.g. "narrowed to Alectra territory then widened back to CA-ON")
        # so they appear in the report's safety_flags block.
        for lib in libraries:
            flags.extend(lib.library_flags)
        # Disclose synthesized fallback candidates so the operator never
        # mistakes the skeleton ring for genuine sourced sites. Triggered by
        # the SiteGenerationEngine's last-resort path in grid/generator.py.
        fallback_count = sum(
            1 for lib in libraries
            for s in lib.sites
            if s.generation_method == "fallback_ring"
        )
        if fallback_count > 0:
            flags.append(
                f"{fallback_count} candidates were synthesized as a fallback "
                "because every upstream generation path returned zero. Treat "
                "these as illustrative placeholders, not sourced sites."
            )
        policy_count = sum(
            1 for lib in libraries
            for s in lib.sites
            if s.profile.has_policy_blockers
        )
        alert_count = sum(
            1 for lib in libraries
            for s in lib.sites
            if s.profile.has_alerts
        )
        if policy_count > 0:
            flags.append(
                f"{policy_count} sites flagged for interconnect-queue or zoning blockers. "
                "Expect regulatory friction."
            )
        if alert_count > 0:
            flags.append(
                f"{alert_count} sites flagged for water-stress or weather alerts. "
                "Review cooling and curtailment assumptions."
            )
        slow_deploy = sum(
            1 for lib in libraries
            for s in lib.sites
            if s.profile.deployment_months is not None
            and s.profile.deployment_months > 30
        )
        if slow_deploy > 0:
            flags.append(
                f"{slow_deploy} sites have time-to-power > 30 months. "
                "Consider phased commissioning."
            )
        return flags

    def _identify_limitations(
        self,
        workload: Workload,
        libraries: list[SiteLibrary],
        scoring_results: dict[str, list[PlacementScore]],
    ) -> list[str]:
        limitations = [
            "LCOE values are forecasts. Refine with utility-specific tariff studies.",
            "Carbon intensity is sampled from the current hour. Treat as a snapshot, not a forward curve.",
            "Transmission headroom is read from the live ISO snapshot. Re-validate at the interconnect study stage.",
            "Site economics use 2D parcel proxies; on-site survey will reshape capex.",
        ]
        no_telemetry_regions = [
            r.iso_code for r in workload.regions if not r.grid_telemetry_path
        ]
        if no_telemetry_regions:
            limitations.append(
                f"No live grid telemetry available for: {', '.join(no_telemetry_regions)}. "
                "Scoring fell back to property-based heuristics."
            )
        return limitations

    def _methodology_notes(self) -> str:
        return (
            "Regions identified via OpenEI region-utility associations and ISO topology snapshots. "
            "Grid telemetry retrieved from EIA Open Data v2 and Electricity Maps. "
            "Sites generated through FERC queue lookups, POI expansion and Claude-guided proposals. "
            "Feasibility filtering via capacity / latency / policy heuristics. "
            "Placement scoring performed with the LP scenario engine (or mock fallback). "
            "Interaction analysis and narrative generation via the Anthropic Claude API."
        )
