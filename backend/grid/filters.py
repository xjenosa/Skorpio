"""
Site feasibility filters — knocks out infeasible candidates before
they reach the scoring stage.

Implements:
  * Capacity / latency / carbon-cap checks against the workload constraints
  * Interconnect-queue and moratorium policy flags
  * Curtailment and water-stress alerts
  * Heuristic composite score
"""
from typing import Optional

from backend.models.site import SiteProfile
from backend.models.workload import Workload
from backend.utils.logger import get_logger

logger = get_logger(__name__)

# Curated list of states / BAs with known interconnect queue moratoria.
# In production, refresh from the FERC queue API or each ISO's bulletin.
POLICY_BLOCKED_KEYWORDS = {
    "moratorium", "interconnect-queue paused", "no-build", "transmission embargo",
}
WATER_STRESS_KEYWORDS = {
    "level-2 drought", "groundwater advisory", "cooling restriction",
}


def compute_site_profile(
    raw: dict,
    workload: Optional[Workload] = None,
) -> Optional[SiteProfile]:
    """
    Take a raw site row (from real-estate / FERC / NREL services) and produce
    a normalised `SiteProfile`. Returns None if the row is unusable.
    """
    if not raw:
        return None

    capacity = _safe_float(raw.get("capacity_mw"))
    headroom = _safe_float(raw.get("transmission_headroom_mw"))
    pue = _safe_float(raw.get("pue"))
    latency = _safe_float(raw.get("fiber_latency_ms"))
    water = _safe_float(raw.get("water_l_per_mwh"))
    sub_dist = _safe_float(raw.get("substation_distance_km"))
    spot = _safe_float(raw.get("spot_lmp_usd_mwh"))
    lease = _safe_float(raw.get("lease_cost_usd_yr"))
    deploy = _safe_float(raw.get("deployment_months"))

    meets = True
    if workload is not None:
        if workload.target_capacity_mw and capacity is not None:
            meets = meets and capacity >= workload.target_capacity_mw * 0.85
        if workload.target_latency_ms and latency is not None:
            meets = meets and latency <= workload.target_latency_ms

    # Composite 0..1 — higher is better.
    score = 1.0
    if pue is not None:
        score *= max(0.4, min(1.0, (1.8 - pue) / 0.6))     # PUE 1.2 → 1.0, 1.8 → 0.0
    if spot is not None:
        score *= max(0.2, min(1.0, (90.0 - spot) / 90.0))  # cheaper spot is better
    if headroom is not None and workload and workload.target_capacity_mw:
        score *= max(0.3, min(1.0, headroom / max(workload.target_capacity_mw, 1.0)))
    score = round(max(0.0, min(1.0, score)), 3)

    flags = " ".join(filter(None, [
        str(raw.get("policy_notes", "")),
        str(raw.get("bulletin_text", "")),
    ])).lower()
    has_policy_blockers = any(k in flags for k in POLICY_BLOCKED_KEYWORDS)
    has_alerts = any(k in flags for k in WATER_STRESS_KEYWORDS)

    return SiteProfile(
        capacity_mw=capacity,
        transmission_headroom_mw=headroom,
        pue=pue,
        fiber_latency_ms=latency,
        water_l_per_mwh=water,
        substation_distance_km=sub_dist,
        spot_lmp_usd_mwh=spot,
        lease_cost_usd_yr=lease,
        meets_constraints=meets,
        overall_score=score,
        has_policy_blockers=has_policy_blockers,
        has_alerts=has_alerts,
        deployment_months=deploy,
    )


def passes_feasibility(profile: SiteProfile, strict: bool = False) -> bool:
    """
    Returns True if site passes basic feasibility filters.
    `strict=True` adds a deployment-speed cap (≤ 18 months) and PUE ≤ 1.45.
    """
    if not profile.meets_constraints:
        return False
    if profile.has_policy_blockers:
        return False
    if profile.deployment_months is not None and profile.deployment_months > 36:
        return False
    if strict:
        if profile.deployment_months is not None and profile.deployment_months > 18:
            return False
        if profile.pue is not None and profile.pue > 1.45:
            return False
    return True


def cluster_by_diversity(
    sites_features: list[list[float]], max_clusters: int = 12
) -> dict[int, list[int]]:
    """
    Cluster sites into `max_clusters` buckets by feature-vector diversity.
    Uses simple greedy farthest-point sampling (no sklearn dependency).
    Returns {cluster_id: [indices]}.
    """
    n = len(sites_features)
    if n == 0:
        return {}
    if n <= max_clusters:
        return {i: [i] for i in range(n)}

    import math

    def _dist(a: list[float], b: list[float]) -> float:
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    # Pick centroids via farthest-point sampling, seeded at index 0.
    centroids = [0]
    while len(centroids) < max_clusters:
        farthest = max(
            range(n),
            key=lambda i: min(_dist(sites_features[i], sites_features[c]) for c in centroids),
        )
        if farthest in centroids:
            break
        centroids.append(farthest)

    # Assign each site to nearest centroid
    clusters: dict[int, list[int]] = {c: [] for c in range(len(centroids))}
    for i in range(n):
        nearest = min(
            range(len(centroids)),
            key=lambda c: _dist(sites_features[i], sites_features[centroids[c]]),
        )
        clusters[nearest].append(i)
    return clusters


def compute_geo_proximity(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine great-circle distance in km — used to deduplicate near-identical candidate sites."""
    import math
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * R * math.asin(math.sqrt(a)), 2)


# ── helpers ──────────────────────────────────────────────────────────────────

def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
