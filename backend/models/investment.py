"""
Domain models for the Climate-Adapted Grid Investment Optimizer pipeline.

Pipeline answers: "Given $<budget> over <N> years, which grid hardening
projects should <utility> fund to maximize climate resilience?"

Mirrors the other pipeline model layouts:
  InvestmentSpec     ↔ workload          (the structured user query)
  GridAsset          ↔ Site / Substation (the per-asset substrate)
  ClimateRiskProfile ↔ ScenarioOutcome   (the modeled future risk)
  UpgradeProject     ↔ Mitigation        (the discrete fundable unit)
  InvestmentPlan     ↔ ResiliencePlan    (the synthesized final report)
"""
from pydantic import BaseModel, Field
from typing import Optional


# ── Inputs ────────────────────────────────────────────────────────────── #


class InvestmentSpec(BaseModel):
    """Structured form of the user's question."""
    query: str
    normalized_name: str                                       # "Hydro One · $500M · 2030"
    utility: str                                               # "Hydro One", "Toronto Hydro", "EPCOR"
    province: str                                              # "ON", "AB", "QC"
    budget_cad: float = Field(500_000_000, ge=0.0, le=100_000_000_000)
    horizon_years: int = Field(5, ge=1, le=30)
    target_year: int = Field(2030, ge=2020, le=2100)
    priority_hazards: list[str] = []                           # ["ice_storm", "heat_wave", ...]
    context_summary: str = ""


# ── Grid assets at risk ────────────────────────────────────────────────── #


class GridAsset(BaseModel):
    """A single grid asset eligible for hardening investment."""
    asset_id: str                                              # "HONE-TX-014"
    name: str                                                  # "Bowmanville TS"
    asset_type: str                                            # "transmission_line" | "substation" | "feeder" | "transformer"
    utility: str
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    age_years: int = Field(25, ge=0, le=120)
    replacement_cost_cad: float = Field(0.0, ge=0.0, le=10_000_000_000)
    customers_served: int = Field(0, ge=0, le=10_000_000)
    criticality: str = "standard"                              # "critical" | "high" | "standard"
    notes: str = ""


# ── Climate risk modeling ──────────────────────────────────────────────── #


class HazardExposure(BaseModel):
    """Probability + impact of one hazard category against one asset."""
    hazard: str                                                # "ice_storm" | "heat_wave" | "wildfire" | "flood" | "wind"
    annual_probability: float = Field(ge=0.0, le=1.0)
    expected_loss_cad: float = 0.0                             # repair + outage cost per event
    customer_hours_lost: float = 0.0                           # CHOL per event (reliability metric)
    rationale: str = ""


class ClimateRiskProfile(BaseModel):
    """Per-asset climate risk under the target year + scenario."""
    asset_id: str
    target_year: int
    hazard_exposures: list[HazardExposure] = []
    aggregate_annual_loss_cad: float = 0.0                     # sum across hazards
    risk_tier: str = "low"                                     # "critical" | "high" | "medium" | "low"
    rank: int = 0


# ── Upgrade projects (the fundable units) ────────────────────────────── #


class UpgradeProject(BaseModel):
    """A discrete hardening project that can be funded."""
    project_id: str
    title: str                                                 # "Reconductor 230kV Bowmanville–Oshawa"
    category: str                                              # "reconductoring" | "undergrounding" | "transformer_upgrade" | "vegetation_mgmt" | "battery_storage" | "switchgear"
    target_assets: list[str] = []                              # asset_ids
    capex_cad: float = Field(0.0, ge=0.0, le=10_000_000_000)
    annual_opex_cad: float = Field(0.0, ge=0.0, le=1_000_000_000)
    risk_reduction_cad_per_year: float = Field(0.0, ge=0.0, le=10_000_000_000)
    customers_protected: int = Field(0, ge=0, le=10_000_000)
    deployment_months: int = Field(12, ge=0, le=240)
    hazards_addressed: list[str] = []
    rationale: str = ""


class FundedProject(BaseModel):
    """An UpgradeProject selected by the optimizer."""
    project: UpgradeProject
    cumulative_capex_cad: float = 0.0                          # running total at this rank
    roi_ratio: float = 0.0                                     # avoided loss / capex (over horizon)
    rank: int = 0                                              # 1 = highest ROI funded


# ── Final synthesized plan ────────────────────────────────────────────── #


class InvestmentPlan(BaseModel):
    """Final synthesized report. Mirrors ResiliencePlan / SitingPlan."""
    job_id: str
    spec: InvestmentSpec
    assets: list[GridAsset] = []
    risk_profiles: list[ClimateRiskProfile] = []
    candidate_projects: list[UpgradeProject] = []              # full menu before optimization
    funded_projects: list[FundedProject] = []                  # ones that made the budget
    unfunded_projects: list[UpgradeProject] = []               # didn't fit; surfaced for "next budget"
    total_capex_committed_cad: float = 0.0
    total_annual_loss_avoided_cad: float = 0.0
    portfolio_roi_ratio: float = 0.0                           # avoided-loss-over-horizon / capex
    customers_protected: int = 0
    executive_summary: str = ""
    methodology_notes: str = ""
    safety_flags: list[str] = []
    limitations: list[str] = []
    chart_paths: dict[str, str] = {}


# ── Pipeline progress ─────────────────────────────────────────────────── #


class InvestmentStage(BaseModel):
    stage: str                                                 # "investment_workload" | "asset_catalog" | "climate_risk_modeling" | "portfolio_optimization" | "investment_synthesis"
    status: str
    progress_pct: float = 0.0
    message: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
