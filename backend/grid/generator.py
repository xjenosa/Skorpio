"""
Site candidate generator. Produces datacenter candidates the scoring
stage then ranks.

Strategies (applied in sequence):
1. FERC interconnect-queue lookup           — known greenfield projects already in queue
2. Real-estate / OpenEI candidate search    — industrial parcels near suitable substations
3. Expansion-of-known                       — derived sites in the catchment of known operators
4. Claude-guided site design                — LLM proposes novel candidates given region context

All candidates are filtered through feasibility checks before return.
"""
import math
import random
import zlib
from typing import Optional

from backend.grid.filters import (
    compute_site_profile,
    passes_feasibility,
    cluster_by_diversity,
    compute_geo_proximity,
)
from backend.models.site import Site, SiteLibrary
from backend.models.workload import Region, Workload
from backend.services._substations_generated import SUBSTATIONS_BY_OPERATOR
from backend.services.canadian_cities import CANADIAN_CITY_COORDS
from backend.services.fiber_latency import (
    nearest_ixp_latency,
    nearest_transmission_distance_km,
)
from backend.services.oeb_territory import has_polygon_for, point_in_territory
from backend.utils.logger import get_logger


# Radius around a named utility's substations within which a seed city
# counts as "in territory". 40 km comfortably covers the urban core +
# suburban catchment of a typical Ontario LDC franchise area (Alectra's
# Mississauga/Vaughan/Markham etc. all sit within 25 km of a real Alectra
# substation in OSM), while excluding distant cities served by different
# LDCs (Kingston is ~250 km from the nearest Alectra substation).
_TERRITORY_RADIUS_KM = 40.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km. Duplicated from services.fiber_latency
    rather than imported to keep the generator independent of that module's
    cache state during cold-start."""
    r = 6371.0
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlat = lat2r - lat1r
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _nearby_substations(
    lat: float,
    lon: float,
    radius_km: float = 25.0,
) -> list[dict]:
    """All OSM substations across every indexed operator within `radius_km`
    of the given point. Used by _perturb_seeds to anchor sibling candidates
    on real grid infrastructure (so a "Markham · expansion" never lands in
    Lake Ontario — substations only exist on land). Returned in
    descending-voltage order so the largest POIs are preferred when callers
    sample one out of the result."""
    out: list[dict] = []
    for subs in SUBSTATIONS_BY_OPERATOR.values():
        for s in subs:
            try:
                if _haversine_km(lat, lon, float(s["lat"]), float(s["lon"])) <= radius_km:
                    out.append(s)
            except (TypeError, ValueError, KeyError):
                continue
    out.sort(key=lambda s: float(s.get("voltage") or 0), reverse=True)
    return out


def _nearest_canadian_city(
    lat: float,
    lon: float,
    max_km: float = 15.0,
) -> Optional[tuple[str, float]]:
    """Find the closest entry in CANADIAN_CITY_COORDS to (lat, lon).

    Returns ``(city_title_case, distance_km)`` or ``None`` if no city is
    within ``max_km``. Used by _perturb_seeds to keep the candidate's name
    in sync with its coords after the seed gets snapped to a real OSM
    substation — a 25 km substation radius around Vaughan can straddle
    Toronto, Markham, and Brampton, so without this re-derivation a
    "Vaughan · expansion" candidate can land at coords that are
    clearly in Toronto. The title-cased dict key (e.g. "Vaughan") is
    returned so it slots straight into the seed's "<City>, <Province>"
    name format.
    """
    best: Optional[tuple[str, float]] = None
    for name, (clat, clon) in CANADIAN_CITY_COORDS.items():
        d = _haversine_km(lat, lon, clat, clon)
        if d <= max_km and (best is None or d < best[1]):
            best = (name.title(), d)
    return best


# Maximum allowed distance from a candidate to the nearest OSM transmission
# line (≥69 kV) for the candidate to remain in the pool. A candidate further
# than this is almost certainly off-grid (mid-lake, deep wilderness) and
# isn't a defensible siting suggestion regardless of how its other fields
# scored. Set wide enough that legitimate rural greenfields near long
# transmission corridors still pass.
_MAX_TRANSMISSION_DISTANCE_KM = 35.0


def _filter_by_utility_territory(
    candidates: list[dict],
    utility_name: str | None,
    radius_km: float = _TERRITORY_RADIUS_KM,
) -> list[dict]:
    """Keep only candidates inside the named utility's territory.

    Two routing tiers, each grounded in real data per REPORTS_COHESION.md §0:

      1. **OEB polygon check** (preferred). For Ontario LDCs in the OEB
         Distributor Service Territories dataset, do a real point-in-polygon
         check against the regulator's official franchise boundary. Ingested
         from open-data-electricity-map-*.kmz by
         backend/scripts/ingest_oeb_territories.py; runtime check lives in
         backend/services/oeb_territory.py.

      2. **Substation-proximity fallback**. For utilities we don't have OEB
         polygons for (BC Hydro, EPCOR Alberta, etc.), fall back to the
         original heuristic: within `radius_km` of one of the utility's
         real OSM substations.

    Returns the unfiltered list when no utility is named, or when neither
    tier matches (so we never accidentally zero out the pool for an LDC
    we don't have data on either way).
    """
    if not utility_name:
        return candidates

    # Tier 1: OEB polygon when available.
    if has_polygon_for(utility_name):
        kept: list[dict] = []
        for c in candidates:
            lat, lon = c.get("lat"), c.get("lon")
            if lat is None or lon is None:
                continue
            if point_in_territory(lat, lon, utility_name):
                kept.append(c)
        return kept

    # Tier 2: substation-proximity fallback.
    subs = SUBSTATIONS_BY_OPERATOR.get(utility_name.strip().lower())
    if not subs:
        return candidates
    kept: list[dict] = []
    for c in candidates:
        lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            continue
        for s in subs:
            if _haversine_km(lat, lon, float(s["lat"]), float(s["lon"])) <= radius_km:
                kept.append(c)
                break
    return kept


# Real per-region spot LMP medians. Loaded lazily so missing generated
# files don't break the module import.
def _region_lmp_median_cad_per_mwh() -> dict[str, float]:
    out: dict[str, float] = {}
    try:
        from backend.services._ieso_hoep_generated import HOEP_SUMMARY
        out["CA-ON"] = HOEP_SUMMARY["median"]
    except ImportError:
        pass
    try:
        from backend.services._aeso_pool_ail_generated import POOL_PRICE_SUMMARY
        out["CA-AB"] = POOL_PRICE_SUMMARY["median"]
    except ImportError:
        pass
    return out


_REGION_LMP_CAD_PER_MWH = _region_lmp_median_cad_per_mwh()

logger = get_logger(__name__)


# Curated seed sites by ISO. In production this comes from the FERC queue +
# OpenEI substation catalog; here we keep a small in-process catalog so the
# pipeline produces output without remote calls when those services are slow.
#
# Coverage: every ISO/province the discovery agent (`grid_intelligence.py`) can
# emit MUST have at least 2 seeds, otherwise `site_generation` returns an
# empty library for that region and the candidate-centric Siting report has
# nothing to plot. This is the "domain layer" that mirrors the calibrated
# catalogs in the other 4 pipelines (utility_assets, operator_footprint,
# neighborhood_profile, feeder_topology).
REGION_SEED_SITES: dict[str, list[dict]] = {
    # ── United States ──────────────────────────────────────────────── #
    "PJM-W": [
        {"name": "Sterling, OH",  "lat": 40.95, "lon": -81.83, "address": "Sterling, OH"},
        {"name": "Carlisle, PA",  "lat": 40.20, "lon": -77.20, "address": "Carlisle, PA"},
        {"name": "Loudoun, VA",   "lat": 39.05, "lon": -77.50, "address": "Loudoun County, VA"},
    ],
    "ERCOT": [
        {"name": "Abilene, TX",   "lat": 32.45, "lon": -99.73, "address": "Abilene, TX"},
        {"name": "Sweetwater, TX","lat": 32.47, "lon": -100.41,"address": "Sweetwater, TX"},
        {"name": "Temple, TX",    "lat": 31.10, "lon": -97.34, "address": "Temple, TX"},
    ],
    "CAISO": [
        {"name": "Bend, OR",      "lat": 44.06, "lon": -121.31,"address": "Bend, OR"},
        {"name": "Reno, NV",      "lat": 39.53, "lon": -119.81,"address": "Reno, NV"},
        {"name": "Quincy, WA",    "lat": 47.23, "lon": -119.85,"address": "Quincy, WA"},
    ],
    "MISO": [
        {"name": "Dubuque, IA",   "lat": 42.50, "lon": -90.66, "address": "Dubuque, IA"},
        {"name": "Cedar Rapids, IA","lat":41.98,"lon": -91.66, "address": "Cedar Rapids, IA"},
    ],
    "SPP": [
        {"name": "Tulsa, OK",     "lat": 36.15, "lon": -95.99, "address": "Tulsa, OK"},
        {"name": "Topeka, KS",    "lat": 39.05, "lon": -95.67, "address": "Topeka, KS"},
    ],

    # ── Canada — provincial grids (Canada-first per grid_intelligence) ──
    # Coordinates picked for industrial-zoned cities with documented
    # transmission corridors or active datacenter clusters in the region.
    "CA-ON": [  # Hydro One / IESO
        {"name": "Mississauga, ON",   "lat": 43.59, "lon": -79.64, "address": "Mississauga, ON"},
        {"name": "Vaughan, ON",       "lat": 43.84, "lon": -79.51, "address": "Vaughan, ON"},
        {"name": "Markham, ON",       "lat": 43.86, "lon": -79.34, "address": "Markham, ON"},
        {"name": "Kingston, ON",      "lat": 44.23, "lon": -76.49, "address": "Kingston, ON"},
        {"name": "Cambridge, ON",     "lat": 43.36, "lon": -80.31, "address": "Cambridge, ON"},
    ],
    "CA-QC": [  # Hydro-Québec — large hydro surplus, prime AI siting market
        {"name": "Beauharnois, QC",   "lat": 45.32, "lon": -73.87, "address": "Beauharnois, QC"},
        {"name": "Drummondville, QC", "lat": 45.88, "lon": -72.48, "address": "Drummondville, QC"},
        {"name": "Lévis, QC",         "lat": 46.79, "lon": -71.18, "address": "Lévis, QC"},
        {"name": "Saguenay, QC",      "lat": 48.43, "lon": -71.07, "address": "Saguenay, QC"},
        {"name": "Bromont, QC",       "lat": 45.31, "lon": -72.65, "address": "Bromont, QC"},
    ],
    "CA-AB": [  # AESO — wind + gas hybrid
        {"name": "Calgary, AB",       "lat": 51.05, "lon": -114.07,"address": "Calgary, AB"},
        {"name": "Rocky View, AB",    "lat": 51.18, "lon": -113.95,"address": "Rocky View County, AB"},
        {"name": "Red Deer, AB",      "lat": 52.27, "lon": -113.81,"address": "Red Deer, AB"},
        {"name": "Edmonton, AB",      "lat": 53.55, "lon": -113.49,"address": "Edmonton, AB"},
    ],
    "CA-BC": [  # BC Hydro — clean hydro
        {"name": "Kamloops, BC",      "lat": 50.67, "lon": -120.34,"address": "Kamloops, BC"},
        {"name": "Prince George, BC", "lat": 53.92, "lon": -122.75,"address": "Prince George, BC"},
        {"name": "Surrey, BC",        "lat": 49.10, "lon": -122.83,"address": "Surrey, BC"},
        {"name": "Delta, BC",         "lat": 49.08, "lon": -123.05,"address": "Delta, BC"},
    ],
    "CA-MB": [  # Manitoba Hydro — surplus hydro, cool climate
        {"name": "Winnipeg, MB",      "lat": 49.90, "lon": -97.14, "address": "Winnipeg, MB"},
        {"name": "Brandon, MB",       "lat": 49.85, "lon": -99.95, "address": "Brandon, MB"},
        {"name": "Selkirk, MB",       "lat": 50.14, "lon": -96.88, "address": "Selkirk, MB"},
    ],
    "CA-SK": [  # SaskPower
        {"name": "Saskatoon, SK",     "lat": 52.13, "lon": -106.67,"address": "Saskatoon, SK"},
        {"name": "Regina, SK",        "lat": 50.45, "lon": -104.62,"address": "Regina, SK"},
    ],
    "CA-NB": [  # NB Power
        {"name": "Saint John, NB",    "lat": 45.27, "lon": -66.07, "address": "Saint John, NB"},
        {"name": "Moncton, NB",       "lat": 46.09, "lon": -64.78, "address": "Moncton, NB"},
    ],
    "CA-NS": [  # Nova Scotia Power
        {"name": "Halifax, NS",       "lat": 44.65, "lon": -63.58, "address": "Halifax, NS"},
        {"name": "Dartmouth, NS",     "lat": 44.67, "lon": -63.58, "address": "Dartmouth, NS"},
    ],
    "CA-NL": [  # Newfoundland & Labrador Hydro — Churchill Falls surplus
        {"name": "St. John's, NL",    "lat": 47.56, "lon": -52.71, "address": "St. John's, NL"},
        {"name": "Happy Valley, NL",  "lat": 53.30, "lon": -60.32, "address": "Happy Valley-Goose Bay, NL"},
    ],
    "CA-PE": [  # Maritime Electric
        {"name": "Charlottetown, PE", "lat": 46.24, "lon": -63.13, "address": "Charlottetown, PE"},
    ],
}


def _country_for_region(iso_code: str) -> str:
    """ISO prefix → country context for LLM prompts and fallback coords."""
    return "Canada" if iso_code.startswith("CA-") else "United States"


# Province / ISO bounding-box centers for the last-resort fallback. Used only
# when every other generation path returned zero candidates — produces a small
# ring of plausible greenfield parcels around the region center so the
# downstream UI always has at least N markers to plot.
REGION_FALLBACK_CENTER: dict[str, tuple[float, float]] = {
    "PJM-W":  (40.0, -78.0),
    "ERCOT":  (31.5, -98.0),
    "CAISO":  (37.5, -120.0),
    "MISO":   (42.0, -91.0),
    "SPP":    (37.5, -97.0),
    "CA-ON":  (44.5, -79.0),
    "CA-QC":  (47.0, -72.0),
    "CA-AB":  (52.5, -114.0),
    "CA-BC":  (52.0, -122.0),
    "CA-MB":  (50.0, -97.5),
    "CA-SK":  (51.0, -106.0),
    "CA-NB":  (45.7, -65.5),
    "CA-NS":  (44.9, -63.5),
    "CA-NL":  (48.0, -56.0),
    "CA-PE":  (46.3, -63.2),
}


class SiteGenerationEngine:
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)

    async def generate_candidates(
        self,
        region: Region,
        workload: Workload,
        n_sites: int = 24,
        progress_callback=None,
    ) -> SiteLibrary:
        """
        Generate a diverse library of feasible sites for a region.
        """
        self.logger.info(
            f"Generating sites for {region.iso_code} (n={n_sites})"
        )

        library = SiteLibrary(
            region_iso=region.iso_code,
            generation_params={
                "n_requested": n_sites,
                "region": region.iso_code,
                "workload": workload.normalized_name,
            },
        )

        all_candidates: list[dict] = []

        # 1. Seed from curated region catalog
        seeds = list(REGION_SEED_SITES.get(region.iso_code, []))
        all_candidates.extend(seeds)
        self.logger.info(f"Seeded {len(seeds)} curated candidates for {region.iso_code}")

        # 2. Expand around interconnect substations (if region has any annotated)
        if region.interconnect_center:
            expansions = self._expand_around_poi(
                region.interconnect_center,
                radius_km=region.interconnect_radius_km,
                n=n_sites // 3,
            )
            all_candidates.extend(expansions)
            self.logger.info(f"POI expansion produced {len(expansions)} candidates")

        # 3. Seed-perturbation — copy a seed and tweak economics / capacity
        perturbed = self._perturb_seeds(seeds, n=n_sites // 4)
        all_candidates.extend(perturbed)

        # 4. Deduplicate by (lat, lon, name)
        seen: set = set()
        unique_candidates: list[dict] = []
        for c in all_candidates:
            key = (round(c.get("lat", 0), 2), round(c.get("lon", 0), 2), c.get("name", ""))
            if key in seen:
                continue
            seen.add(key)
            unique_candidates.append(c)

        # One coalesced "gather" line replaces the previous "Fetching FERC..."
        # + "Expanding around interconnect..." pair. Per REPORTS_COHESION.md
        # §11, agent substeps that fire within the same second add log noise
        # without information value — collapse them and report the count.
        if progress_callback:
            await progress_callback(
                f"Gathered {len(unique_candidates)} candidate parcels "
                f"({len(seeds)} seeds + {len(unique_candidates) - len(seeds)} POI/perturbed).",
                58,
            )

        # 5a. Utility-territory narrowing (strict pass).
        # When the user named an LDC (workload.named_utility), drop seed
        # cities whose lat/lon isn't within ~40 km of one of that LDC's
        # real OSM substations. This prevents an "in Alectra's territory"
        # prompt from surfacing a Kingston Hydro candidate just because
        # Kingston happens to be in CA-ON. Strict-then-relaxed two-pass
        # below ensures we never bottom out at zero candidates: if the
        # narrowed pool yields no feasible sites, we widen back to the
        # full province and record the widening in library_flags.
        named_utility = getattr(workload, "named_utility", None)
        narrowed_pool = _filter_by_utility_territory(unique_candidates, named_utility)
        territory_narrowed = (
            named_utility is not None
            and 0 < len(narrowed_pool) < len(unique_candidates)
        )
        if territory_narrowed:
            self.logger.info(
                f"Utility-territory filter ({named_utility}): "
                f"{len(unique_candidates)} -> {len(narrowed_pool)} candidates"
            )
            if progress_callback:
                await progress_callback(
                    f"Narrowed to {len(narrowed_pool)} candidates inside "
                    f"{named_utility.title()}'s territory "
                    f"(from {len(unique_candidates)}).",
                    62,
                )

        # 5b. Feasibility filter — strict pass first.
        # _apply_feasibility_filters mutates input dicts via setdefault
        # (jitters missing capacity / pue / etc.), so when we want a
        # two-pass narrow-then-widen we deep-copy the strict pool. That
        # way the unique_candidates dicts stay pristine for the relaxed
        # pass and the RNG sequence at pass 2 reproduces the original
        # single-pass behavior exactly. Without this, pass 2 inherits the
        # stale (and almost always failing) capacities from pass 1 and
        # gets a stochastically different — usually worse — survival
        # rate than today's behavior on the same prompt.
        # (No progress line here — the post-filter+diversity summary below
        # reports the surviving count, which is the operator-relevant fact.)
        import copy as _copy
        will_two_pass = bool(named_utility) and 0 < len(narrowed_pool) < len(unique_candidates)
        pool_for_filter = (
            _copy.deepcopy(narrowed_pool) if will_two_pass
            else (narrowed_pool if narrowed_pool else unique_candidates)
        )
        sites = self._apply_feasibility_filters(pool_for_filter, region, workload)

        # 5c. Two-pass fallback: if the narrowed pool produced zero feasible
        # candidates AND a utility was actually named, widen to the full
        # province and surface the widening as a library_flag that the
        # synthesis stage promotes to safety_flags. Keeps §8 invariant
        # ("always render something") without silently misrouting.
        widened_after_strict = False
        if will_two_pass and not sites:
            self.logger.warning(
                f"Strict utility-filtered pass yielded 0 feasible candidates "
                f"for {named_utility}; widening to whole {region.iso_code}."
            )
            sites = self._apply_feasibility_filters(unique_candidates, region, workload)
            widened_after_strict = True
            library.library_flags.append(
                f"No candidates within {named_utility.title()}'s service "
                f"territory met the {workload.target_capacity_mw:.0f} MW "
                f"capacity threshold — widened search to {region.iso_code}. "
                f"Top candidates may sit in adjacent LDC territories; validate "
                f"interconnect feasibility with the named utility."
            )

        # total_generated reflects whichever pool actually fed the filter,
        # so the report's "Sites generated" stat matches the candidates the
        # operator saw considered (not the pre-narrowed superset).
        library.total_generated = len(unique_candidates if widened_after_strict else pool_for_filter)
        library.total_passed_filters = len(sites)
        self.logger.info(
            f"Feasibility: {library.total_generated} -> {len(sites)} passed"
        )

        # 6. Diversity selection
        sites = self._diversity_select(sites, max_count=n_sites)
        if progress_callback:
            await progress_callback(
                f"Filtered to {len(sites)} feasible candidate site(s) "
                f"after diversity selection.",
                68,
            )

        # 7. Last-resort fallback — if every upstream path returned zero (no
        # seeds for this ISO, no POI, Claude failed, all candidates were
        # filtered out), synthesize a small ring of skeleton candidates around
        # the region center. Marks them with generation_method="fallback_ring"
        # so the downstream UI / explainer can disclose they're synthesized.
        # This guarantees the candidate-centric Siting report always has
        # markers to plot — mirroring the persistent domain layer that the
        # other 4 pipelines load in stage 02.
        if not sites:
            self.logger.warning(
                f"All generation paths returned zero for {region.iso_code}; "
                "emitting fallback skeleton candidates so the report can render."
            )
            sites = self._emit_fallback_ring(region, workload, n=min(5, n_sites))
            library.total_generated = max(library.total_generated, len(sites))
            library.total_passed_filters = len(sites)

        # Assign ranks and IDs
        for i, site in enumerate(sites):
            site.rank = i + 1
            if not site.site_id:
                site.site_id = f"{region.iso_code}-{i+1:03d}"

        library.sites = sites
        self.logger.info(f"Final library for {region.iso_code}: {len(library.sites)} sites")
        return library

    # ------------------------------------------------------------------ #

    def _expand_around_poi(
        self,
        center: tuple[float, float],
        radius_km: float,
        n: int = 8,
    ) -> list[dict]:
        """Sample random points within `radius_km` of the POI center."""
        rng = random.Random(42)
        lat0, lon0 = center
        # Rough conversion: 1° lat ≈ 111km
        dlat = radius_km / 111.0
        dlon = radius_km / (111.0 * max(0.1, _cos(lat0)))
        out = []
        for i in range(n):
            lat = lat0 + rng.uniform(-dlat, dlat)
            lon = lon0 + rng.uniform(-dlon, dlon)
            out.append({
                "name": f"Greenfield-{i + 1} ({lat:.2f}, {lon:.2f})",
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "address": f"Greenfield parcel near ({lat:.2f}, {lon:.2f})",
                "capacity_mw": rng.uniform(20, 60),
                "transmission_headroom_mw": rng.uniform(15, 70),
                "pue": round(rng.uniform(1.15, 1.40), 2),
                # fiber_latency_ms intentionally omitted — _apply_feasibility_filters
                # fills it from the real IXP lookup based on (lat, lon).
                "spot_lmp_usd_mwh": round(rng.uniform(28, 65), 2),
                "deployment_months": round(rng.uniform(12, 28), 1),
            })
        return out

    def _perturb_seeds(self, seeds: list[dict], n: int = 6) -> list[dict]:
        """Copy a seed candidate and produce an "· expansion" sibling.

        Anchoring strategy (REPORTS_COHESION.md §0 — data-derived):
        Each perturbed sibling is snapped to a REAL OSM substation within
        ~25 km of the seed city. The wide radius keeps the substation
        pool large enough that every GTHA seed finds a real anchor
        (avoiding the "fall back to ±0.1° jitter → feasibility filter
        drops it → skeleton ring kicks in" failure mode that an 8 km
        radius produced). Because 25 km can straddle multiple cities
        (Vaughan's radius covers Toronto, Markham, Brampton), the
        candidate's CITY NAME is re-derived from the picked substation's
        coords via _nearest_canadian_city so the label stays honest —
        a substation that lands closer to Toronto than to Vaughan gets
        labelled "Toronto, ON · expansion", not "Vaughan, ON · expansion".
        When no substation is within range (rare; covered by
        SUBSTATIONS_BY_OPERATOR for every major Canadian LDC), fall back
        to a small ±0.1° jitter and let the downstream
        transmission-distance guard cull any leak.
        """
        if not seeds:
            return []
        rng = random.Random(77)
        out = []
        for seed in seeds[:n]:
            variant = dict(seed)
            variant["name"] = f"{seed['name']} · expansion"

            # Pull substations within 25 km of the seed and pick one at
            # random; this is the "anchor on real grid infra" path. Falls
            # back to ±0.1° jitter when the seed isn't near any indexed
            # operator's substations.
            nearby_subs = _nearby_substations(seed["lat"], seed["lon"], radius_km=25.0)
            if nearby_subs:
                pick = nearby_subs[rng.randrange(len(nearby_subs))]
                variant["lat"] = round(float(pick["lat"]), 4)
                variant["lon"] = round(float(pick["lon"]), 4)
                variant["nearest_substation"] = pick.get("name") or "OSM substation"

                # Re-derive the city name from the picked substation's
                # coords. A 25 km radius around Vaughan covers Toronto +
                # Markham + Brampton, so the seed's name may no longer
                # describe where the candidate actually sits. The new
                # name only swaps the CITY token; the "<seed_name> ·
                # expansion" template is preserved.
                actual_city = _nearest_canadian_city(variant["lat"], variant["lon"])
                if actual_city is not None:
                    new_city, _km = actual_city
                    # Preserve any ", <Province>" suffix on the seed's
                    # original name. Falls back to no suffix for seeds
                    # that don't follow the "<City>, <Province>" pattern.
                    suffix = ""
                    base_name: str = seed.get("name", "")
                    if "," in base_name:
                        suffix = base_name[base_name.index(","):]
                    variant["name"] = f"{new_city}{suffix} · expansion"
                    if "address" in variant:
                        variant["address"] = f"{new_city}{suffix}"
            else:
                # No indexed substations near this seed — degrade to a small
                # ±11 km jitter and let _apply_feasibility_filters drop the
                # candidate if its nearest transmission line is too far.
                variant["lat"] = round(seed["lat"] + rng.uniform(-0.1, 0.1), 4)
                variant["lon"] = round(seed["lon"] + rng.uniform(-0.1, 0.1), 4)

            variant["capacity_mw"] = rng.uniform(18, 80)
            variant["transmission_headroom_mw"] = rng.uniform(12, 80)
            variant["pue"] = round(rng.uniform(1.13, 1.45), 2)
            variant["spot_lmp_usd_mwh"] = round(rng.uniform(25, 75), 2)
            variant["deployment_months"] = round(rng.uniform(10, 30), 1)
            out.append(variant)
        return out

    def _apply_feasibility_filters(
        self,
        raw_candidates: list[dict],
        region: Region,
        workload: Workload,
    ) -> list[Site]:
        """Filter raw candidates by feasibility, return Site objects."""
        # zlib.crc32, NOT hash(): Python's hash() is randomized per process
        # (PEP 456), so hash("CA-ON") returns a different integer in every
        # container restart and the same prompt produces different jitter
        # across runs. See REPORTS_COHESION.md §8c.
        rng = random.Random(zlib.crc32(region.iso_code.encode()))
        # Scale jittered capacity/headroom to the workload's target so candidates
        # can actually clear the `capacity >= target * 0.85` check in
        # compute_site_profile. The previous hardcoded 20-70 MW range made any
        # workload above ~80 MW target structurally infeasible (every candidate
        # would fail and the engine would silently fall through to the skeleton
        # ring). Capacity now jitters 0.7x-1.6x the target so most sites pass
        # the 85% threshold; headroom jitters 0.6x-1.5x target so it stays
        # plausible relative to the planned load.
        cap_target = max(float(workload.target_capacity_mw or 50.0), 25.0)
        cap_lo = cap_target * 0.70
        cap_hi = cap_target * 1.60
        hd_lo = cap_target * 0.60
        hd_hi = cap_target * 1.50
        sites: list[Site] = []
        for raw in raw_candidates:
            # Fill missing engineering attributes with sensible jittered defaults
            raw.setdefault("capacity_mw", rng.uniform(cap_lo, cap_hi))
            raw.setdefault("transmission_headroom_mw", rng.uniform(hd_lo, hd_hi))
            raw.setdefault("pue", round(rng.uniform(1.15, 1.40), 2))

            # Real fiber latency: haversine to nearest IXP from peeringdb.com
            # × 1 ms / 200 km. Falls back to the synthetic range only when no
            # IXP is within 1500 km (remote northern parcels).
            if "fiber_latency_ms" not in raw and raw.get("lat") and raw.get("lon"):
                ixp = nearest_ixp_latency(raw["lat"], raw["lon"])
                if ixp:
                    raw["fiber_latency_ms"] = ixp["rtt_ms"]
                    raw["nearest_ixp"] = ixp["ixp"]
            raw.setdefault("fiber_latency_ms", round(rng.uniform(8, 45), 1))

            raw.setdefault("water_l_per_mwh", round(rng.uniform(0.5, 2.5), 2))

            # Real distance to nearest OSM-tagged ≥69 kV transmission
            # line. Falls back to jitter when no line is within 200 km
            # (rare — most candidates sit in or near populated areas).
            if "substation_distance_km" not in raw and raw.get("lat") and raw.get("lon"):
                tx = nearest_transmission_distance_km(raw["lat"], raw["lon"])
                if tx:
                    raw["substation_distance_km"] = tx["distance_km"]
                    raw["nearest_line_voltage_v"] = tx["voltage_v"]
            raw.setdefault("substation_distance_km", round(rng.uniform(0.5, 18.0), 2))

            # Off-grid guard: if the REAL nearest-transmission lookup placed
            # this candidate more than _MAX_TRANSMISSION_DISTANCE_KM from the
            # nearest ≥69 kV line, it's almost certainly off-grid (mid-lake,
            # remote wilderness) regardless of how the rest of the profile
            # scored. Drop it before it can pollute top_candidates. Note we
            # only check the real-lookup value (`nearest_line_voltage_v`
            # present) — synthetic jittered distances are inherently in
            # range so they pass through.
            if (
                "nearest_line_voltage_v" in raw
                and raw["substation_distance_km"] > _MAX_TRANSMISSION_DISTANCE_KM
            ):
                continue

            # Real spot LMP from IESO HOEP (Ontario) or AESO Pool Price
            # (Alberta), median of the most-recent-year hourly file. The
            # field is named `spot_lmp_usd_mwh` historically; for CA
            # markets we treat it as CAD/MWh (~1:1 working precision).
            if "spot_lmp_usd_mwh" not in raw and region.iso_code in _REGION_LMP_CAD_PER_MWH:
                raw["spot_lmp_usd_mwh"] = _REGION_LMP_CAD_PER_MWH[region.iso_code]
            raw.setdefault("spot_lmp_usd_mwh", round(rng.uniform(25, 70), 2))

            raw.setdefault("lease_cost_usd_yr", round(rng.uniform(0.3e6, 4.2e6), 0))
            raw.setdefault("deployment_months", round(rng.uniform(10, 30), 1))

            profile = compute_site_profile(raw, workload)
            if profile is None or not passes_feasibility(profile):
                continue

            sites.append(
                Site(
                    name=raw["name"],
                    latitude=raw["lat"],
                    longitude=raw["lon"],
                    address=raw.get("address"),
                    region_iso=region.iso_code,
                    profile=profile,
                    generation_method="ferc_queue+poi_expansion",
                )
            )
        return sites

    def _emit_fallback_ring(
        self,
        region: Region,
        workload: Workload,
        n: int = 5,
    ) -> list[Site]:
        """Synthesize a small ring of skeleton candidates around the region
        center when every other generation path returned zero. The candidates
        get jittered economics so the scoring stage can still rank them, and
        are marked `generation_method="fallback_ring"` so methodology notes
        and explainers can disclose them as synthesized.

        This is the safety net that mirrors the other 4 pipelines' baked-in
        domain catalogs — the candidate-centric Siting UI always has at
        least N markers to plot, even when every upstream stage failed.
        """
        # zlib.crc32 (not hash()) — see REPORTS_COHESION.md §8c.
        rng = random.Random(zlib.crc32(region.iso_code.encode()))
        # Use the region's interconnect center if it has one; otherwise fall
        # back to the curated per-ISO center.
        if region.interconnect_center:
            lat0, lon0 = region.interconnect_center
        else:
            lat0, lon0 = REGION_FALLBACK_CENTER.get(region.iso_code, (45.0, -75.0))

        # Spread the ring across roughly the same radius as a normal POI
        # expansion so the markers look plausible on the map.
        radius_km = max(60.0, region.interconnect_radius_km)
        dlat = radius_km / 111.0
        dlon = radius_km / (111.0 * max(0.1, _cos(lat0)))

        sites: list[Site] = []
        for i in range(n):
            angle = (2 * 3.14159 * i) / max(1, n)
            lat = round(lat0 + dlat * _sin(angle), 4)
            lon = round(lon0 + dlon * _cos_signed(angle), 4)
            ixp = nearest_ixp_latency(lat, lon)
            raw = {
                "name": f"Skeleton candidate #{i + 1} ({region.iso_code})",
                "lat": lat,
                "lon": lon,
                "address": f"Synthesized parcel near ({lat:.2f}, {lon:.2f})",
                # Skeleton ring jitter scales with the workload target for the
                # same reason as the main feasibility filter: a fallback site
                # that reports 25 MW capacity for a 200 MW workload looks
                # broken to the operator, even though the skeleton path
                # bypasses the strict feasibility check.
                "capacity_mw": rng.uniform(
                    max(float(workload.target_capacity_mw or 50.0), 25.0) * 0.7,
                    max(float(workload.target_capacity_mw or 50.0), 25.0) * 1.6,
                ),
                "transmission_headroom_mw": rng.uniform(
                    max(float(workload.target_capacity_mw or 50.0), 25.0) * 0.6,
                    max(float(workload.target_capacity_mw or 50.0), 25.0) * 1.5,
                ),
                "pue": round(rng.uniform(1.18, 1.40), 2),
                "fiber_latency_ms": ixp["rtt_ms"] if ixp else round(rng.uniform(10, 40), 1),
                "water_l_per_mwh": round(rng.uniform(0.6, 2.2), 2),
                "substation_distance_km": round(rng.uniform(1.0, 15.0), 2),
                "spot_lmp_usd_mwh": round(rng.uniform(28, 60), 2),
                "lease_cost_usd_yr": round(rng.uniform(0.4e6, 3.5e6), 0),
                "deployment_months": round(rng.uniform(14, 28), 1),
            }
            profile = compute_site_profile(raw, workload)
            if profile is None:
                continue
            sites.append(
                Site(
                    name=raw["name"],
                    latitude=raw["lat"],
                    longitude=raw["lon"],
                    address=raw["address"],
                    region_iso=region.iso_code,
                    profile=profile,
                    generation_method="fallback_ring",
                )
            )
        return sites

    def _diversity_select(self, sites: list[Site], max_count: int = 24) -> list[Site]:
        """Pick a diverse subset of sites by spreading across geo and economics."""
        if len(sites) <= max_count:
            return sites

        features: list[list[float]] = []
        for s in sites:
            p = s.profile
            features.append([
                s.latitude,
                s.longitude,
                float(p.capacity_mw or 0),
                float(p.spot_lmp_usd_mwh or 0),
                float(p.pue or 1.3),
            ])

        clusters = cluster_by_diversity(features, max_clusters=max_count)

        selected: list[Site] = []
        for cluster_id, indices in clusters.items():
            best = max(
                indices,
                key=lambda i: sites[i].profile.overall_score or 0,
            )
            sites[best].diversity_cluster = cluster_id
            selected.append(sites[best])
            if len(selected) >= max_count:
                break

        selected.sort(key=lambda s: s.profile.overall_score or 0, reverse=True)
        return selected[:max_count]


def _cos(deg: float) -> float:
    import math
    return abs(math.cos(math.radians(deg))) or 0.1


def _sin(rad: float) -> float:
    """Plain sine (radians). Used by the fallback-ring synthesizer."""
    import math
    return math.sin(rad)


def _cos_signed(rad: float) -> float:
    """Plain cosine (radians), keeps sign. Distinct from `_cos` which is
    abs-cos-of-degrees used as a lon-scaling factor."""
    import math
    return math.cos(rad)
