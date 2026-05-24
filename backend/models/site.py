from pydantic import BaseModel, Field
from typing import Optional


class SiteProfile(BaseModel):
    """
    Physical, economic and operational attributes of a candidate site.
    Numeric fields are bounded to plausible real-world ranges so a Claude
    hallucination (e.g. `capacity_mw=-500`) can never reach the report.
    """
    # Capacity & power
    capacity_mw: Optional[float] = Field(None, ge=0.1, le=10_000)
    transmission_headroom_mw: Optional[float] = Field(None, ge=0.0, le=10_000)
    pue: Optional[float] = Field(None, ge=1.0, le=3.0)
    # Operational
    fiber_latency_ms: Optional[float] = Field(None, ge=0.0, le=500.0)
    water_l_per_mwh: Optional[float] = Field(None, ge=0.0, le=50.0)
    substation_distance_km: Optional[float] = Field(None, ge=0.0, le=500.0)
    # Economics
    spot_lmp_usd_mwh: Optional[float] = Field(None, ge=-50.0, le=2_000.0)  # LMP can briefly go negative
    lease_cost_usd_yr: Optional[float] = Field(None, ge=0.0, le=1_000_000_000)
    # Aggregate
    meets_constraints: bool = False
    overall_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    # Risk flags
    has_policy_blockers: bool = False
    has_alerts: bool = False
    deployment_months: Optional[float] = Field(None, ge=0.0, le=240.0)  # cap 20 years


class ParetoObjectives(BaseModel):
    """All 6 multi-objective scores, normalised 0-1 (higher = better)."""
    cost_economics: float = Field(0.5, ge=0.0, le=1.0)
    carbon_intensity: float = Field(0.5, ge=0.0, le=1.0)
    latency_fit: float = Field(0.5, ge=0.0, le=1.0)
    transmission_headroom: float = Field(0.5, ge=0.0, le=1.0)
    deployment_speed: float = Field(0.5, ge=0.0, le=1.0)
    operational_resilience: float = Field(0.5, ge=0.0, le=1.0)
    pareto_rank: int = Field(1, ge=1)
    weighted_score: float = Field(0.5, ge=0.0, le=1.0)


class ObjectiveWeights(BaseModel):
    """Workload-context weights assigned by Claude. Must sum to ~1.0."""
    cost_economics: float = Field(0.25, ge=0.0, le=1.0)
    carbon_intensity: float = Field(0.20, ge=0.0, le=1.0)
    latency_fit: float = Field(0.15, ge=0.0, le=1.0)
    transmission_headroom: float = Field(0.15, ge=0.0, le=1.0)
    deployment_speed: float = Field(0.15, ge=0.0, le=1.0)
    operational_resilience: float = Field(0.10, ge=0.0, le=1.0)
    rationale: str = ""


class Site(BaseModel):
    """A candidate datacenter site within a region."""
    site_id: str = ""                       # e.g. "ALPHA-04"
    name: str                               # human-readable (e.g. "Sterling, OH")
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    address: Optional[str] = None
    region_iso: str                         # parent region code (e.g. "PJM-W")
    # Mapping
    topology_block: Optional[str] = None    # GeoJSON / KML block for the candidate footprint
    parcel_path: Optional[str] = None       # path to parcel boundary file
    # Properties
    profile: SiteProfile = Field(default_factory=SiteProfile)
    # Multi-objective optimisation
    pareto_objectives: Optional[ParetoObjectives] = None
    # Origin
    generation_method: str = ""             # e.g. "ferc_queue", "real_estate_search", "expansion_of_known"
    parent_site_id: Optional[str] = None    # ancestor site if derived from a known operator's footprint
    # Similarity
    distance_to_known_dc_km: Optional[float] = None
    nearest_known_operator: Optional[str] = None
    # Ranking
    diversity_cluster: Optional[int] = None
    rank: Optional[int] = None


class SiteLibrary(BaseModel):
    """Set of candidate sites within one region."""
    region_iso: str
    sites: list[Site] = []
    generation_params: dict = {}
    total_generated: int = 0
    total_passed_filters: int = 0
    # Disclosure messages the generator wants surfaced as safety_flags on the
    # final plan. Populated by SiteGenerationEngine when, e.g., the
    # utility-territory filter found zero candidates and the engine widened
    # the search to the whole province. Picked up by
    # plan_synthesis._collect_safety_flags so the operator can see the
    # routing decision in the final report.
    library_flags: list[str] = []
