"""
Domain models for the Neighborhood Electrification Readiness pipeline.

Pipeline answers: "Can these FSAs / this city handle <X%> heat pump conversion
plus <Y%> EV adoption by <year> without breaking the local distribution grid?"

Mirrors the Winter Peak / Datacenter Siting model layout:
  ElectrificationSpec ↔ WinterPeakSpec / Workload   (the structured user query)
  NeighborhoodProfile ↔ Substation / Region          (the per-area substrate)
  AdoptionScenario    ↔ ScenarioPreset               (the modeled future)
  ReadinessScore      ↔ FeederRisk / PlacementScore  (the ranked output)
  ElectrificationPlan ↔ ResiliencePlan / SitingPlan  (the synthesized report)
"""
from pydantic import BaseModel, Field
from typing import Optional
from backend.models.report import CitationSource


# ── Inputs ────────────────────────────────────────────────────────────── #


class AdoptionScenario(BaseModel):
    """A named electrification adoption target."""
    name: str                                    # "Conservative" | "Moderate" | "Aggressive"
    label: str                                   # "2030 plans (40% HP, 30% EV)"
    heat_pump_conversion_pct: float = Field(ge=0.0, le=1.0)
    ev_adoption_pct: float = Field(ge=0.0, le=1.0)
    target_year: int = 2030
    description: str = ""


class ElectrificationSpec(BaseModel):
    """Structured form of the user's question."""
    query: str
    normalized_name: str                         # "Toronto downtown · 2030 Aggressive"
    city: str                                    # "Toronto", "Mississauga", "Ottawa", ...
    province: str                                # "ON", "AB", "QC"
    fsas: list[str] = []                         # ["M5V", "M5A", "M4Y"]; empty = whole-city sample
    scope: str = "heating_and_ev"                # "heating_only" | "ev_only" | "heating_and_ev"
    scenarios: list[AdoptionScenario] = []       # default: 3 presets
    horizon_year: int = 2030
    context_summary: str = ""


# ── Neighborhood data ──────────────────────────────────────────────────── #


class DwellingMix(BaseModel):
    """Housing type breakdown for an FSA."""
    single_detached: float = 0.0
    semi_detached: float = 0.0
    row: float = 0.0
    apartment_low_rise: float = 0.0              # < 5 storeys
    apartment_high_rise: float = 0.0             # ≥ 5 storeys
    other: float = 0.0


class HeatingMix(BaseModel):
    """Primary heating fuel breakdown."""
    natural_gas: float = 0.0
    electric_baseboard: float = 0.0
    electric_forced_air: float = 0.0
    heat_pump: float = 0.0
    oil: float = 0.0
    wood: float = 0.0
    other: float = 0.0


class NeighborhoodProfile(BaseModel):
    """Demographic + housing snapshot for one FSA. From StatsCan + ECCC."""
    fsa: str                                     # "M5V"
    label: str                                   # "Toronto · King West / Liberty Village"
    city: str
    province: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    households: int = 0
    median_household_income_cad: float = 0.0
    avg_household_size: float = 2.4
    dwelling_mix: DwellingMix = DwellingMix()
    heating_mix: HeatingMix = HeatingMix()
    vehicles_per_household: float = 1.2
    avg_dwelling_age_years: float = 35.0
    heating_degree_days_18c: float = 4000.0      # from ECCC normals
    sources: list[str] = []                      # ["StatsCan Census 2021", "ECCC normals 1981-2010"]
    is_synthesized: bool = False                 # True when data was synthesized from province averages


# ── Adoption modeling ──────────────────────────────────────────────────── #


class LoadImpactPoint(BaseModel):
    """One hour of the projected new electric load curve for a neighborhood."""
    hour: int                                    # 0..23 (winter peak day)
    base_load_kw_per_household: float            # existing electric load
    new_heat_pump_kw_per_household: float        # added by HP conversion
    new_ev_kw_per_household: float               # added by EV charging
    total_kw_per_household: float


class NeighborhoodLoadImpact(BaseModel):
    """Per-FSA, per-scenario load projection."""
    fsa: str
    scenario_name: str
    hours: list[LoadImpactPoint] = []
    peak_kw_per_household: float = 0.0
    peak_hour: int = 0
    incremental_peak_mw: float = 0.0             # NEW load added across the FSA
    transformer_overload_count: int = 0          # FSA-level transformers projected to overload
    panel_upgrade_household_pct: float = 0.0     # % of homes needing >100A service


# ── Readiness scoring ──────────────────────────────────────────────────── #


class ReadinessScore(BaseModel):
    """Multi-dimensional electrification readiness for one FSA under one scenario."""
    fsa: str
    scenario_name: str
    grid_score: float = Field(ge=0.0, le=1.0)            # transformer/feeder headroom
    building_score: float = Field(ge=0.0, le=1.0)        # panel capacity, dwelling suitability
    affordability_score: float = Field(ge=0.0, le=1.0)   # income vs upgrade cost
    policy_score: float = Field(ge=0.0, le=1.0)          # rebates, code support
    overall_score: float = Field(ge=0.0, le=1.0)
    verdict: str = ""                                    # "READY" | "CONSTRAINED" | "BLOCKED"
    rank: int = 0
    blockers: list[str] = []                             # plain-English failure list
    rationale: str = ""


# ── Interventions & final report ──────────────────────────────────────── #


class Intervention(BaseModel):
    """A recommended unblocker."""
    intervention_id: str
    title: str                                   # "Bulk panel upgrade rebate program"
    category: str                                # "panel_upgrade" | "transformer_upgrade" | "rebate_program" | "code_change" | "managed_charging"
    targeted_fsas: list[str] = []
    households_unlocked: int = 0
    estimated_cost_cad: Optional[float] = None
    deployment_months: Optional[int] = None
    readiness_lift_pct: float = 0.0              # percentage points on overall readiness
    rationale: str = ""


class FSAOutcome(BaseModel):
    """Per-FSA, per-scenario combined result."""
    profile: NeighborhoodProfile
    scenario: AdoptionScenario
    load_impact: NeighborhoodLoadImpact
    readiness: ReadinessScore


class ElectrificationPlan(BaseModel):
    """Final synthesized report. Mirrors ResiliencePlan / SitingPlan."""
    job_id: str
    spec: ElectrificationSpec
    neighborhoods: list[NeighborhoodProfile] = []
    fsa_outcomes: list[FSAOutcome] = []          # one per (fsa × scenario)
    interventions: list[Intervention] = []
    executive_summary: str = ""
    methodology_notes: str = ""
    safety_flags: list[str] = []
    limitations: list[str] = []
    citation_sources: dict[str, CitationSource] = {}   # inline-citation table for exec summary markers
    chart_paths: dict[str, str] = {}


# ── Pipeline progress ─────────────────────────────────────────────────── #


class ElectrificationStage(BaseModel):
    stage: str                                   # "electrification_workload" | "neighborhood_profile" | "adoption_modeling" | "readiness_scoring" | "electrification_synthesis"
    status: str                                  # "pending" | "running" | "complete" | "error"
    progress_pct: float = 0.0
    message: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
