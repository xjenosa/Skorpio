"""
Skorpio Orchestrator
Drives the 4-stage siting pipeline via Langflow custom components.
Each stage is a Langflow Component; the orchestrator sequences them,
threads progress updates to the DB, and persists the final SitingPlan.
"""
import asyncio
import uuid
from datetime import datetime
from typing import AsyncIterator

from backend.langflow_compat import Data

from backend.langflow_components import (
    GridIntelligenceComponent,
    SiteGenerationComponent,
    PlacementScoringComponent,
    PlanSynthesisComponent,
)
from backend.models.workload import Workload
from backend.models.site import SiteLibrary
from backend.models.report import SitingPlan, PlacementScore, PipelineStage
from backend.models.winter_peak import (
    ResiliencePlan,
    ScenarioOutcome,
    WinterPeakSpec,
)
from backend.agents.winter_workload import WinterWorkloadAgent
from backend.agents.winter_grid import WinterGridAgent
from backend.agents.cold_event_sim import ColdEventSimAgent
from backend.agents.feeder_risk import FeederRiskAgent
from backend.agents.winter_synthesis import WinterSynthesisAgent
from backend.services.cold_events import get_event
from backend.models.electrification import ElectrificationPlan
from backend.agents.electrification_workload import ElectrificationWorkloadAgent
from backend.agents.neighborhood_profile import NeighborhoodProfileAgent
from backend.agents.adoption_modeling import AdoptionModelingAgent
from backend.agents.readiness_scoring import ReadinessScoringAgent
from backend.agents.electrification_synthesis import ElectrificationSynthesisAgent
from backend.models.investment import InvestmentPlan
from backend.agents.investment_workload import InvestmentWorkloadAgent
from backend.agents.asset_catalog import AssetCatalogAgent
from backend.agents.climate_risk_modeling import ClimateRiskModelingAgent
from backend.agents.portfolio_optimization import PortfolioOptimizationAgent
from backend.agents.investment_synthesis import InvestmentSynthesisAgent
from backend.models.expansion import ExpansionPlan
from backend.agents.expansion_workload import ExpansionWorkloadAgent
from backend.agents.operator_footprint_agent import OperatorFootprintAgent
from backend.agents.demand_forecast import DemandForecastAgent
from backend.agents.expansion_scoring import ExpansionScoringAgent
from backend.agents.expansion_synthesis import ExpansionSynthesisAgent
from backend.db.session import AsyncSessionLocal
from backend.db import crud
from backend.utils.logger import get_logger
from backend.config import settings
from backend.analytics.snowflake_analytics import snowflake_analytics
from backend.orchestrator_control import JobCancelledError, JobControl
from backend.orchestrator_stream import stream_progress as _emit_progress_events

logger = get_logger(__name__)


# Re-export JobCancelledError so callers that historically did
# ``from backend.orchestrator import JobCancelledError`` keep working
# even though the class itself now lives in ``orchestrator_control``.
__all__ = ["JobCancelledError", "SkorpioOrchestrator", "orchestrator"]


class SkorpioOrchestrator:
    """Drives every Skorpio pipeline run end-to-end.

    State is split across two helpers:
      * ``_control``       — pause / resume / cancel flags + the
                             stage-boundary checkpoint coroutine that
                             raises ``JobCancelledError``. Lives in
                             ``orchestrator_control.py``.
      * SSE poll loop      — read-only progress streamer in
                             ``orchestrator_stream.py``; consumed by
                             ``stream_progress`` below.

    The control flags are NOT persisted across restarts — see the
    docstring on ``JobControl`` for why that's intentional.
    """

    _control: JobControl = JobControl()

    # ── Public pause / cancel API (thin pass-throughs to JobControl) ──

    @classmethod
    def pause(cls, job_id: str) -> None:
        cls._control.request_pause(job_id)

    @classmethod
    def resume(cls, job_id: str) -> None:
        cls._control.release_pause(job_id)

    @classmethod
    def is_paused(cls, job_id: str) -> bool:
        return cls._control.is_paused(job_id)

    @classmethod
    def cancel(cls, job_id: str) -> None:
        """Flag a job for cancellation. Effect lands at the next stage
        boundary inside ``_wait_if_paused``."""
        cls._control.request_cancel(job_id)

    @classmethod
    def is_cancelled(cls, job_id: str) -> bool:
        return cls._control.is_cancelled(job_id)

    @classmethod
    def clear_cancel(cls, job_id: str) -> None:
        cls._control.release_cancel(job_id)

    # ── Stage-boundary checkpoint ─────────────────────────────────────

    async def _wait_if_paused(
        self, job_id: str, db, last_pct: float = 0.0,
    ) -> None:
        """Stage-boundary checkpoint. Blocks while paused; raises
        ``JobCancelledError`` if the user clicked Stop. The 19 call
        sites in the pipeline ``run_*`` methods kept this exact name so
        the surgical refactor doesn't have to touch every stage."""
        await self._control.checkpoint(job_id, db, last_pct=last_pct)

    async def create_job(self, workload_spec: str) -> str:
        job_id = str(uuid.uuid4())
        async with AsyncSessionLocal() as db:
            await crud.create_job(db, job_id, workload_spec)
        return job_id

    async def run_pipeline(
        self,
        job_id: str,
        workload_spec: str,
        model: str | None = None,
    ) -> SitingPlan:
        """
        Execute the full 4-stage pipeline via Langflow components.
        Each component wraps its agent; progress is written to the DB
        between stages so the SSE stream stays live.

        `model`, when provided, overrides ANTHROPIC_MODEL for every agent in
        this run. Validated against the allowlist in main.py before reaching here.
        """
        start_time = datetime.utcnow()

        async with AsyncSessionLocal() as db:

            async def progress(message: str, pct: int, stage: PipelineStage = None):
                await crud.update_progress(
                    db,
                    job_id,
                    message=message,
                    progress=float(pct),
                    stage=stage.value if stage else None,
                )
                logger.info(f"[{job_id[:8]}] {pct}% — {message}")

            try:
                # ── Stage 1: Grid Intelligence ─────────────────────────── #
                await crud.update_progress(
                    db, job_id,
                    message="Ingesting grid telemetry...",
                    progress=5.0,
                    stage=PipelineStage.GRID_ANALYSIS.value,
                    started_at=start_time,
                )

                grid_comp = GridIntelligenceComponent()
                grid_comp.workload_query = workload_spec
                grid_comp.max_regions = settings.max_regions
                grid_comp.model = model
                grid_comp.progress_callback = progress
                workload_data: Data = await grid_comp.build_workload_data()
                workload = Workload.model_validate(workload_data.data)

                await progress(
                    f"Identified {len(workload.regions)} regions: "
                    + ", ".join(r.iso_code for r in workload.regions),
                    48,
                    PipelineStage.REGION_DISCOVERY,
                )

                if not workload.regions:
                    raise ValueError(
                        f"No feasible regions for '{workload_spec}'. "
                        "Try a more specific workload spec."
                    )

                await self._wait_if_paused(job_id, db, last_pct=48)

                # ── Stage 2: Site Generation ───────────────────────────── #
                await progress(
                    f"Generating sites for {len(workload.regions)} regions in parallel...",
                    50,
                    PipelineStage.SITE_GENERATION,
                )

                n_sites = settings.min_site_candidates

                async def _gen_one(region) -> tuple[str, SiteLibrary | Exception]:
                    # Agent-internal progress_callback now flows through the
                    # component (see REPORTS_COHESION.md §11), so the agent
                    # emits its own substep lines ("Fetching FERC queue...",
                    # "Applying feasibility filters...", etc.). The
                    # orchestrator only emits the "done" line so the user
                    # sees a clean completion signal per region.
                    site_comp = SiteGenerationComponent()
                    site_comp.region_data = Data(data=region.model_dump(mode="json"))
                    site_comp.workload_data = Data(data=workload.model_dump(mode="json"))
                    site_comp.n_sites = n_sites
                    site_comp.model = model
                    site_comp.progress_callback = progress
                    try:
                        lib_data: Data = await site_comp.build_site_library()
                        lib = SiteLibrary.model_validate(lib_data.data)
                        await progress(
                            f"Generated {len(lib.sites)} candidate sites for {region.iso_code}.",
                            68,
                            PipelineStage.SITE_GENERATION,
                        )
                        return region.iso_code, lib
                    except Exception as exc:
                        return region.iso_code, exc

                gen_outcomes = await asyncio.gather(
                    *(_gen_one(r) for r in workload.regions)
                )

                libraries: list[SiteLibrary] = []
                for iso_code, outcome in gen_outcomes:
                    if isinstance(outcome, Exception):
                        logger.warning(f"Site generation failed for {iso_code}: {outcome}")
                        continue
                    libraries.append(outcome)
                    logger.info(f"Library for {iso_code}: {len(outcome.sites)} sites")

                await self._wait_if_paused(job_id, db, last_pct=68)

                # ── Stage 3: Placement Scoring ─────────────────────────── #
                await progress(
                    f"Scoring {len(libraries)} region libraries in parallel...",
                    70,
                    PipelineStage.SCORING,
                )

                async def _score_one(region, library) -> tuple[str, list[PlacementScore] | Exception]:
                    # Agent-internal progress_callback now flows through the
                    # component (REPORTS_COHESION.md §11), so the agent
                    # emits per-region scoring substep lines. The orchestrator
                    # only emits the "done" line per region.
                    score_comp = PlacementScoringComponent()
                    score_comp.region_data = Data(data=region.model_dump(mode="json"))
                    score_comp.site_library = Data(data=library.model_dump(mode="json"))
                    score_comp.workload_data = Data(data=workload.model_dump(mode="json"))
                    score_comp.model = model
                    score_comp.progress_callback = progress
                    try:
                        results_data: Data = await score_comp.build_placement_scores()
                        results = [PlacementScore.model_validate(r) for r in results_data.data["results"]]
                        if results:
                            await progress(
                                f"{region.iso_code}: best LCOE ${results[0].levelized_cost_usd_mwh:.1f}/MWh.",
                                82,
                                PipelineStage.SCORING,
                            )
                        return region.iso_code, results
                    except Exception as exc:
                        return region.iso_code, exc

                score_outcomes = await asyncio.gather(
                    *(_score_one(r, lib) for r, lib in zip(workload.regions, libraries))
                )

                scoring_results: dict[str, list[PlacementScore]] = {}
                for iso_code, outcome in score_outcomes:
                    if isinstance(outcome, Exception):
                        logger.warning(f"Scoring failed for {iso_code}: {outcome}")
                        continue
                    scoring_results[iso_code] = outcome
                    if outcome:
                        logger.info(
                            f"{iso_code}: best LCOE = ${outcome[0].levelized_cost_usd_mwh:.1f}/MWh"
                        )

                # ── Snowflake: store site features ─────────────────────── #
                try:
                    sf_payload = {
                        iso: [r.model_dump(mode="json") for r in results]
                        for iso, results in scoring_results.items()
                    }
                    snowflake_analytics.store_sites(
                        job_id=job_id,
                        workload=workload.normalized_name or workload_spec,
                        scoring_results_per_region=sf_payload,
                    )
                except Exception as sf_exc:
                    logger.warning(f"Snowflake site storage skipped: {sf_exc}")

                await self._wait_if_paused(job_id, db, last_pct=85)

                # ── Stage 4: Plan Synthesis ────────────────────────────── #
                await progress("Composing siting plan...", 87, PipelineStage.PLAN_SYNTHESIS)

                plan_comp = PlanSynthesisComponent()
                plan_comp.job_id = job_id
                plan_comp.model = model
                plan_comp.progress_callback = progress
                plan_comp.workload_data = Data(data=workload.model_dump(mode="json"))
                plan_comp.libraries_data = Data(data={
                    "libraries": [lib.model_dump(mode="json") for lib in libraries]
                })
                plan_comp.scoring_data = Data(data={
                    "results_per_region": {
                        iso: [r.model_dump(mode="json") for r in results]
                        for iso, results in scoring_results.items()
                    }
                })
                plan_comp.pipeline_start_time = start_time.isoformat()
                plan_data: Data = await plan_comp.build_plan()
                plan = SitingPlan.model_validate(plan_data.data)

                # ── Snowflake: store plan for RAG search ───────────────── #
                try:
                    snowflake_analytics.store_plan(
                        job_id=job_id,
                        workload=plan.workload_name or workload_spec,
                        plan=plan.model_dump(mode="json"),
                    )
                except Exception as sf_exc:
                    logger.warning(f"Snowflake plan storage skipped: {sf_exc}")

                # ── Persist completed plan ─────────────────────────────── #
                await crud.complete_job(
                    db,
                    job_id,
                    plan.model_dump(mode="json"),
                    message="Siting plan ready",
                )

                duration = (datetime.utcnow() - start_time).total_seconds()
                logger.info(
                    f"Pipeline complete for job {job_id} in {duration:.1f}s | "
                    f"regions={len(workload.regions)}, "
                    f"candidates={sum(len(lib.sites) for lib in libraries)}"
                )
                return plan

            except Exception as e:
                logger.error(f"Pipeline failed for job {job_id}: {e}", exc_info=True)
                await crud.fail_job(db, job_id, str(e))
                raise

    async def run_winter_peak(
        self,
        job_id: str,
        query: str,
        model: str | None = None,
    ) -> ResiliencePlan:
        """
        Execute the 5-stage Winter Peak Stress Tester pipeline.

        Stages:
          1. Workload Intelligence    — query → WinterPeakSpec
          2. Grid Intelligence        — load distribution network
          3. Cold-Event Simulation    — hourly load curves per scenario
          4. Risk Scoring             — feeder + substation risk
          5. Plan Synthesis           — ResiliencePlan with mitigations
        """
        start_time = datetime.utcnow()

        async with AsyncSessionLocal() as db:

            async def progress(message: str, pct: int, stage: PipelineStage = None):
                await crud.update_progress(
                    db, job_id,
                    message=message,
                    progress=float(pct),
                    stage=stage.value if stage else None,
                )
                logger.info(f"[{job_id[:8]}] winter_peak {pct}% — {message}")

            try:
                # ── Stage 1: Workload Intelligence ─────────────────────── #
                await crud.update_progress(
                    db, job_id,
                    message="Parsing winter stress-test query...",
                    progress=2.0,
                    stage=PipelineStage.WINTER_WORKLOAD.value,
                    started_at=start_time,
                )
                workload_agent = WinterWorkloadAgent(model=model)
                spec = await workload_agent.parse_query(query, progress_callback=progress)
                await self._wait_if_paused(job_id, db, last_pct=10)

                # ── Stage 2: Grid Intelligence ─────────────────────────── #
                await progress("Loading distribution network...", 15, PipelineStage.WINTER_GRID)
                grid_agent = WinterGridAgent(model=model)
                network = await grid_agent.load_network(spec, progress_callback=progress)
                await self._wait_if_paused(job_id, db, last_pct=25)

                # Resolve cold event from spec
                cold_event = get_event(
                    spec.cold_event_id,
                    custom_min_temp_c=spec.custom_min_temp_c,
                    custom_duration_hours=spec.custom_duration_hours,
                    custom_location_label=f"{spec.city}, {spec.province}",
                )

                # ── Stage 3: Cold-Event Simulation ─────────────────────── #
                await progress("Simulating cold-event load curves...", 30, PipelineStage.COLD_EVENT_SIM)
                sim_agent = ColdEventSimAgent(model=model)
                load_profiles = await sim_agent.run_scenarios(
                    network, cold_event, spec.scenarios, progress_callback=progress,
                )
                await self._wait_if_paused(job_id, db, last_pct=60)

                # ── Stage 4: Risk Scoring ──────────────────────────────── #
                # Scenarios are independent: gather lets a 3-5 scenario sweep
                # finish in ~1 scenario's wall time instead of N×. Semaphore
                # caps concurrency at 4 so Opus-tier-1 output-TPM holds even
                # if a future spec ships with more scenarios.
                await progress(
                    f"Scoring {len(spec.scenarios)} scenarios in parallel...",
                    60,
                    PipelineStage.FEEDER_RISK,
                )
                risk_agent = FeederRiskAgent(model=model)
                scenario_sem = asyncio.Semaphore(4)

                async def _score_scenario(scenario) -> tuple:
                    async with scenario_sem:
                        feeder_risks, substation_risks = await risk_agent.score_scenario(
                            network, cold_event, scenario,
                            progress_callback=progress,
                            progress_offset_pct=70,  # static mid-band; per-scenario %s no longer ordered
                        )
                        return scenario, feeder_risks, substation_risks

                scenario_results = await asyncio.gather(
                    *(_score_scenario(s) for s in spec.scenarios)
                )

                scenario_outcomes: list[ScenarioOutcome] = [
                    ScenarioOutcome(
                        scenario=scenario,
                        load_profile=load_profiles[scenario.name],
                        feeder_risks=feeder_risks,
                        substation_risks=substation_risks,
                    )
                    for scenario, feeder_risks, substation_risks in scenario_results
                ]

                await self._wait_if_paused(job_id, db, last_pct=85)

                # ── Stage 5: Plan Synthesis ────────────────────────────── #
                await progress("Composing resilience report...", 87, PipelineStage.WINTER_SYNTHESIS)
                synth_agent = WinterSynthesisAgent(model=model)
                plan = await synth_agent.synthesize(
                    job_id=job_id,
                    spec=spec,
                    cold_event=cold_event,
                    network=network,
                    scenario_outcomes=scenario_outcomes,
                    progress_callback=progress,
                )

                # ── Persist completed plan ─────────────────────────────── #
                await crud.complete_job(
                    db,
                    job_id,
                    plan.model_dump(mode="json"),
                    message="Resilience plan ready",
                )

                duration = (datetime.utcnow() - start_time).total_seconds()
                logger.info(
                    f"Winter Peak pipeline complete for job {job_id} in {duration:.1f}s | "
                    f"city={spec.city}, scenarios={len(spec.scenarios)}, "
                    f"feeders_at_risk={sum(1 for o in scenario_outcomes for fr in o.feeder_risks if fr.overload_risk >= 0.5)}"
                )
                return plan

            except Exception as e:
                logger.error(f"Winter Peak pipeline failed for job {job_id}: {e}", exc_info=True)
                await crud.fail_job(db, job_id, str(e))
                raise

    async def run_electrification(
        self,
        job_id: str,
        query: str,
        model: str | None = None,
    ) -> ElectrificationPlan:
        """
        Execute the 5-stage Neighborhood Electrification Readiness pipeline.

        Stages:
          1. Workload Intelligence    — query → ElectrificationSpec
          2. Neighborhood Profile     — fetch StatsCan + geocoder data per FSA
          3. Adoption Modeling        — per-FSA × per-scenario load curves
          4. Readiness Scoring        — multi-dimensional readiness score per pair
          5. Plan Synthesis           — ElectrificationPlan with interventions
        """
        start_time = datetime.utcnow()

        async with AsyncSessionLocal() as db:

            async def progress(message: str, pct: int, stage: PipelineStage = None):
                await crud.update_progress(
                    db, job_id,
                    message=message,
                    progress=float(pct),
                    stage=stage.value if stage else None,
                )
                logger.info(f"[{job_id[:8]}] electrification {pct}% — {message}")

            try:
                # ── Stage 1: Workload Intelligence ─────────────────────── #
                await crud.update_progress(
                    db, job_id,
                    message="Parsing electrification readiness query...",
                    progress=2.0,
                    stage=PipelineStage.ELECTRIFICATION_WORKLOAD.value,
                    started_at=start_time,
                )
                workload_agent = ElectrificationWorkloadAgent(model=model)
                spec = await workload_agent.parse_query(query, progress_callback=progress)
                await self._wait_if_paused(job_id, db, last_pct=10)

                # ── Stage 2: Neighborhood Profile ──────────────────────── #
                await progress("Loading FSA demographic + housing data...", 15, PipelineStage.NEIGHBORHOOD_PROFILE)
                profile_agent = NeighborhoodProfileAgent(model=model)
                profiles = await profile_agent.fetch_profiles(spec, progress_callback=progress)
                if not profiles:
                    raise ValueError(
                        f"No FSAs resolved for query '{query}'. "
                        "Try naming a city or specific postal codes."
                    )
                await self._wait_if_paused(job_id, db, last_pct=28)

                # ── Stage 3: Adoption Modeling ─────────────────────────── #
                await progress("Modeling per-FSA load impact under each scenario...", 30, PipelineStage.ADOPTION_MODELING)
                model_agent = AdoptionModelingAgent(model=model)
                impacts = await model_agent.model_all(
                    profiles, spec.scenarios,
                    progress_callback=progress, progress_offset_pct=30,
                )
                await self._wait_if_paused(job_id, db, last_pct=58)

                # ── Stage 4: Readiness Scoring ─────────────────────────── #
                await progress("Scoring readiness across grid, building, affordability, policy...", 60, PipelineStage.READINESS_SCORING)
                score_agent = ReadinessScoringAgent(model=model)
                scores = await score_agent.score_all(
                    profiles, spec.scenarios, impacts,
                    progress_callback=progress, progress_offset_pct=60,
                )
                await self._wait_if_paused(job_id, db, last_pct=85)

                # ── Stage 5: Plan Synthesis ────────────────────────────── #
                await progress("Composing electrification readiness report...", 87, PipelineStage.ELECTRIFICATION_SYNTHESIS)
                synth_agent = ElectrificationSynthesisAgent(model=model)
                plan = await synth_agent.synthesize(
                    job_id=job_id,
                    spec=spec,
                    profiles=profiles,
                    scenarios=spec.scenarios,
                    impacts=impacts,
                    scores=scores,
                    progress_callback=progress,
                )

                # ── Persist completed plan ─────────────────────────────── #
                await crud.complete_job(
                    db,
                    job_id,
                    plan.model_dump(mode="json"),
                    message="Readiness plan ready",
                )

                duration = (datetime.utcnow() - start_time).total_seconds()
                logger.info(
                    f"Electrification pipeline complete for job {job_id} in {duration:.1f}s | "
                    f"city={spec.city}, fsas={len(profiles)}, scenarios={len(spec.scenarios)}, "
                    f"blocked={sum(1 for s in scores.values() if s.verdict == 'BLOCKED')}"
                )
                return plan

            except Exception as e:
                logger.error(f"Electrification pipeline failed for job {job_id}: {e}", exc_info=True)
                await crud.fail_job(db, job_id, str(e))
                raise

    async def run_investment(
        self,
        job_id: str,
        query: str,
        model: str | None = None,
    ) -> InvestmentPlan:
        """
        Execute the 5-stage Climate-Adapted Grid Investment Optimizer pipeline.

        Stages:
          1. Workload Intelligence    — query → InvestmentSpec
          2. Asset Catalog            — load utility's at-risk asset registry
          3. Climate Risk Modeling    — per-asset hazard exposure under target year
          4. Portfolio Optimization   — generate candidates + greedy ROI knapsack
          5. Plan Synthesis           — InvestmentPlan with exec summary
        """
        start_time = datetime.utcnow()

        async with AsyncSessionLocal() as db:

            async def progress(message: str, pct: int, stage: PipelineStage = None):
                await crud.update_progress(
                    db, job_id,
                    message=message,
                    progress=float(pct),
                    stage=stage.value if stage else None,
                )
                logger.info(f"[{job_id[:8]}] investment {pct}% — {message}")

            try:
                # ── Stage 1: Workload Intelligence ─────────────────────── #
                await crud.update_progress(
                    db, job_id,
                    message="Parsing climate investment query...",
                    progress=2.0,
                    stage=PipelineStage.INVESTMENT_WORKLOAD.value,
                    started_at=start_time,
                )
                workload_agent = InvestmentWorkloadAgent(model=model)
                spec = await workload_agent.parse_query(query, progress_callback=progress)
                await self._wait_if_paused(job_id, db, last_pct=10)

                # ── Stage 2: Asset Catalog ─────────────────────────────── #
                await progress("Loading utility asset catalog...", 15, PipelineStage.ASSET_CATALOG)
                catalog_agent = AssetCatalogAgent(model=model)
                assets, is_synth = await catalog_agent.load_catalog(spec, progress_callback=progress)
                if not assets:
                    raise ValueError(
                        f"No assets found for utility '{spec.utility}'. "
                        "Try naming Hydro One, Toronto Hydro, EPCOR, or Hydro-Québec."
                    )
                await self._wait_if_paused(job_id, db, last_pct=28)

                # ── Stage 3: Climate Risk Modeling ─────────────────────── #
                await progress("Modeling per-asset climate risk exposure...", 30, PipelineStage.CLIMATE_RISK_MODELING)
                risk_agent = ClimateRiskModelingAgent(model=model)
                risk_profiles = await risk_agent.assess_all(
                    spec, assets,
                    progress_callback=progress, progress_offset_pct=30,
                )
                await self._wait_if_paused(job_id, db, last_pct=55)

                # ── Stage 4: Portfolio Optimization ────────────────────── #
                await progress("Generating candidate projects + running optimizer...", 55, PipelineStage.PORTFOLIO_OPTIMIZATION)
                opt_agent = PortfolioOptimizationAgent(model=model)
                candidates, funded, unfunded = await opt_agent.build_and_select(
                    spec, assets, risk_profiles,
                    progress_callback=progress, progress_offset_pct=55,
                )
                await self._wait_if_paused(job_id, db, last_pct=85)

                # ── Stage 5: Plan Synthesis ────────────────────────────── #
                await progress("Composing investment plan...", 87, PipelineStage.INVESTMENT_SYNTHESIS)
                synth_agent = InvestmentSynthesisAgent(model=model)
                plan = await synth_agent.synthesize(
                    job_id=job_id,
                    spec=spec,
                    assets=assets,
                    is_synthesized_catalog=is_synth,
                    risk_profiles=risk_profiles,
                    candidate_projects=candidates,
                    funded=funded,
                    unfunded=unfunded,
                    progress_callback=progress,
                )

                # ── Persist completed plan ─────────────────────────────── #
                await crud.complete_job(
                    db,
                    job_id,
                    plan.model_dump(mode="json"),
                    message="Investment plan ready",
                )

                duration = (datetime.utcnow() - start_time).total_seconds()
                logger.info(
                    f"Investment pipeline complete for job {job_id} in {duration:.1f}s | "
                    f"utility={spec.utility}, assets={len(assets)}, funded={len(funded)}, "
                    f"capex=${plan.total_capex_committed_cad/1e6:.0f}M"
                )
                return plan

            except Exception as e:
                logger.error(f"Investment pipeline failed for job {job_id}: {e}", exc_info=True)
                await crud.fail_job(db, job_id, str(e))
                raise

    async def run_expansion(
        self,
        job_id: str,
        query: str,
        model: str | None = None,
    ) -> ExpansionPlan:
        """
        Execute the 5-stage Datacenter Expansion Planner pipeline.

        Stages:
          1. Workload Intelligence    — query → ExpansionSpec
          2. Operator Footprint       — load existing sites + live grid carbon
          3. Demand Forecast          — annual MW projection
          4. Expansion Scoring        — score brownfield + greenfield candidates
          5. Plan Synthesis           — phased rollout, blended carbon, exec summary
        """
        start_time = datetime.utcnow()

        async with AsyncSessionLocal() as db:

            async def progress(message: str, pct: int, stage: PipelineStage = None):
                await crud.update_progress(
                    db, job_id,
                    message=message,
                    progress=float(pct),
                    stage=stage.value if stage else None,
                )
                logger.info(f"[{job_id[:8]}] expansion {pct}% — {message}")

            try:
                # ── Stage 1: Workload Intelligence ─────────────────────── #
                await crud.update_progress(
                    db, job_id,
                    message="Parsing expansion query...",
                    progress=2.0,
                    stage=PipelineStage.EXPANSION_WORKLOAD.value,
                    started_at=start_time,
                )
                workload_agent = ExpansionWorkloadAgent(model=model)
                spec = await workload_agent.parse_query(query, progress_callback=progress)
                await self._wait_if_paused(job_id, db, last_pct=10)

                # ── Stage 2: Operator Footprint ────────────────────────── #
                await progress("Loading operator footprint...", 15, PipelineStage.OPERATOR_FOOTPRINT)
                footprint_agent = OperatorFootprintAgent(model=model)
                footprint = await footprint_agent.load(spec, progress_callback=progress)
                if not footprint.sites:
                    raise ValueError(
                        f"No existing sites found for operator '{spec.operator}'. "
                        "Try eStruxture, Cologix, Hyperion, Q-Scale, or Equinix."
                    )
                await self._wait_if_paused(job_id, db, last_pct=28)

                # ── Stage 3: Demand Forecast ───────────────────────────── #
                await progress("Forecasting demand growth...", 30, PipelineStage.DEMAND_FORECAST)
                demand_agent = DemandForecastAgent(model=model)
                demand = await demand_agent.forecast(spec, footprint, progress_callback=progress)
                await self._wait_if_paused(job_id, db, last_pct=45)

                # ── Stage 4: Expansion Scoring ─────────────────────────── #
                await progress("Generating + scoring expansion options...", 50, PipelineStage.EXPANSION_SCORING)
                scoring_agent = ExpansionScoringAgent(model=model)
                options, funded = await scoring_agent.score(
                    spec, footprint, demand,
                    progress_callback=progress, progress_offset_pct=50,
                )
                await self._wait_if_paused(job_id, db, last_pct=85)

                # ── Stage 5: Plan Synthesis ────────────────────────────── #
                await progress("Composing expansion plan...", 87, PipelineStage.EXPANSION_SYNTHESIS)
                synth_agent = ExpansionSynthesisAgent(model=model)
                plan = await synth_agent.synthesize(
                    job_id=job_id,
                    spec=spec,
                    footprint=footprint,
                    demand=demand,
                    options=options,
                    funded=funded,
                    progress_callback=progress,
                )

                # ── Persist completed plan ─────────────────────────────── #
                await crud.complete_job(
                    db,
                    job_id,
                    plan.model_dump(mode="json"),
                    message="Expansion plan ready",
                )

                duration = (datetime.utcnow() - start_time).total_seconds()
                logger.info(
                    f"Expansion pipeline complete for job {job_id} in {duration:.1f}s | "
                    f"operator={spec.operator}, sites={len(footprint.sites)}, "
                    f"funded={len(funded)}, new_mw={plan.total_new_capacity_mw:.0f}"
                )
                return plan

            except Exception as e:
                logger.error(f"Expansion pipeline failed for job {job_id}: {e}", exc_info=True)
                await crud.fail_job(db, job_id, str(e))
                raise

    async def stream_progress(self, job_id: str) -> AsyncIterator[str]:
        """SSE generator delegated to ``orchestrator_stream``. We inject
        ``self.is_paused`` so the streamer can include the paused flag
        in every payload without importing back into this module."""
        async for event in _emit_progress_events(job_id, self.is_paused):
            yield event


# Singleton orchestrator instance
orchestrator = SkorpioOrchestrator()
