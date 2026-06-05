"""
Domain models for the Winter Peak Stress Tester pipeline.

The pipeline answers: "Will <city>'s grid hold up during a <cold event>
once <X%> of homes have heat pumps and <Y%> of vehicles are EVs?"

Five model layers:
  WinterPeakSpec      — the structured user query
  DistributionNetwork — the operational substrate (substations + feeders)
  HourlyLoadProfile   — the simulated load curve under one scenario
  FeederRisk          — the ranked per-asset risk output
  ResiliencePlan      — the synthesized executive report
"""
from pydantic import BaseModel, Field
from typing import Optional
from backend.models.report import CitationSource


# ── Inputs ────────────────────────────────────────────────────────────── #


class ScenarioPreset(BaseModel):
    """A named electrification adoption scenario."""
    name: str                                    # "Conservative" | "Moderate" | "Aggressive"
    label: str                                   # "Today (5% HP, 7% EV)"
    heat_pump_adoption_pct: float = Field(ge=0.0, le=1.0)
    ev_adoption_pct: float = Field(ge=0.0, le=1.0)
    description: str = ""


class WinterPeakSpec(BaseModel):
    """
    Structured form of the user's question.
    """
    query: str                                   # raw user input
    normalized_name: str                         # e.g. "Mississauga · 2014 Polar Vortex · Moderate"
    city: str                                    # "Mississauga", "Toronto", etc.
    utility: Optional[str] = None                # "Alectra", "Toronto Hydro", inferred from city
    province: str                                # "ON", "AB", "QC"
    iso_zone: Optional[str] = None               # "IESO-Toronto", "AESO-South", "HQ-Montreal"
    cold_event_id: str                           # see services.cold_events._REGISTRY for the full set
    custom_min_temp_c: Optional[float] = None    # set when cold_event_id == "custom"
    custom_duration_hours: Optional[int] = None  # set when cold_event_id == "custom"
    scenarios: list[ScenarioPreset] = []         # which scenarios to run (default: all 3 presets)
    horizon_year: int = 2030                     # context for adoption forecasting
    context_summary: str = ""                    # Claude-generated overview of the test


# ── Climate event ──────────────────────────────────────────────────────── #


class HourlyTemperature(BaseModel):
    """One hour of the cold event timeline."""
    hour_offset: int                             # 0..N from event start
    temp_c: float
    wind_speed_kmh: float = 0.0
    is_peak_hour: bool = False                   # marked True for the coldest stretch


class ColdEvent(BaseModel):
    """
    A reference cold event. Either a real historical event (loaded from
    services.cold_events) or a user-defined custom one.
    """
    event_id: str                                # "polar_vortex_2014"
    name: str                                    # "January 2014 Polar Vortex"
    region: str                                  # "Eastern Canada / US Midwest"
    start_date: Optional[str] = None             # ISO date for historical events
    duration_hours: int                          # total span
    min_temp_c: float                            # coldest reading
    avg_temp_c: float                            # event-mean
    hourly_curve: list[HourlyTemperature] = []   # full hourly timeline
    description: str = ""
    sources: list[str] = []                      # ECCC station IDs, IESO post-mortems, etc.


# ── Distribution network ──────────────────────────────────────────────── #


class Substation(BaseModel):
    """A single substation in the modeled distribution network."""
    substation_id: str                           # "MSS-N-01"
    name: str                                    # "Mississauga North TS"
    latitude: float
    longitude: float
    voltage_kv: float                            # primary voltage (e.g. 230, 115, 27.6)
    nameplate_mva: float                         # rated capacity
    summer_peak_mw: float                        # historical hot-day peak
    winter_peak_mw: float                        # historical cold-day peak
    feeders: list[str] = []                      # feeder_ids served


class Feeder(BaseModel):
    """A residential / commercial distribution feeder."""
    feeder_id: str                               # "MSS-N-01-F03"
    name: str                                    # "Streetsville Hub F3"
    parent_substation_id: str
    voltage_kv: float = 27.6                     # typical Ontario primary
    rated_capacity_mva: float
    customer_count: int                          # premises served
    dwelling_mix: dict[str, float] = {}          # {"single_detached": 0.62, "semi": 0.18, ...}
    primary_heating_mix: dict[str, float] = {}   # {"gas": 0.55, "heat_pump": 0.05, "baseboard": 0.30, ...}
    ev_penetration_pct: float = 0.0              # current EV ownership share
    age_years: int = 25                          # asset age (drives failure probability)
    has_recent_upgrade: bool = False


class DistributionNetwork(BaseModel):
    """
    A modeled distribution network for one city/utility — the
    operational substrate the simulation runs against.
    """
    city: str
    utility: str
    province: str
    substations: list[Substation] = []
    feeders: list[Feeder] = []
    baseline_winter_peak_mw: float = 0.0         # network-wide historical winter peak
    baseline_year: int = 2024
    sources: list[str] = []                      # IESO market reports, utility annual reports, etc.
    is_synthesized: bool = True                  # mark False only when from real utility data


# ── Simulation outputs ────────────────────────────────────────────────── #


class HourlyLoadPoint(BaseModel):
    """One hour of the simulated load curve."""
    hour_offset: int
    temp_c: float
    base_load_mw: float                          # baseline (non-electrified) load
    heat_pump_load_mw: float                     # HP draw at this temp (COP-adjusted)
    backup_resistance_mw: float                  # auxiliary resistance heat
    baseboard_load_mw: float                     # legacy baseboard spike
    ev_load_mw: float                            # EV cold-draw + preconditioning
    other_load_mw: float                         # lighting, appliances, etc.
    total_load_mw: float                         # sum of the above


class HourlyLoadProfile(BaseModel):
    """Simulated load curve for one network under one scenario."""
    scenario_name: str                           # "Moderate"
    cold_event_id: str
    hours: list[HourlyLoadPoint] = []
    peak_load_mw: float = 0.0
    peak_hour_offset: int = 0
    peak_temp_c: float = 0.0
    headroom_at_peak_mw: float = 0.0             # negative = overload
    headroom_pct_at_peak: float = 0.0


# ── Risk scoring ──────────────────────────────────────────────────────── #


class FeederRisk(BaseModel):
    """Per-feeder risk under the simulated event."""
    feeder_id: str
    feeder_name: str
    parent_substation_id: str
    scenario_name: str
    overload_risk: float = Field(ge=0.0, le=1.0)         # 0=safe, 1=certain overload
    voltage_sag_risk: float = Field(ge=0.0, le=1.0)
    time_to_failure_hours: Optional[float] = None        # None = no failure expected
    peak_load_mva: float = 0.0
    capacity_utilization_pct: float = 0.0                # 100 = at nameplate, >100 = over
    failure_mode: str = ""                               # "thermal_overload" | "voltage_collapse" | "none"
    rationale: str = ""                                  # Claude-generated explanation
    rank: int = 0                                        # 1 = highest risk


class SubstationRisk(BaseModel):
    """Per-substation aggregate risk."""
    substation_id: str
    substation_name: str
    scenario_name: str
    aggregate_risk: float = Field(ge=0.0, le=1.0)
    peak_load_mva: float = 0.0
    peak_utilization_pct: float = 0.0
    at_risk_feeder_count: int = 0
    rationale: str = ""


# ── Mitigations & final report ────────────────────────────────────────── #


class Mitigation(BaseModel):
    """A recommended mitigation option."""
    mitigation_id: str
    title: str                                   # "Demand response on top 5 feeders"
    category: str                                # "demand_response" | "transformer_upgrade" | "feeder_reconductor" | "load_shift"
    targeted_feeders: list[str] = []
    estimated_load_relief_mw: float = 0.0
    estimated_cost_cad: Optional[float] = None
    deployment_months: Optional[int] = None
    risk_reduction_pct: float = 0.0              # how much aggregate risk it removes
    rationale: str = ""


class ScenarioOutcome(BaseModel):
    """End-to-end result for one scenario."""
    scenario: ScenarioPreset
    load_profile: HourlyLoadProfile
    feeder_risks: list[FeederRisk] = []
    substation_risks: list[SubstationRisk] = []
    summary_verdict: str = ""                    # "PASS" | "MARGINAL" | "FAIL"
    headline: str = ""                           # one-line verdict
    notable_failures: list[str] = []             # plain-language problem list


class ResiliencePlan(BaseModel):
    """
    Final synthesized report returned to the frontend.
    """
    job_id: str
    spec: WinterPeakSpec
    cold_event: ColdEvent
    network: DistributionNetwork
    scenarios: list[ScenarioOutcome] = []
    mitigations: list[Mitigation] = []
    executive_summary: str = ""                  # Claude-generated narrative
    methodology_notes: str = ""
    safety_flags: list[str] = []                 # e.g. "Voltage sag risk to medical devices"
    limitations: list[str] = []                  # data gaps / synthesis caveats
    citation_sources: dict[str, CitationSource] = {}   # inline-citation table for exec summary markers
    chart_paths: dict[str, str] = {}             # {"load_curve": "/data/winter/<job>/load.json", ...}


# ── Pipeline progress ─────────────────────────────────────────────────── #


class WinterPipelineStage(BaseModel):
    """Per-stage progress entry, streamed to the UI via SSE."""
    stage: str                                   # "workload_intelligence" | "grid_intelligence" | "cold_event_sim" | "risk_scoring" | "plan_synthesis"
    status: str                                  # "pending" | "running" | "complete" | "error"
    progress_pct: float = 0.0
    message: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
