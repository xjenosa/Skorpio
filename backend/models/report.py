from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from datetime import datetime
from backend.models.site import ObjectiveWeights


class NewsItem(BaseModel):
    """A grid / energy news or preprint reference."""
    arxiv_id: str
    title: str
    authors: list[str] = []
    summary: str = ""
    published: str = ""          # YYYY-MM-DD
    url: str
    categories: list[str] = []


class PipelineStage(str, Enum):
    # Shared lifecycle states used by every pipeline.
    QUEUED = "queued"
    COMPLETED = "completed"
    FAILED = "failed"

    # Datacenter Siting pipeline stages.
    GRID_ANALYSIS = "grid_analysis"
    REGION_DISCOVERY = "region_discovery"
    SITE_GENERATION = "site_generation"
    SCORING = "scoring"
    PLAN_SYNTHESIS = "plan_synthesis"

    # Winter Peak Stress Tester stages.
    WINTER_WORKLOAD = "winter_workload"
    WINTER_GRID = "winter_grid"
    COLD_EVENT_SIM = "cold_event_sim"
    FEEDER_RISK = "feeder_risk"
    WINTER_SYNTHESIS = "winter_synthesis"

    # Neighborhood Electrification Readiness stages.
    ELECTRIFICATION_WORKLOAD = "electrification_workload"
    NEIGHBORHOOD_PROFILE = "neighborhood_profile"
    ADOPTION_MODELING = "adoption_modeling"
    READINESS_SCORING = "readiness_scoring"
    ELECTRIFICATION_SYNTHESIS = "electrification_synthesis"

    # Climate-Adapted Grid Investment Optimizer stages.
    INVESTMENT_WORKLOAD = "investment_workload"
    ASSET_CATALOG = "asset_catalog"
    CLIMATE_RISK_MODELING = "climate_risk_modeling"
    PORTFOLIO_OPTIMIZATION = "portfolio_optimization"
    INVESTMENT_SYNTHESIS = "investment_synthesis"

    # Datacenter Expansion Planner stages.
    EXPANSION_WORKLOAD = "expansion_workload"
    OPERATOR_FOOTPRINT = "operator_footprint"
    DEMAND_FORECAST = "demand_forecast"
    EXPANSION_SCORING = "expansion_scoring"
    EXPANSION_SYNTHESIS = "expansion_synthesis"


class PipelineStatus(BaseModel):
    job_id: str
    stage: PipelineStage = PipelineStage.QUEUED
    progress: int = Field(ge=0, le=100, default=0)
    message: str = ""
    started_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    error: Optional[str] = None


class GridInteraction(BaseModel):
    """
    A specific operational dependency between a site and the grid —
    the contact points that explain why the score is what it is.
    """
    facility: str                # e.g. "Keystone 500kV", "Loudoun POI"
    interaction_type: str        # "Transmission", "Water rights", "Fiber backhaul", "Substation"
    distance_km: Optional[float] = None
    latency_ms: Optional[float] = None


class PlacementScore(BaseModel):
    """
    Result of scoring one site against the workload. Negative
    `levelized_cost_usd_mwh` would not make sense; here lower is better,
    and the frontend renders it on a lower-is-better axis.
    """
    site: "Site"
    region_iso: str
    topology_id: str             # which transmission topology was used
    levelized_cost_usd_mwh: float = Field(ge=0.0, le=500.0)   # plausible $0–$500/MWh
    uptime_lb: Optional[float] = Field(None, ge=0.0, le=1.0)
    uptime_ub: Optional[float] = Field(None, ge=0.0, le=1.0)
    plan_path: Optional[str] = None          # full local path to GeoJSON / plan artifact
    plan_file: Optional[str] = None          # filename only — served via /api/transmission/{plan_file}
    topology_file: Optional[str] = None      # transmission diagram for the viewer
    scoring_method: str = "lp"               # "lp" (linear program) or "ml" (forecast model)
    interactions: list[GridInteraction] = []
    rank: int = 0
    explanation: str = ""                    # Claude-generated rationale


class RegionInsight(BaseModel):
    """Narrative for a single region."""
    region_iso: str
    market_outlook: str
    transmission_constraints: str
    regulatory_context: str
    top_sites: list["PlacementScore"] = []
    news_items: list[NewsItem] = []
    topology_graph: Optional[dict] = None


class ParetoAnalysis(BaseModel):
    """Summary of multi-objective Pareto optimisation results."""
    weights: ObjectiveWeights
    pareto_front_count: int = 0          # sites on the first Pareto front
    workload_context: str = ""           # Claude's explanation of weight choices
    is_latency_critical: bool = False    # whether latency was up-weighted in the objective vector


class SitingPlan(BaseModel):
    """The end-of-pipeline artefact returned to the frontend."""
    job_id: str
    workload_spec: str
    workload_name: str
    workload_description: str
    target_capacity_mw: float = 0.0
    target_latency_ms: Optional[float] = None
    candidate_iso_codes: list[str] = []
    executive_summary: str
    regions_analyzed: int
    sites_generated: int
    sites_scored: int
    region_insights: list[RegionInsight] = []
    top_candidates: list["PlacementScore"] = []
    safety_flags: list[str] = []
    limitations: list[str] = []
    methodology_notes: str = ""
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    pipeline_duration_seconds: Optional[float] = None
    news_items: list[NewsItem] = []          # workload-level grid / policy preprints
    pareto_analysis: Optional[ParetoAnalysis] = None
    sources: list[str] = []                  # extra dynamic citations (e.g. ArcGIS GeoEnrichment when configured)


class PipelineJob(BaseModel):
    job_id: str
    workload_spec: str
    status: PipelineStatus
    plan: Optional[SitingPlan] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# Resolve forward references
from backend.models.site import Site  # noqa: E402
PlacementScore.model_rebuild()
SitingPlan.model_rebuild()
RegionInsight.model_rebuild()
ParetoAnalysis.model_rebuild()
