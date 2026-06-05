"""
Domain models for the Datacenter Expansion Planner pipeline.

Pipeline answers: "Given <operator>'s existing footprint, how should they
add <target_mw> of capacity over <horizon_years> — brownfield expansion at
existing sites, or greenfield neighbors?"

Distinct from Datacenter Siting (#1):
  - Siting starts from nothing → finds a fresh location.
  - Expansion starts from an existing footprint → grows it, with greenfield
    only as fallback when brownfield headroom runs out.

Mirrors the other pipeline model layouts:
  ExpansionSpec       ↔ workload          (the structured user query)
  ExistingSite        ↔ Site / Substation (the per-site substrate)
  DemandForecast      ↔ ScenarioOutcome   (the modeled future need)
  ExpansionOption     ↔ PlacementScore    (the scored option)
  ExpansionPlan       ↔ SitingPlan        (the synthesized final report)
"""
from pydantic import BaseModel, Field
from typing import Optional
from backend.models.report import CitationSource


# ── Inputs ────────────────────────────────────────────────────────────── #


class ExpansionSpec(BaseModel):
    """Structured form of the user's question."""
    query: str
    normalized_name: str                                       # "eStruxture · +60 MW · 2030"
    operator: str                                              # "eStruxture", "Cologix", ...
    province: str                                              # "QC", "ON", "AB", ...
    target_additional_mw: float = 30.0                         # how much new capacity to add
    horizon_years: int = 3
    target_year: int = 2030
    workload_mix: str = "balanced"                             # "ai_training" | "ai_inference" | "traditional" | "balanced"
    prefer_brownfield: bool = True                             # bias the optimizer toward expanding existing sites
    context_summary: str = ""
    # City the user explicitly named in the prompt ("our Vaughan datacenter").
    # Populated by ExpansionWorkloadAgent when the city matches a city in any
    # operator's footprint catalog (services/operator_footprint.lookup_city).
    # Used to ground the synthesis prose and to resolve target_site_id when
    # the city → operator mapping is unambiguous.
    city: Optional[str] = None
    # When the named city maps to exactly one site in the resolved operator's
    # footprint, that site's site_id (e.g. "ESTR-TOR-1" for Vaughan). The
    # scorer adds a brownfield bonus to options whose target_site_id matches,
    # so the funded plan reflects "expand the specific campus the user named"
    # rather than recommending a different campus that scores marginally
    # higher on cost. None when the city was ambiguous or absent.
    target_site_id: Optional[str] = None
    # Free-text note describing how city → operator/site resolution played
    # out. Surfaced in the synthesis prompt and recorded as a safety_flag
    # when the resolution overrode the LLM's operator pick. Empty string
    # when no routing decision was made.
    routing_note: str = ""


# ── Existing footprint ────────────────────────────────────────────────── #


class ExistingSite(BaseModel):
    """A single operating datacenter site in the operator's footprint."""
    site_id: str                                               # "ESTR-MTL-01"
    name: str                                                  # "eStruxture MTL-1"
    operator: str
    city: str
    province: str
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    year_commissioned: int = Field(2018, ge=1900, le=2100)
    current_capacity_mw: float = Field(0.0, ge=0.0, le=10_000)
    contracted_mw: float = Field(0.0, ge=0.0, le=10_000)
    plot_acres: float = Field(5.0, ge=0.0, le=10_000)
    transformer_headroom_mw: float = Field(0.0, ge=0.0, le=10_000)
    fiber_providers: list[str] = []
    cooling: str = "air"
    water_available_l_s: float = Field(0.0, ge=0.0, le=10_000)
    grid_zone: Optional[str] = None
    avg_carbon_g_kwh: float = Field(0.0, ge=0.0, le=2000)
    pue: float = Field(1.3, ge=1.0, le=3.0)
    notes: str = ""


class OperatorFootprint(BaseModel):
    """Snapshot of an operator's Canadian footprint."""
    operator: str
    province: str                                              # primary province (most sites)
    sites: list[ExistingSite] = []
    total_current_capacity_mw: float = 0.0
    is_synthesized: bool = False                               # True when we fell back to a generic operator
    sources: list[str] = []


# ── Demand forecast ───────────────────────────────────────────────────── #


class DemandForecast(BaseModel):
    """Annual demand growth projection driving the expansion need."""
    workload_mix: str
    horizon_years: int
    annual_growth_rate: float                                  # 0.0 - 1.0
    baseline_mw: float                                         # year-0 utilization
    annual_demand_mw: list[float] = []                         # one entry per year
    target_mw_year_n: float = 0.0                              # demand at horizon
    drivers: list[str] = []                                    # plain-English drivers


# ── Expansion options ─────────────────────────────────────────────────── #


class ExpansionOption(BaseModel):
    """A discrete expansion option — brownfield phase OR greenfield neighbor."""
    option_id: str
    option_type: str                                           # "brownfield" | "greenfield"
    target_site_id: Optional[str] = None                       # set when brownfield
    title: str                                                 # "MTL-1 Phase 4 — +20 MW liquid hall"
    new_capacity_mw: float = 0.0
    capex_cad: float = 0.0
    capex_per_mw_cad: float = 0.0                              # derived for ranking
    deployment_months: int = 18
    grid_score: float = Field(ge=0.0, le=1.0, default=0.0)     # transformer + fiber headroom
    sustainability_score: float = Field(ge=0.0, le=1.0, default=0.0)  # cleaner grid + free-cooling
    speed_score: float = Field(ge=0.0, le=1.0, default=0.0)    # 1.0 = fast, 0.0 = slow
    cost_score: float = Field(ge=0.0, le=1.0, default=0.0)     # 1.0 = cheap, 0.0 = expensive
    risk_score: float = Field(ge=0.0, le=1.0, default=0.0)     # 1.0 = low risk, 0.0 = high
    overall_score: float = Field(ge=0.0, le=1.0, default=0.0)
    rank: int = 0
    rationale: str = ""
    blockers: list[str] = []
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    grid_zone: Optional[str] = None
    avg_carbon_g_kwh: float = 0.0


class PhasedRollout(BaseModel):
    """One entry per year of the horizon — which options light up when."""
    year: int
    options: list[str] = []                                    # option_ids commissioned that year
    cumulative_new_mw: float = 0.0
    cumulative_capex_cad: float = 0.0


# ── Final synthesized plan ────────────────────────────────────────────── #


class ExpansionPlan(BaseModel):
    """Final synthesized report. Mirrors the other final-plan models."""
    job_id: str
    spec: ExpansionSpec
    footprint: OperatorFootprint
    demand_forecast: DemandForecast
    options: list[ExpansionOption] = []                        # all considered, scored
    funded_options: list[ExpansionOption] = []                 # selected to meet target_mw
    phased_rollout: list[PhasedRollout] = []
    total_new_capacity_mw: float = 0.0
    total_capex_cad: float = 0.0
    blended_carbon_g_kwh: float = 0.0
    coverage_pct: float = 0.0                                  # selected MW / target MW × 100
    executive_summary: str = ""
    methodology_notes: str = ""
    safety_flags: list[str] = []
    limitations: list[str] = []
    citation_sources: dict[str, CitationSource] = {}           # inline-citation table for exec summary markers
    chart_paths: dict[str, str] = {}


# ── Pipeline progress ─────────────────────────────────────────────────── #


class ExpansionStageProgress(BaseModel):
    stage: str                                                 # "expansion_workload" | "operator_footprint" | "demand_forecast" | "expansion_scoring" | "expansion_synthesis"
    status: str
    progress_pct: float = 0.0
    message: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
