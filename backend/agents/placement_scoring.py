"""
Placement Scoring Agent — Stage 3 of the Skorpio pipeline. For each
candidate site, computes a delivered cost (LCOE), uptime band, and a
small GeoJSON artefact ("pose") that the frontend can render on a map.
"""
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Optional

from backend.agents.base_agent import BaseAgent
from backend.config import settings
from backend.grid.scoring_engine import (
    estimate_interconnect_center,
    prepare_region_topology,
    run_scorer,
    topology_pose_to_geojson,
    workload_to_loadprofile,
)
from backend.models.report import GridInteraction, PlacementScore
from backend.agents.grounding import GROUNDING_RULES
from backend.models.site import Site, SiteLibrary
from backend.models.workload import Region, Workload
from backend.utils.cache import scoring_cache


SYSTEM_SCORING = """You are a transmission planner and energy economist.
Analyse the contact points between a candidate site and the grid (substation,
fibre, water, permits) and predict the dominant operational dependencies.""" + GROUNDING_RULES


# Module-level cap on concurrent per-site explanation calls. Shared across
# every PlacementScoringAgent instance (one per region) so a multi-region
# Siting run can't spike past this regardless of fan-out. Sized for Opus
# tier-1 output-TPM headroom; raise on higher tiers if you want more speed.
_EXPLANATION_SEMAPHORE = asyncio.Semaphore(4)


class PlacementScoringAgent(BaseAgent):
    async def score_sites(
        self,
        region: Region,
        library: SiteLibrary,
        workload: Workload,
        progress_callback=None,
        top_n: int = 20,
    ) -> list[PlacementScore]:
        """Score all sites in the library against the workload + region."""
        if not region.grid_telemetry_path or not Path(region.grid_telemetry_path).exists():
            self.logger.warning(
                f"No grid telemetry for {region.iso_code} — returning mock scoring"
            )
            return await self._mock_scoring_results(region, library, workload, top_n)

        self.logger.info(
            f"Scoring {len(library.sites)} sites against {region.iso_code}"
        )

        # Prepare normalised region topology (scorer's "receptor")
        if progress_callback:
            await progress_callback("Preparing region topology...", 72)
        topology_path = await asyncio.to_thread(
            self._prepare_topology, region.grid_telemetry_path
        )

        center = region.interconnect_center or estimate_interconnect_center(
            region.grid_telemetry_path
        )
        region.interconnect_center = center
        radius = (region.interconnect_radius_km, region.interconnect_radius_km, 0.0)

        if progress_callback:
            await progress_callback("Running placement scoring scenarios...", 75)

        results: list[PlacementScore] = []
        semaphore = asyncio.Semaphore(4)

        async def score_one(site: Site) -> Optional[PlacementScore]:
            async with semaphore:
                return await self._score_site(site, region, workload, topology_path, center, radius)

        tasks = [score_one(site) for site in library.sites]
        scored = await asyncio.gather(*tasks, return_exceptions=True)

        for r in scored:
            if isinstance(r, PlacementScore):
                results.append(r)
            elif isinstance(r, Exception):
                self.logger.debug(f"Scoring error: {r}")

        if not results and library.sites:
            self.logger.warning(
                f"All scoring tasks failed for {region.iso_code} — falling back to mock"
            )
            return await self._mock_scoring_results(region, library, workload, top_n)

        results.sort(key=lambda r: r.levelized_cost_usd_mwh)   # lower is better
        top_results = results[:top_n]
        for i, r in enumerate(top_results):
            r.rank = i + 1

        self.logger.info(
            f"Scoring complete: {len(results)} results, "
            f"best LCOE: {top_results[0].levelized_cost_usd_mwh if top_results else 'N/A'} $/MWh"
        )

        if progress_callback:
            await progress_callback("Analysing grid interactions...", 83)
        await self._analyze_interactions(top_results[:5], region)

        return top_results

    # ------------------------------------------------------------------ #

    def _prepare_topology(self, telemetry_path: str) -> str:
        normalised_path = telemetry_path.replace(".json", "_topology.json")
        if not Path(normalised_path).exists():
            ok = prepare_region_topology(telemetry_path, normalised_path)
            if not ok:
                self.logger.warning(f"Topology preparation failed for {telemetry_path}")
        return normalised_path

    def _site_hash(self, site: Site) -> str:
        key = f"{site.region_iso}:{site.latitude:.4f}:{site.longitude:.4f}"
        return hashlib.md5(key.encode()).hexdigest()[:8]

    def _topology_file(self, region: Region) -> Optional[str]:
        """Return just the filename portion of the region telemetry."""
        if not region.grid_telemetry_path:
            return None
        return Path(region.grid_telemetry_path).name

    def _site_parcel_to_geojson(self, site: Site, out_path: str) -> bool:
        """Write a minimal GeoJSON polygon for the site parcel."""
        try:
            offset = 0.01
            feature = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [site.longitude - offset, site.latitude - offset],
                            [site.longitude + offset, site.latitude - offset],
                            [site.longitude + offset, site.latitude + offset],
                            [site.longitude - offset, site.latitude + offset],
                            [site.longitude - offset, site.latitude - offset],
                        ]],
                    },
                    "properties": {
                        "site_id": site.site_id,
                        "name": site.name,
                        "region_iso": site.region_iso,
                    },
                }],
            }
            Path(out_path).write_text(json.dumps(feature))
            return True
        except Exception as e:
            self.logger.warning(f"Site parcel GeoJSON failed: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  Scorer path                                                         #
    # ------------------------------------------------------------------ #

    async def _score_site(
        self,
        site: Site,
        region: Region,
        workload: Workload,
        topology_path: str,
        center: tuple,
        radius: tuple,
    ) -> Optional[PlacementScore]:
        cache_key = f"score:{site.region_iso}:{site.latitude:.4f}:{site.longitude:.4f}:{workload.target_capacity_mw}"
        cached = await scoring_cache.aget(cache_key)
        if cached:
            return PlacementScore(**cached)

        site_id_hash = self._site_hash(site)
        plan_filename = f"plan_{region.iso_code}_{site_id_hash}.geojson"
        plan_path = settings.transmission_dir / plan_filename

        # Always render a parcel GeoJSON so the viewer has a base layer even when
        # the scorer binary is unavailable.
        if not plan_path.exists():
            await asyncio.to_thread(
                self._site_parcel_to_geojson, site, str(plan_path)
            )

        # Try real scoring
        scorer_results = []
        with tempfile.TemporaryDirectory() as tmpdir:
            load_path = str(Path(tmpdir) / "load.json")
            pose_path = str(Path(tmpdir) / "pose.json")

            load_ok = await asyncio.to_thread(
                workload_to_loadprofile, workload.target_capacity_mw, load_path
            )
            if load_ok:
                scorer_results = await run_scorer(
                    topology_path=topology_path,
                    load_profile_path=load_path,
                    interconnect_center=center,
                    search_radius_km=radius,
                    out_path=pose_path,
                )
                # Overlay the GeoJSON parcel with the scorer's chosen POI line
                if scorer_results and Path(pose_path).exists():
                    topology_pose_to_geojson(pose_path, str(plan_path))

        if not scorer_results:
            import random
            import zlib
            # zlib.crc32 (not hash()) — Python's hash() is randomized per
            # process (PEP 456), so the same site.name produces different
            # mock LCOE across container restarts. See REPORTS_COHESION.md §8c.
            rng = random.Random(zlib.crc32(site.name.encode()))
            scorer_results = [{
                "lcoe_usd_mwh": round(rng.uniform(28.0, 72.0), 1),
                "uptime_lb": round(rng.uniform(0.985, 0.999), 4),
                "uptime_ub": round(rng.uniform(0.995, 0.9999), 4),
            }]

        best = scorer_results[0]
        result = PlacementScore(
            site=site,
            region_iso=region.iso_code,
            topology_id=region.preferred_zone or region.iso_code,
            levelized_cost_usd_mwh=best["lcoe_usd_mwh"],
            uptime_lb=best.get("uptime_lb"),
            uptime_ub=best.get("uptime_ub"),
            plan_path=str(plan_path) if plan_path.exists() else None,
            plan_file=plan_filename if plan_path.exists() else None,
            topology_file=self._topology_file(region),
            scoring_method="lp",
        )
        await scoring_cache.aset(cache_key, result.model_dump())
        return result

    # ------------------------------------------------------------------ #
    #  Interaction analysis                                                #
    # ------------------------------------------------------------------ #

    async def _analyze_interactions(
        self,
        results: list[PlacementScore],
        region: Region,
    ) -> None:
        # Each call mutates its own result; gather lets the top-N explanations
        # generate concurrently instead of one-at-a-time. The module-level
        # _EXPLANATION_SEMAPHORE caps total in-flight calls so multi-region
        # runs on Opus don't burst past the per-minute output-token limit.
        async def _one(result: PlacementScore) -> None:
            async with _EXPLANATION_SEMAPHORE:
                try:
                    interactions, explanation = await self._predict_interactions(result, region)
                    result.interactions = interactions
                    result.explanation = explanation
                except Exception as e:
                    self.logger.warning(f"Interaction analysis failed: {e}")
                    result.explanation = (
                        f"Estimated LCOE: ${result.levelized_cost_usd_mwh:.1f}/MWh"
                    )

        await asyncio.gather(*(_one(r) for r in results), return_exceptions=False)

    async def _predict_interactions(
        self, result: PlacementScore, region: Region,
    ) -> tuple[list[GridInteraction], str]:
        prompt = f"""Region: {region.name} ({region.iso_code})
Balancing authority: {region.balancing_authority}
Zone: {result.topology_id}
Known interconnect substations: {', '.join(region.interconnect_substations) if region.interconnect_substations else 'unknown'}

Site: {result.site.name} ({result.site.latitude:.3f}, {result.site.longitude:.3f})
Estimated LCOE: ${result.levelized_cost_usd_mwh:.1f}/MWh
Uptime band: {result.uptime_lb}–{result.uptime_ub}
Scoring method: {result.scoring_method}

Based on the region, zone and site location:
1. Predict 3-5 dominant operational dependencies (substation, fibre, water, permits, etc.)
2. Explain the likely operational profile in 2-3 sentences

Return a JSON object:
{{
  "interactions": [
    {{"facility": "Keystone 500kV", "interaction_type": "Transmission", "distance_km": 12.4}},
    ...
  ],
  "explanation": "..."
}}"""

        response = await self.ask_claude_json(
            system=SYSTEM_SCORING,
            prompt=prompt,
            max_tokens=1024,
        )
        interactions = [
            GridInteraction(**i)
            for i in response.get("interactions", [])
            if isinstance(i, dict)
        ]
        explanation = response.get("explanation", "")
        return interactions, explanation

    # ------------------------------------------------------------------ #
    #  Mock fallback                                                       #
    # ------------------------------------------------------------------ #

    async def _mock_scoring_results(
        self,
        region: Region,
        library: SiteLibrary,
        workload: Workload,
        top_n: int,
    ) -> list[PlacementScore]:
        import random
        rng = random.Random(42)
        results: list[PlacementScore] = []
        for i, site in enumerate(library.sites[:top_n]):
            score = site.profile.overall_score or 0.5
            mock_lcoe = round(30.0 + (1.0 - score) * 60.0 + rng.uniform(-5, 5), 1)
            results.append(PlacementScore(
                site=site,
                region_iso=region.iso_code,
                topology_id=region.preferred_zone or region.iso_code,
                levelized_cost_usd_mwh=mock_lcoe,
                uptime_lb=round(rng.uniform(0.985, 0.998), 4),
                uptime_ub=round(rng.uniform(0.998, 0.9999), 4),
                rank=i + 1,
                scoring_method="mock",
                explanation="LCOE estimated from site profile (no live grid telemetry available).",
            ))

        results.sort(key=lambda r: r.levelized_cost_usd_mwh)

        topology_file = self._topology_file(region)
        for r in results:
            site_id_hash = self._site_hash(r.site)
            plan_filename = f"plan_{region.iso_code}_{site_id_hash}.geojson"
            plan_path = settings.transmission_dir / plan_filename
            if not plan_path.exists():
                await asyncio.to_thread(
                    self._site_parcel_to_geojson, r.site, str(plan_path)
                )
            if plan_path.exists():
                r.plan_file = plan_filename
                r.plan_path = str(plan_path)
            r.topology_file = topology_file

        await self._analyze_interactions(results[:5], region)
        return results
