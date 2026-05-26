"""
Site Generation Agent — Stage 2 of the Skorpio pipeline. Wraps the
generator engine and supplements with Claude-designed candidate sites.
"""
from backend.agents.base_agent import BaseAgent
from backend.agents.grounding import GROUNDING_RULES
from backend.config import settings
from backend.grid.filters import compute_site_profile, passes_feasibility
from backend.grid.generator import SiteGenerationEngine, _country_for_region
from backend.models.site import Site, SiteLibrary
from backend.models.workload import Region, Workload
from backend.services._substations_generated import SUBSTATIONS_BY_OPERATOR
from backend.services.canadian_cities import parse_proximity_hint


# Canadian ISO code → list of OSM operator keys whose substations sit in
# that province. Used to ground Claude's site-design prompt with real
# substation coordinates instead of letting it invent points-of-interconnect.
_REGION_TO_OPERATORS: dict[str, list[str]] = {
    "CA-ON": ["hydro one", "toronto hydro", "alectra", "hydro ottawa"],
    "CA-QC": ["hydro-québec"],
    "CA-AB": ["altalink", "atco electric", "epcor"],
    "CA-BC": ["bc hydro", "fortisbc"],
    "CA-MB": ["manitoba hydro"],
    "CA-SK": ["saskpower"],
    "CA-NB": ["nb power"],
    "CA-NS": ["nova scotia power"],
    "CA-NL": ["newfoundland power", "nalcor"],
    "CA-PE": ["maritime electric"],
}


def _real_substation_anchors(
    iso_code: str,
    limit: int = 10,
    restrict_to_operator: str | None = None,
) -> list[dict]:
    """Pull up to N real OSM substations for the operators that serve this
    region. Sorted descending by voltage so the largest POIs are surfaced
    first. Empty list when we have no coverage for the region.

    When `restrict_to_operator` is set (e.g. "alectra"), narrow to ONLY that
    operator's substations — so a prompt that names a utility never gets
    anchors from a different LDC's territory. Falls back to the full
    region pool when the named operator isn't in SUBSTATIONS_BY_OPERATOR
    (rare; covered LDCs are in services/_substations_generated.py).
    """
    if restrict_to_operator:
        key = restrict_to_operator.strip().lower()
        narrowed = SUBSTATIONS_BY_OPERATOR.get(key, [])
        if narrowed:
            narrowed = list(narrowed)
            narrowed.sort(key=lambda s: float(s.get("voltage") or 0), reverse=True)
            return narrowed[:limit]
        # Fall through to region-wide if the operator isn't indexed.

    out: list[dict] = []
    for op in _REGION_TO_OPERATORS.get(iso_code, []):
        out.extend(SUBSTATIONS_BY_OPERATOR.get(op, []))
    out.sort(key=lambda s: float(s.get("voltage") or 0), reverse=True)
    return out[:limit]


SYSTEM_SITEGEN = """You are an expert real-estate / siting analyst with deep
expertise in transmission interconnect, fiber, water rights and zoning.
You propose plausible greenfield datacenter parcels for specific ISO regions.""" + GROUNDING_RULES


class SiteGenerationAgent(BaseAgent):
    def __init__(self, model: str | None = None):
        super().__init__(model=model)
        self.engine = SiteGenerationEngine()

    async def generate_candidates(
        self,
        region: Region,
        workload: Workload,
        n_sites: int = None,
        progress_callback=None,
    ) -> SiteLibrary:
        """Generate a feasible site library for the given region."""
        n = n_sites or settings.min_site_candidates

        # Run engine-based generation
        library = await self.engine.generate_candidates(
            region=region,
            workload=workload,
            n_sites=n,
            progress_callback=progress_callback,
        )

        # Supplement with Claude-designed sites if library is small
        if len(library.sites) < 8:
            if progress_callback:
                await progress_callback("Requesting AI-designed sites...", 70)
            claude_sites = await self._claude_generate(region, workload, n=12)
            library.sites.extend(claude_sites)
            library.total_passed_filters += len(claude_sites)
            self.logger.info(f"Claude added {len(claude_sites)} sites")

        # Re-rank by composite site score
        library.sites.sort(
            key=lambda s: s.profile.overall_score or 0, reverse=True
        )
        for i, s in enumerate(library.sites):
            s.rank = i + 1

        return library

    async def _claude_generate(
        self, region: Region, workload: Workload, n: int = 12
    ) -> list[Site]:
        """Ask Claude to generate novel candidate sites for a region."""
        country = _country_for_region(region.iso_code)
        admin_label = "province" if country == "Canada" else "state"
        states_str = ', '.join(region.states) if region.states else region.iso_code

        # Real interconnection anchors from OSM. Empty for US ISOs (we don't
        # ingest US OSM substations) — the prompt falls back to Claude's
        # general knowledge there, same as before.
        # When the user named a utility (workload.named_utility), narrow the
        # anchor pool to ONLY that utility's substations so every Claude-
        # designed candidate is grounded next to a real Alectra / Hydro Ottawa
        # / BC Hydro / etc. POI — keeps generated sites provably in-territory
        # for that LDC.
        anchors = _real_substation_anchors(
            region.iso_code,
            restrict_to_operator=workload.named_utility,
        )
        if anchors:
            anchor_lines = "\n".join(
                f"  - {a.get('name') or 'unnamed'} @ ({a['lat']:.3f}, {a['lon']:.3f}), "
                f"{int(float(a.get('voltage') or 0) / 1000)} kV"
                for a in anchors
            )
            anchor_block = (
                f"\nReal substations in this region (OpenStreetMap, "
                f"voltage ≥ 25 kV). Anchor each proposed site within ~25 km "
                f"of one of these points of interconnect:\n{anchor_lines}\n"
            )
        else:
            anchor_block = ""

        # City-proximity hint extracted from the user's prompt. Falls back
        # to no constraint when no known city is mentioned (we never let
        # Claude invent coordinates for unknown cities — §0).
        proximity = parse_proximity_hint(
            f"{workload.description or ''} {workload.normalized_name or ''}"
        )
        if proximity:
            proximity_block = (
                f"\nGEOGRAPHIC CONSTRAINT: the user named "
                f"{proximity['city']} explicitly (verified coords: "
                f"{proximity['lat']:.4f}, {proximity['lon']:.4f}). ALL "
                f"{n} proposed sites MUST lie within 50 km of this point. "
                f"Sites outside this radius will be discarded.\n"
            )
        else:
            proximity_block = ""

        # Capacity / headroom ranges scale with the workload target so a
        # 200 MW HPC build does not get a library of 20-80 MW parcels that
        # all fail the `capacity >= target * 0.85` feasibility floor.
        cap_target = max(float(workload.target_capacity_mw or 50.0), 25.0)
        cap_lo = int(round(cap_target * 0.85))
        cap_hi = int(round(cap_target * 1.50))
        hd_lo = int(round(cap_target * 0.85))
        hd_hi = int(round(cap_target * 1.60))

        prompt = f"""Region: {region.name} ({region.iso_code})
Country: {country}
Balancing authority: {region.balancing_authority}
{admin_label.capitalize()}(s): {states_str}
Workload: {workload.normalized_name} · target {workload.target_capacity_mw} MW
Workload description: {workload.description[:300]}
{anchor_block}{proximity_block}
Propose {n} plausible new greenfield datacenter parcels for this region. For each, provide:
- name: city + {admin_label} (string)
- lat: latitude (float)
- lon: longitude (float)
- address: short address (string)
- capacity_mw: nameplate capacity if built (float, {cap_lo}-{cap_hi} MW; sized for the {workload.target_capacity_mw} MW workload)
- transmission_headroom_mw: estimated POI headroom (float, {hd_lo}-{hd_hi} MW)
- pue: expected PUE 1.10-1.45 (float)
- fiber_latency_ms: round-trip to nearest IXP (float)
- water_l_per_mwh: cooling water draw (float)
- substation_distance_km: distance to nearest substation (float)
- spot_lmp_usd_mwh: current LMP estimate (float)
- deployment_months: time-to-power (float, 6-30)
- policy_notes: short note on permitting / interconnect queue (string)

Requirements:
- Geographic diversity within the region — sites must lie inside {country}
- Realistic coordinates that match the {admin_label}(s) listed above
- Plausible economics
- Avoid stacking in the same {admin_label.replace('state', 'county').replace('province', 'municipality')}

Return ONLY a JSON array of objects, no extra prose."""

        try:
            # 12 sites × 13 fields ≈ 1800-2050 tokens including JSON wrapping;
            # verbose policy_notes can push past 2048 and truncate the array
            # mid-object, breaking the parse. 2500 gives ~25% headroom.
            result = await self.ask_claude_json(
                system=SYSTEM_SITEGEN,
                prompt=prompt,
                max_tokens=2500,
            )
            if not isinstance(result, list):
                return []

            sites: list[Site] = []
            for raw in result:
                if not isinstance(raw, dict):
                    continue
                profile = compute_site_profile(raw, workload)
                if profile is None or not passes_feasibility(profile):
                    continue
                try:
                    sites.append(Site(
                        name=raw["name"],
                        latitude=float(raw["lat"]),
                        longitude=float(raw["lon"]),
                        address=raw.get("address"),
                        region_iso=region.iso_code,
                        profile=profile,
                        generation_method="claude_design",
                    ))
                except Exception:
                    continue
            return sites
        except Exception as e:
            self.logger.warning(f"Claude site generation failed: {e}")
            return []
