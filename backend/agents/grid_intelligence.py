"""
Grid Intelligence Agent — Stage 1 of the Skorpio pipeline.

Maps a natural-language workload spec to validated, operationally-feasible
ISO regions, enriched with topology + carbon + economics data.
"""
import asyncio
import re
from typing import Optional


# Utility name → province ISO code. Sources: OEB Yearbook of Electricity
# Distributors 2021 (Ontario LDCs), provincial regulator lists (AESO,
# BCUC, AUC, NL PUB, etc.). All mappings are public facts — a utility's
# operating province is published in its regulatory filings.
#
# Keys are lowercased substrings the parser scans for in the user's
# prompt. Add a new utility by checking its province from OEB / the
# province's energy regulator and pasting it here.
_UTILITY_TO_PROVINCE: dict[str, str] = {
    # Ontario LDCs (OEB Yearbook)
    "hydro one": "CA-ON",
    "toronto hydro": "CA-ON",
    "alectra": "CA-ON",
    "hydro ottawa": "CA-ON",
    "elexicon": "CA-ON",
    "enova power": "CA-ON",
    "essex power": "CA-ON",
    "festival hydro": "CA-ON",
    "halton hills hydro": "CA-ON",
    "hydro hawkesbury": "CA-ON",
    "kitchener-wilmot hydro": "CA-ON",
    "london hydro": "CA-ON",
    "milton hydro": "CA-ON",
    "newmarket-tay power": "CA-ON",
    "niagara peninsula energy": "CA-ON",
    "north bay hydro": "CA-ON",
    "oakville hydro": "CA-ON",
    "oshawa power": "CA-ON",
    "peterborough distribution": "CA-ON",
    "sudbury hydro": "CA-ON",
    "synergy north": "CA-ON",
    "thunder bay hydro": "CA-ON",
    "utilities kingston": "CA-ON",
    "waterloo north hydro": "CA-ON",
    "welland hydro": "CA-ON",

    # Quebec
    "hydro-québec": "CA-QC",
    "hydro quebec": "CA-QC",
    "hydroquébec": "CA-QC",
    "hydroquebec": "CA-QC",

    # Alberta
    "atco electric": "CA-AB",
    "epcor": "CA-AB",
    "enmax": "CA-AB",
    "altalink": "CA-AB",
    "fortisalberta": "CA-AB",

    # BC
    "bc hydro": "CA-BC",
    "fortisbc": "CA-BC",

    # Manitoba / Saskatchewan / NB / NS / NL / PEI
    "manitoba hydro": "CA-MB",
    "saskpower": "CA-SK",
    "nb power": "CA-NB",
    "ns power": "CA-NS",
    "nova scotia power": "CA-NS",
    "emera": "CA-NS",
    "newfoundland power": "CA-NL",
    "newfoundland and labrador hydro": "CA-NL",
    "nl hydro": "CA-NL",
    "nalcor": "CA-NL",
    "maritime electric": "CA-PE",
}


def _detect_utilities(query: str) -> list[tuple[str, str]]:
    """Scan the prompt for any known utility name. Returns
    [(utility_name, province_iso_code)] for every match. Longer names
    match first (so "Hydro Ottawa" beats a stray "Hydro" substring).
    Empty list when no utility is mentioned.
    """
    if not query:
        return []
    lower = query.lower()
    hits: list[tuple[str, str]] = []
    seen_provinces: set[str] = set()
    for name in sorted(_UTILITY_TO_PROVINCE.keys(), key=len, reverse=True):
        if re.search(r"\b" + re.escape(name) + r"\b", lower):
            province = _UTILITY_TO_PROVINCE[name]
            if province in seen_provinces:
                continue
            seen_provinces.add(province)
            hits.append((name, province))
    return hits

from backend.agents.base_agent import BaseAgent
from backend.models.workload import Workload, Region, RegionEvidence, BalancingAuthority
from backend.services.eia import eia_client
from backend.services.iso_lmp import iso_client
from backend.services.openei import openei_client
from backend.services.electricitymaps import electricitymaps_client
from backend.services.nrel import nrel_client
from backend.services.topology_graph import get_topology_graph
from backend.agents.grounding import GROUNDING_RULES
from backend.config import settings


SYSTEM_GRID = """You are an expert grid operator and energy markets analyst.
Your role is to parse compute-workload placement requests and identify the most
suitable regions. You are Canada-first: prefer Canadian provincial grids
(IESO/Ontario, AESO/Alberta, Hydro-Québec, BC Hydro, Manitoba Hydro,
SaskPower, NB Power, NS Power, NL Hydro, Maritime Electric/PEI) and use
ISO 3166-2 codes prefixed with "CA-" (e.g. CA-ON, CA-QC, CA-AB, CA-BC,
CA-MB, CA-SK, CA-NB, CA-NS, CA-NL, CA-PE).

Reach for US ISOs (PJM, ERCOT, CAISO, MISO, SPP) only when the query
explicitly requests US placement.

Canadian context to keep in mind:
  - Québec: ~94% hydro, near-zero carbon (~2 gCO₂/kWh), low industrial
    rates, large surplus capacity, exports heavily to NY/NE.
  - Ontario: ~55% nuclear + 24% hydro (~30 gCO₂/kWh), tight headroom
    around the GTA, strong fibre to Toronto.
  - Alberta: gas-heavy (~550 gCO₂/kWh) but cheap industrial power and
    fast permitting; rapid wind buildout.
  - BC: ~92% hydro (~15 gCO₂/kWh), Site C adds capacity through 2025.
  - Manitoba: 97% hydro, very low carbon, strong DC interties south.

Always base recommendations on observable grid state. Be precise with
ISO/zone codes, balancing authorities, and units.""" + GROUNDING_RULES


class GridIntelligenceAgent(BaseAgent):
    async def discover_regions(
        self,
        workload_query: str,
        progress_callback=None,
    ) -> Workload:
        """
        Full workload → region pipeline.
        Returns a Workload object with ranked, annotated regions.
        """
        self.logger.info(f"Starting grid analysis: {workload_query}")

        # Step 1: Parse and normalise the workload query with Claude
        if progress_callback:
            await progress_callback("Parsing workload spec with AI...", 5)
        workload = await self._parse_workload_query(workload_query)
        self.logger.info(f"[DEBUG] Normalized name: '{workload.normalized_name}'")
        self.logger.info(f"[DEBUG] Claude candidate ISOs: {workload.candidate_iso_codes}")

        # Step 2: Query OpenEI for region-utility associations
        # (No progress line — coalesced with the region-identification line
        # below per REPORTS_COHESION.md §11.)
        seeded_codes = workload.candidate_iso_codes or [
            "CA-ON", "CA-QC", "CA-AB", "CA-BC", "CA-MB",
        ]
        association_tasks = [openei_client.utilities_for_region(c) for c in seeded_codes]
        associations = await asyncio.gather(*association_tasks, return_exceptions=True)
        flat_assocs: list[dict] = []
        for code, group in zip(seeded_codes, associations):
            if isinstance(group, list):
                for a in group:
                    a["iso_code"] = code
                    flat_assocs.append(a)
        self.logger.info(f"[DEBUG] OpenEI returned {len(flat_assocs)} associations")

        # Step 3: Get Claude to identify top suitable regions
        if progress_callback:
            await progress_callback(
                f"Identifying suitable regions from {len(flat_assocs)} region-utility associations...",
                25,
            )
        region_seed_list = await self._identify_suitable_regions(workload, flat_assocs)
        self.logger.info(f"[DEBUG] Claude selected {len(region_seed_list)} regions")

        # Step 4: Fetch ISO topology + Electricity Maps data for each candidate region
        if progress_callback:
            await progress_callback("Fetching grid telemetry and carbon snapshots...", 35)
        regions = await self._enrich_regions(region_seed_list, workload)
        self.logger.info(f"[DEBUG] Enrichment succeeded for {len(regions)}/{len(region_seed_list)} regions")

        # Step 5: Score and rank
        regions = self._rank_regions(regions)
        workload.regions = regions[: settings.max_regions]

        # Step 6: Generate workload context summary (no progress line —
        # the orchestrator emits the "Identified N regions" line right
        # after this method returns, which is the meaningful stage-end signal).
        workload.context_summary = await self._generate_workload_summary(workload)

        self.logger.info(
            f"Grid analysis complete: {len(workload.regions)} regions identified"
        )
        return workload

    # ------------------------------------------------------------------ #
    #  Private helpers                                                    #
    # ------------------------------------------------------------------ #

    async def _parse_workload_query(self, query: str) -> Workload:
        """Use Claude to normalise the workload spec and extract context."""
        result = await self.ask_claude_json(
            system=SYSTEM_GRID,
            prompt=f"""Parse this compute-workload placement query and return a JSON object with:
- normalized_name: short label (e.g. "Training cluster · Q3 expansion")
- workload_class: one of "training", "inference", "edge-pop", "colocation", or null
- target_capacity_mw: number (default 42 if unclear)
- target_latency_ms: number or null (e.g. 35 for inference)
- max_carbon_g_co2_kwh: number or null
- description: 2-3 sentence operational description
- candidate_iso_codes: list of up to 5 ISO/province codes. Prefer Canadian
  codes (CA-ON, CA-QC, CA-AB, CA-BC, CA-MB, CA-SK, CA-NB, CA-NS, CA-NL,
  CA-PE). US RTO codes (PJM-W, PJM-E, ERCOT, CAISO, MISO, SPP, NYISO,
  ISO-NE) only when the query explicitly asks for US placement.
- geographic_constraint: list of ISO/province codes the user explicitly
  required. Populate this when the prompt names a country, province, or
  state as a hard filter (e.g. "in Quebec" → ["CA-QC"]; "Alberta with
  latency to Calgary" → ["CA-AB"]; "Ontario only" → ["CA-ON"]). When
  multiple regions are listed ("Quebec or Manitoba"), include all. Leave
  this list EMPTY when the prompt is geographically open-ended
  ("anywhere in Canada", "any low-carbon region", no place mentioned).
  When set, this acts as a hard filter — only regions in this list will
  be returned, even if Claude thinks others are better fits.

Workload query: "{query}"

Respond ONLY with the JSON object.""",
            max_tokens=1024,
        )
        # Deterministic utility-name backstop. Claude's geographic_constraint
        # parsing can miss less-famous utilities; a public utility→province
        # lookup table (sourced from OEB Yearbook + provincial regulators)
        # ensures e.g. "Alectra" → CA-ON and "BC Hydro" → CA-BC always lands
        # in the constraint set. The detected utility name is also recorded
        # in the description so downstream agents can surface it.
        constraint = list(result.get("geographic_constraint", []) or [])
        utility_hits = _detect_utilities(query)
        for _name, prov in utility_hits:
            if prov not in (c.upper() for c in constraint):
                constraint.append(prov)

        utility_note = ""
        if utility_hits:
            utility_note = (
                " Utility mentioned in prompt: "
                + ", ".join(name.title() for name, _ in utility_hits)
                + "."
            )

        # First detected utility wins. Lowercased to match the OSM operator
        # keys in services._substations_generated.SUBSTATIONS_BY_OPERATOR
        # (which is keyed by the raw_operator string from OSM, lowercased).
        # The site generator uses this to narrow seed cities + substation
        # anchors to the operator's actual territory.
        named_utility = utility_hits[0][0].lower() if utility_hits else None

        return Workload(
            query=query,
            normalized_name=result.get("normalized_name", query),
            workload_class=result.get("workload_class"),
            target_capacity_mw=float(result.get("target_capacity_mw") or 42),
            target_latency_ms=result.get("target_latency_ms"),
            max_carbon_g_co2_kwh=result.get("max_carbon_g_co2_kwh"),
            description=(result.get("description", "") or "") + utility_note,
            candidate_iso_codes=result.get("candidate_iso_codes", []),
            geographic_constraint=constraint,
            named_utility=named_utility,
        )

    async def _identify_suitable_regions(
        self, workload: Workload, association_list: list[dict]
    ) -> list[dict]:
        """Ask Claude to select the top suitable regions from combined evidence."""
        association_codes = [a["iso_code"] for a in association_list[:30] if a.get("iso_code")]
        all_codes = list(dict.fromkeys(workload.candidate_iso_codes + association_codes))

        if not all_codes:
            all_codes = workload.candidate_iso_codes or []

        # Hard geographic filter: when the user explicitly named a region in
        # their prompt, narrow the candidate pool to ONLY those codes before
        # we ask Claude to pick. Claude was previously ignoring soft hints
        # like "in Quebec" and returning whichever US RTO it thought scored
        # best; the constraint makes the filter a hard precondition.
        constraint = [c.strip().upper() for c in workload.geographic_constraint if c]
        if constraint:
            all_codes = [c for c in all_codes if c.upper() in constraint] or list(constraint)

        constraint_block = (
            f"\nHARD GEOGRAPHIC FILTER: the user explicitly requires placement "
            f"in {', '.join(constraint)}. Return regions ONLY from this set; "
            f"reject every other candidate even if it would score better.\n"
            if constraint else ""
        )
        priority_line = (
            "3. Match the user's stated geographic intent (Canadian provinces "
            "for Canadian queries; US RTOs only when the prompt explicitly "
            "names US placement)"
        )

        prompt = f"""Workload: {workload.normalized_name}
Description: {workload.description}
Target capacity: {workload.target_capacity_mw} MW
Target latency: {workload.target_latency_ms} ms (None = flexible)
Max carbon: {workload.max_carbon_g_co2_kwh} gCO₂/kWh (None = flexible)
{constraint_block}
Candidate ISO regions from utility / RTO data: {', '.join(all_codes[:30])}

Select up to {settings.max_regions} of the best-fit regions for this workload.
Prioritise regions that:
1. Have transmission headroom for the target capacity at a known POI
2. Carbon-intensity profile fits the workload's caps
{priority_line}
4. Diverse geography (avoid stacking all candidates in one BA)

Return a JSON array of objects, each with:
- iso_code: short ISO code (string, e.g. "CA-QC", "CA-ON", "PJM-W")
- name: full region name (string)
- balancing_authority: BA code (string, e.g. "HQT" for Hydro-Québec, "IESO" for Ontario, "PJM")
- states: list of state / province codes the region covers (e.g. ["QC"], ["ON"], ["OH", "PA"])
- rationale: 1-2 sentence operational rationale (string)
- headroom_score: float 0-1
- carbon_score: float 0-1
- economics_score: float 0-1

Example:
[{{"iso_code": "CA-QC", "name": "Hydro-Québec", "balancing_authority": "HQT", "states": ["QC"], "rationale": "...", "headroom_score": 0.9, "carbon_score": 0.98, "economics_score": 0.85}}]"""

        try:
            regions_raw = await self.ask_claude_json(
                system=SYSTEM_GRID,
                prompt=prompt,
                max_tokens=2048,
            )
            if isinstance(regions_raw, list) and regions_raw:
                # Belt-and-braces: even with the hard-filter in the prompt,
                # strip anything Claude returned that's outside the constraint.
                if constraint:
                    regions_raw = [
                        r for r in regions_raw
                        if str(r.get("iso_code", "")).upper() in constraint
                    ]
                    if not regions_raw:
                        # Claude returned only out-of-constraint regions —
                        # synthesise a stub for each constraint code so the
                        # pipeline doesn't dead-end. Downstream enrichment
                        # will fill in the real telemetry.
                        regions_raw = [
                            {
                                "iso_code": code,
                                "name": code,
                                "balancing_authority": code.split("-")[-1],
                                "states": [code.split("-")[-1]] if "-" in code else [],
                                "rationale": (
                                    f"Region forced by explicit user constraint "
                                    f"({code}); enrichment will supply telemetry."
                                ),
                                "headroom_score": 0.5,
                                "carbon_score": 0.5,
                                "economics_score": 0.5,
                            }
                            for code in constraint
                        ]
                return regions_raw
        except Exception as e:
            self.logger.warning(f"Claude region identification failed: {e}")

        # Fallback 1: use top association codes (post-filter by constraint
        # so a Canadian-constrained query doesn't get back Texas utilities).
        if association_list:
            assocs = [
                {
                    "iso_code": a["iso_code"],
                    "name": a.get("utility_name", a["iso_code"]),
                    "balancing_authority": a["iso_code"].split("-")[0],
                    "states": [],
                    "rationale": f"Surfaced via OpenEI (score: {a['score']:.2f})",
                    "headroom_score": min(a["score"] * 1.5, 1.0),
                    "carbon_score": a["score"],
                    "economics_score": a["score"],
                }
                for a in association_list[: settings.max_regions * 3]
                if a.get("iso_code")
            ]
            if constraint:
                assocs = [a for a in assocs if a["iso_code"].upper() in constraint]
            if assocs:
                return assocs[: settings.max_regions]

        # Fallback 2: ask Claude without database results. Honour the
        # constraint here too — the previous prompt explicitly said "US
        # power markets" which broke any Canadian query that fell through
        # to this branch.
        self.logger.info("No database results — using Claude knowledge fallback")
        fallback_constraint = (
            f"\nHARD GEOGRAPHIC FILTER: the user explicitly requires placement "
            f"in {', '.join(constraint)}. Return regions ONLY from this set.\n"
            if constraint else ""
        )
        market_scope = (
            "Canadian provincial grids (IESO/Ontario, AESO/Alberta, "
            "Hydro-Québec, BC Hydro, Manitoba Hydro) first; US RTOs only "
            "when the prompt explicitly asks for US placement"
        )
        try:
            fallback_prompt = f"""Workload: {workload.normalized_name}
Description: {workload.description}
{fallback_constraint}
No database results are available. Using your knowledge of {market_scope}, identify up to {settings.max_regions} well-suited regions for this workload.

Return a JSON array of objects with: iso_code, name, balancing_authority, states, rationale, headroom_score, carbon_score, economics_score (all scores 0-1)."""
            fallback_raw = await self.ask_claude_json(
                system=SYSTEM_GRID,
                prompt=fallback_prompt,
                max_tokens=2048,
            )
            if isinstance(fallback_raw, list) and fallback_raw:
                if constraint:
                    fallback_raw = [
                        r for r in fallback_raw
                        if str(r.get("iso_code", "")).upper() in constraint
                    ]
                if fallback_raw:
                    return fallback_raw
        except Exception as e:
            self.logger.warning(f"Claude fallback region identification failed: {e}")

        return []

    async def _enrich_regions(
        self, region_list: list[dict], workload: Workload
    ) -> list[Region]:
        """Fetch topology + carbon + utility-rate data for each region in parallel."""
        tasks = [self._enrich_single_region(r, workload) for r in region_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        regions = []
        for r in results:
            if isinstance(r, Exception):
                self.logger.warning(f"Region enrichment error: {r}")
            elif r is not None:
                regions.append(r)
        return regions

    async def _enrich_single_region(
        self, region_info: dict, workload: Workload
    ) -> Optional[Region]:
        iso_code = region_info.get("iso_code", "")
        if not iso_code:
            return None

        # ── Fetch ISO topology (zones, substations)
        topology = await iso_client.get_topology(iso_code)

        # ── Determine the load zone and fetch a recent LMP slice
        zone = ""
        if topology:
            zone = iso_client.extract_load_zone(topology)
        lmp_rows = await iso_client.get_zone_lmp(iso_code, zone) if zone else []
        authorities_raw = iso_client.extract_authorities(topology or {})

        # ── Fetch carbon intensity snapshot
        zone_for_em = region_info.get("electricitymaps_zone") or iso_code.split("-")[0]
        snapshot_path: Optional[str] = await electricitymaps_client.get_snapshot(zone_for_em)

        # ── Fetch a sample utility rate at the region centroid (if known)
        rate_summary: Optional[dict] = None
        states = region_info.get("states", [])
        if states:
            try:
                rate_summary = await nrel_client.utility_rates(
                    *_state_centroid(states[0])
                )
            except Exception:
                rate_summary = None

        authorities = [
            BalancingAuthority(
                ba_code=a.get("operator", region_info.get("balancing_authority", iso_code)),
                name=a.get("name", ""),
                operator=a.get("operator", ""),
            )
            for a in authorities_raw
        ]

        evidence = [
            RegionEvidence(
                source="Claude/OpenEI",
                score=float(region_info.get("headroom_score", 0.5)),
                description=region_info.get("rationale", ""),
            )
        ]
        if lmp_rows:
            avg_lmp = sum(r.get("lmp_usd_mwh") or 0 for r in lmp_rows) / max(len(lmp_rows), 1)
            evidence.append(RegionEvidence(
                source=f"{iso_code} LMP feed",
                score=min(1.0, max(0.0, 1.0 - avg_lmp / 100.0)),
                description=f"Average LMP last hour: ${avg_lmp:.2f}/MWh across {len(lmp_rows)} samples.",
            ))

        region = Region(
            iso_code=iso_code,
            name=region_info.get("name", iso_code),
            balancing_authority=region_info.get("balancing_authority", iso_code.split("-")[0]),
            states=region_info.get("states", []),
            topology_id=zone or None,
            preferred_zone=zone or None,
            grid_telemetry_path=snapshot_path,
            timezone=_iso_timezone(iso_code),
            function_summary=region_info.get("rationale", "")[:500],
            authorities=authorities[:5],
            evidence=evidence,
            headroom_score=float(region_info.get("headroom_score", 0.5)),
            carbon_score=float(region_info.get("carbon_score", 0.5)),
            economics_score=float(region_info.get("economics_score", 0.5)),
        )
        region.overall_score = (
            region.headroom_score + region.carbon_score + region.economics_score
        ) / 3.0

        # Build {nodes, edges} graph (best-effort, non-blocking on failure)
        try:
            region.topology_graph = await get_topology_graph(iso_code, zone)
        except Exception as e:
            self.logger.warning(f"Topology graph fetch failed for {iso_code}: {e}")

        return region

    def _rank_regions(self, regions: list[Region]) -> list[Region]:
        """Rank regions by overall_score descending."""
        return sorted(regions, key=lambda r: r.overall_score, reverse=True)

    async def _generate_workload_summary(self, workload: Workload) -> str:
        """Generate a concise workload + region context summary."""
        region_bullets = "\n".join(
            f"- {r.iso_code} ({r.name}): {r.function_summary[:150]}"
            for r in workload.regions
        )
        summary = await self.ask_claude(
            system=SYSTEM_GRID,
            prompt=f"""Write a concise (3-4 paragraph) operational overview of placing
{workload.normalized_name} for a siting-plan report. Include:
1. Workload profile and operational sensitivity (load shape, latency, redundancy)
2. Current market context (LMP volatility, transmission queue depth)
3. Why the following regions were selected:
{region_bullets}

Be precise, cite mechanism not just names. Write for a senior grid-operations audience.""",
            max_tokens=1024,
        )
        return summary


# ── Static helpers ───────────────────────────────────────────────────────────

def _state_centroid(state_code: str) -> tuple[float, float]:
    """Rough geographic centroid for a US state (best-effort)."""
    centroids = {
        "OH": (40.42, -82.91), "PA": (40.59, -77.21), "VA": (37.43, -78.66),
        "TX": (31.05, -97.56), "OR": (44.93, -120.55), "NV": (39.32, -116.63),
        "WA": (47.40, -120.41), "IA": (42.07, -93.49), "OK": (35.30, -97.27),
        "KS": (38.52, -98.38),
    }
    return centroids.get(state_code.upper(), (39.83, -98.58))   # default: US centroid


def _iso_timezone(iso_code: str) -> str:
    return {
        "PJM-W": "America/New_York",
        "PJM-E": "America/New_York",
        "NYISO": "America/New_York",
        "ISO-NE": "America/New_York",
        "MISO": "America/Chicago",
        "SPP":  "America/Chicago",
        "ERCOT": "America/Chicago",
        "CAISO": "America/Los_Angeles",
    }.get(iso_code, "America/New_York")
