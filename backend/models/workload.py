from pydantic import BaseModel, Field
from typing import Optional


class RegionEvidence(BaseModel):
    """A sourced claim about a region — used to justify ranking decisions."""
    source: str                         # e.g. "EIA", "IPCC AR5", "IESO", "PJM"
    score: float = Field(ge=0.0, le=1.0)
    bulletins: list[str] = []           # bulletin / docket IDs supporting the claim
    description: str = ""


class BalancingAuthority(BaseModel):
    """An ISO / RTO transmission topology reference."""
    ba_code: str                        # e.g. "PJM", "ERCO", "CISO"
    name: str
    operator: str                       # e.g. "PJM Interconnection LLC"
    url: str = ""


class Region(BaseModel):
    """
    An ISO / market region considered for workload placement. The
    structured object the rest of the pipeline reasons about.
    """
    iso_code: str                       # e.g. "PJM-W", "ERCO-N"
    name: str                           # e.g. "PJM West"
    balancing_authority: str            # FERC BA code, e.g. "PJM"
    states: list[str] = []
    topology_id: Optional[str] = None              # transmission-zone ID where applicable
    preferred_zone: Optional[str] = None           # the picked zone within the region
    grid_telemetry_path: Optional[str] = None      # cached telemetry snapshot path on disk
    timezone: str = "America/New_York"
    function_summary: str = ""                     # plain-text description of the region's role
    authorities: list[BalancingAuthority] = []     # FERC/RTO / NERC entities operating in this region
    evidence: list[RegionEvidence] = []
    # Scoring inputs (0..1 normalised)
    headroom_score: float = Field(0.0, ge=0.0, le=1.0)
    carbon_score: float = Field(0.0, ge=0.0, le=1.0)
    economics_score: float = Field(0.0, ge=0.0, le=1.0)
    overall_score: float = Field(0.0, ge=0.0, le=1.0)
    # Operational specifics
    interconnect_substations: list[str] = []       # candidate POIs, e.g. ["Keystone 500kV"]
    interconnect_center: Optional[tuple[float, float]] = None       # (lat, lon)
    interconnect_radius_km: float = Field(100.0, ge=0.0, le=1000.0)
    topology_graph: Optional[dict] = None          # {nodes, edges} for the transmission overlay


class Workload(BaseModel):
    """
    The user's request: where to place a compute workload.
    """
    query: str                          # raw user input
    normalized_name: str                # e.g. "Training cluster · Q3 expansion"
    workload_class: Optional[str] = None       # "training", "inference", "edge-pop", "colocation"
    target_capacity_mw: float = Field(0.0, ge=0.0, le=10_000)
    target_latency_ms: Optional[float] = Field(None, ge=0.0, le=1000.0)
    max_carbon_g_co2_kwh: Optional[float] = Field(None, ge=0.0, le=2000.0)
    description: str = ""
    candidate_iso_codes: list[str] = []        # ISO regions seeded by the prompt
    # Hard geographic filter extracted from the prompt — populated when the
    # user explicitly names a country / province / state ("in Quebec", "in
    # Alberta with latency to Calgary", "Ontario only"). When non-empty,
    # the region-selection stage MUST only return regions whose `iso_code`
    # appears here. Empty = no constraint, Claude can pick freely.
    geographic_constraint: list[str] = []
    # Utility / LDC the user explicitly named in the prompt ("Alectra's
    # service territory", "BC Hydro"). Populated by WorkloadAgent's
    # _detect_utilities scanner using a public LDC → province lookup. When
    # set, the site generator narrows seed cities + substation anchors to
    # this operator's territory (REPORTS_COHESION.md §0 — territory routing
    # is data-derived from real OSM substation footprints, not LLM-inferred).
    # Lowercased canonical key matching _SUBSTATIONS_BY_OPERATOR (e.g.
    # "alectra", "hydro one", "bc hydro").
    named_utility: Optional[str] = None
    regions: list[Region] = []
    context_summary: str = ""                  # Claude-generated workload overview
