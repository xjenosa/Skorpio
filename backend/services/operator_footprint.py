"""
Canadian datacenter operator footprint catalog for the Expansion Planner.

Calibrated from public sources:
  - Operator company pages, press releases, annual reports
  - DC Byte / Cushman & Wakefield Canadian DC market reports 2023–2024
  - CRTC Network Resiliency Service Provider data (fiber count proxy)
  - Provincial grid zone assignments (ElectricityMaps)

Site coordinates are real (verifiable on OpenStreetMap / operator maps).
Per-site MW and headroom are approximated and rounded.

Live integration: `enrich_with_live_carbon()` adds current
ElectricityMaps gCO₂/kWh per zone. If the API key is missing or the call
fails, sites keep their baked-in `avg_carbon_g_kwh` value.
"""
from __future__ import annotations

import asyncio

from backend.models.expansion import ExistingSite, OperatorFootprint
from backend.services.electricitymaps import electricitymaps_client
from backend.utils.logger import get_logger

logger = get_logger(__name__)


# ── Catalogs ──────────────────────────────────────────────────────────── #


_ESTRUXTURE: list[ExistingSite] = [
    ExistingSite(
        site_id="ESTR-MTL-1", name="eStruxture MTL-1 Saint-Bruno",
        operator="eStruxture", city="Montréal", province="QC",
        latitude=45.527, longitude=-73.378,
        year_commissioned=2018,
        current_capacity_mw=60.0, contracted_mw=52.0,
        plot_acres=14, transformer_headroom_mw=18.0,
        fiber_providers=["Bell", "Cogeco", "Rogers", "Telus"],
        cooling="hybrid", water_available_l_s=22.0,
        grid_zone="CA-QC", avg_carbon_g_kwh=30.0, pue=1.22,
        notes="Flagship Quebec campus, Hydro-Québec 315 kV feed.",
    ),
    ExistingSite(
        site_id="ESTR-MTL-2", name="eStruxture MTL-2 Pointe-Claire",
        operator="eStruxture", city="Pointe-Claire", province="QC",
        latitude=45.451, longitude=-73.808,
        year_commissioned=2020,
        current_capacity_mw=40.0, contracted_mw=36.0,
        plot_acres=8, transformer_headroom_mw=8.0,
        fiber_providers=["Bell", "Cogeco", "Telus"],
        cooling="air", water_available_l_s=0.0,
        grid_zone="CA-QC", avg_carbon_g_kwh=30.0, pue=1.28,
        notes="Tier-III west-island site, limited plot.",
    ),
    ExistingSite(
        site_id="ESTR-TOR-1", name="eStruxture TOR-1 Vaughan",
        operator="eStruxture", city="Vaughan", province="ON",
        latitude=43.836, longitude=-79.539,
        year_commissioned=2022,
        current_capacity_mw=15.0, contracted_mw=10.0,
        plot_acres=12, transformer_headroom_mw=10.0,
        fiber_providers=["Bell", "Rogers", "Cogeco"],
        cooling="hybrid", water_available_l_s=12.0,
        grid_zone="CA-ON", avg_carbon_g_kwh=130.0, pue=1.30,
        notes="GTA expansion runway, Hydro One 230 kV.",
    ),
]


_COLOGIX: list[ExistingSite] = [
    ExistingSite(
        site_id="COLO-MTL-7", name="Cologix MTL7",
        operator="Cologix", city="Montréal", province="QC",
        latitude=45.498, longitude=-73.567,
        year_commissioned=2019,
        current_capacity_mw=24.0, contracted_mw=22.0,
        plot_acres=4, transformer_headroom_mw=6.0,
        fiber_providers=["Bell", "Cogeco", "Telus", "Zayo"],
        cooling="air", water_available_l_s=0.0,
        grid_zone="CA-QC", avg_carbon_g_kwh=30.0, pue=1.31,
        notes="High-density interconnection hub.",
    ),
    ExistingSite(
        site_id="COLO-TOR-1", name="Cologix TOR1",
        operator="Cologix", city="Toronto", province="ON",
        latitude=43.643, longitude=-79.380,
        year_commissioned=2017,
        current_capacity_mw=18.0, contracted_mw=17.0,
        plot_acres=2, transformer_headroom_mw=1.0,
        fiber_providers=["Bell", "Rogers", "Telus", "Zayo"],
        cooling="air", water_available_l_s=0.0,
        grid_zone="CA-ON", avg_carbon_g_kwh=130.0, pue=1.36,
        notes="Downtown Toronto carrier hotel, minimal expansion plot.",
    ),
    ExistingSite(
        site_id="COLO-VAN-2", name="Cologix VAN2",
        operator="Cologix", city="Vancouver", province="BC",
        latitude=49.275, longitude=-123.106,
        year_commissioned=2020,
        current_capacity_mw=20.0, contracted_mw=17.0,
        plot_acres=3, transformer_headroom_mw=4.0,
        fiber_providers=["Telus", "Bell", "Rogers"],
        cooling="free_air", water_available_l_s=0.0,
        grid_zone="CA-BC", avg_carbon_g_kwh=35.0, pue=1.18,
        notes="BC Hydro feed, free-air cooling much of the year.",
    ),
    # Cologix TOR4 — Markham. Name, address, and capacity disclosed by
    # Cologix on cologix.com/data-centers/toronto/. Coordinates from OSM
    # Nominatim geocode of the cited address (105 Clegg Road, Buttonville).
    #
    # Note: contracted_mw / plot_acres / transformer_headroom_mw / fiber /
    # water / pue are NOT publicly disclosed at the site level. They match
    # the catalog's documented "approximated and rounded" baseline (see
    # module docstring) and should not be quoted as authoritative.
    #
    # Cologix TOR5 also exists at 105 Clegg Road but its capacity is not
    # publicly disclosed; rather than fabricate a number to add a row,
    # we leave TOR5 off the catalog. §0 compliance — accept the gap.
    ExistingSite(
        site_id="COLO-TOR-4", name="Cologix TOR4",
        operator="Cologix", city="Markham", province="ON",
        latitude=43.8508, longitude=-79.3427,
        year_commissioned=2022,
        current_capacity_mw=11.0, contracted_mw=8.0,
        plot_acres=5, transformer_headroom_mw=3.0,
        fiber_providers=["Bell", "Rogers", "Cogeco", "Telus"],
        cooling="hybrid", water_available_l_s=6.0,
        grid_zone="CA-ON", avg_carbon_g_kwh=130.0, pue=1.30,
        notes="Purpose-built Scalelogix 11 MW facility (capacity disclosed by Cologix); 105 Clegg Road, Building B, Markham. Cologix TOR5 also exists at this campus but capacity is undisclosed, so it is omitted from the catalog per §0 (no fabrication).",
    ),
]


_HYPERION: list[ExistingSite] = [
    ExistingSite(
        site_id="HYPN-EDM-1", name="Hyperion EDM-1 Beaver County",
        operator="Hyperion", city="Beaver County", province="AB",
        latitude=53.241, longitude=-112.821,
        year_commissioned=2024,
        current_capacity_mw=120.0, contracted_mw=60.0,
        plot_acres=420, transformer_headroom_mw=80.0,
        fiber_providers=["Telus", "Bell", "Shaw"],
        cooling="hybrid", water_available_l_s=45.0,
        grid_zone="CA-AB", avg_carbon_g_kwh=380.0, pue=1.25,
        notes="AI-first hyperscale, AESO 240 kV; coal-retirement transition.",
    ),
]


_QSCALE: list[ExistingSite] = [
    ExistingSite(
        site_id="QSC-LEV-1", name="Q-Scale Q01 Lévis",
        operator="Q-Scale", city="Lévis", province="QC",
        latitude=46.776, longitude=-71.190,
        year_commissioned=2023,
        current_capacity_mw=15.0, contracted_mw=12.0,
        plot_acres=22, transformer_headroom_mw=27.0,
        fiber_providers=["Cogeco", "Bell", "Videotron"],
        cooling="liquid_immersion", water_available_l_s=10.0,
        grid_zone="CA-QC", avg_carbon_g_kwh=30.0, pue=1.15,
        notes="AI training campus, waste-heat district loop.",
    ),
]


_EQUINIX: list[ExistingSite] = [
    ExistingSite(
        site_id="EQ-TOR-1", name="Equinix TR1 Toronto",
        operator="Equinix", city="Toronto", province="ON",
        latitude=43.671, longitude=-79.487,
        year_commissioned=2010,
        current_capacity_mw=10.0, contracted_mw=10.0,
        plot_acres=2, transformer_headroom_mw=2.0,
        fiber_providers=["Bell", "Rogers", "Cogeco", "Telus", "Zayo"],
        cooling="air", water_available_l_s=0.0,
        grid_zone="CA-ON", avg_carbon_g_kwh=130.0, pue=1.40,
        notes="Carrier-dense IBX; small plot, vertical build only.",
    ),
    ExistingSite(
        site_id="EQ-TOR-3", name="Equinix TR3 Brampton",
        operator="Equinix", city="Brampton", province="ON",
        latitude=43.733, longitude=-79.762,
        year_commissioned=2019,
        current_capacity_mw=15.0, contracted_mw=11.0,
        plot_acres=10, transformer_headroom_mw=12.0,
        fiber_providers=["Bell", "Rogers", "Cogeco"],
        cooling="hybrid", water_available_l_s=8.0,
        grid_zone="CA-ON", avg_carbon_g_kwh=130.0, pue=1.30,
        notes="Built-for-cloud campus with expansion runway.",
    ),
]


_REGISTRY: dict[str, list[ExistingSite]] = {
    "estruxture": _ESTRUXTURE,
    "cologix": _COLOGIX,
    "hyperion": _HYPERION,
    "q-scale": _QSCALE,
    "qscale": _QSCALE,
    "equinix": _EQUINIX,
}


# ── City → (operator, site_id) reverse index ──────────────────────────── #
#
# Built once at import from the catalogs above. Used by ExpansionWorkloadAgent
# to ground city-name parsing in observed data: when the prompt names a city
# (e.g. "our Vaughan datacenter"), we look up which operator actually owns a
# site there instead of letting the LLM guess from province affinity. Per §0
# of REPORTS_COHESION.md the routing is data-derived — no fabrication, no LLM
# heuristic. City keys are lowercased and accent-folded so "Montréal" and
# "Montreal" both match.

def _fold(s: str) -> str:
    """Lowercase + strip + drop common French accents for city matching."""
    return (
        (s or "")
        .strip()
        .lower()
        .replace("é", "e").replace("è", "e").replace("ê", "e")
        .replace("à", "a").replace("â", "a")
        .replace("ô", "o").replace("ç", "c")
    )


def _build_city_index() -> dict[str, list[tuple[str, str]]]:
    idx: dict[str, list[tuple[str, str]]] = {}
    for sites in (_ESTRUXTURE, _COLOGIX, _HYPERION, _QSCALE, _EQUINIX):
        for s in sites:
            idx.setdefault(_fold(s.city), []).append((s.operator, s.site_id))
    return idx


_CITY_TO_SITES: dict[str, list[tuple[str, str]]] = _build_city_index()


def cities_in_catalog() -> list[str]:
    """Distinct city names present in the operator footprint catalog.
    Returned with original (display) casing, sorted longest-first so prompt
    matching prefers "Pointe-Claire" over "Claire" when both happen to appear."""
    seen: dict[str, str] = {}
    for sites in (_ESTRUXTURE, _COLOGIX, _HYPERION, _QSCALE, _EQUINIX):
        for s in sites:
            key = _fold(s.city)
            seen.setdefault(key, s.city)
    return sorted(seen.values(), key=lambda c: (-len(c), c))


def lookup_city(city: str) -> list[tuple[str, str]]:
    """Return [(operator, site_id), …] for sites in the named city. Empty
    list when the city isn't in any operator's footprint."""
    return list(_CITY_TO_SITES.get(_fold(city), []))


def list_supported_operators() -> list[dict]:
    out = []
    for key, sites in [
        ("estruxture", _ESTRUXTURE), ("cologix", _COLOGIX),
        ("hyperion", _HYPERION), ("q-scale", _QSCALE),
        ("equinix", _EQUINIX),
    ]:
        out.append({
            "key": key,
            "name": sites[0].operator,
            "site_count": len(sites),
            "total_mw": sum(s.current_capacity_mw for s in sites),
            "provinces": sorted({s.province for s in sites}),
        })
    return out


def load_footprint(operator: str) -> OperatorFootprint:
    """Resolve the operator's footprint. Returns synthesized=True for unknowns."""
    key = (operator or "").strip().lower().replace(" ", "")
    sites = _REGISTRY.get(key)
    if not sites:
        # Synthesize a generic 2-site footprint so the pipeline never bombs.
        sites = _synthesize_generic(operator or "Unknown Operator")
        return OperatorFootprint(
            operator=operator or "Unknown",
            province=sites[0].province if sites else "ON",
            sites=sites,
            total_current_capacity_mw=sum(s.current_capacity_mw for s in sites),
            is_synthesized=True,
            sources=["synthesized from province defaults; operator not in catalog"],
        )
    province_counts: dict[str, int] = {}
    for s in sites:
        province_counts[s.province] = province_counts.get(s.province, 0) + 1
    primary_prov = max(province_counts.items(), key=lambda kv: kv[1])[0]
    return OperatorFootprint(
        operator=sites[0].operator,
        province=primary_prov,
        sites=list(sites),
        total_current_capacity_mw=sum(s.current_capacity_mw for s in sites),
        is_synthesized=False,
        sources=[
            "Cushman & Wakefield Canada DC Market 2024",
            "DC Byte Canadian DC Insights 2024",
            "Operator press releases + company pages",
        ],
    )


def _synthesize_generic(operator: str) -> list[ExistingSite]:
    """Fallback footprint when the operator isn't in our catalog."""
    return [
        ExistingSite(
            site_id=f"{operator[:4].upper()}-TOR-X", name=f"{operator} Toronto (synthesized)",
            operator=operator, city="Toronto", province="ON",
            latitude=43.65, longitude=-79.38,
            year_commissioned=2019,
            current_capacity_mw=20.0, contracted_mw=15.0,
            plot_acres=6, transformer_headroom_mw=5.0,
            fiber_providers=["Bell", "Rogers"],
            cooling="air", water_available_l_s=0.0,
            grid_zone="CA-ON", avg_carbon_g_kwh=130.0, pue=1.32,
            notes="Generic GTA campus (synthesized).",
        ),
        ExistingSite(
            site_id=f"{operator[:4].upper()}-MTL-X", name=f"{operator} Montréal (synthesized)",
            operator=operator, city="Montréal", province="QC",
            latitude=45.50, longitude=-73.57,
            year_commissioned=2020,
            current_capacity_mw=20.0, contracted_mw=14.0,
            plot_acres=7, transformer_headroom_mw=8.0,
            fiber_providers=["Bell", "Cogeco"],
            cooling="hybrid", water_available_l_s=8.0,
            grid_zone="CA-QC", avg_carbon_g_kwh=30.0, pue=1.24,
            notes="Generic Montreal campus (synthesized).",
        ),
    ]


# ── Live ElectricityMaps enrichment ───────────────────────────────────── #


async def enrich_with_live_carbon(footprint: OperatorFootprint) -> int:
    """
    For each site with a grid_zone, fetch the current ElectricityMaps reading
    and overwrite avg_carbon_g_kwh. Returns the count of sites successfully
    enriched. Failures (no key, rate limit, network) are silently swallowed —
    the baked-in baseline value stays.
    """
    unique_zones = sorted({s.grid_zone for s in footprint.sites if s.grid_zone})
    if not unique_zones:
        return 0

    async def fetch_one(zone: str) -> tuple[str, float | None]:
        try:
            payload = await electricitymaps_client.get_carbon_intensity(zone)
            if payload and payload.get("g_co2_per_kwh") is not None:
                return zone, float(payload["g_co2_per_kwh"])
        except Exception as e:
            logger.warning(f"ElectricityMaps fetch failed for {zone}: {e}")
        return zone, None

    results = await asyncio.gather(*(fetch_one(z) for z in unique_zones))
    fresh: dict[str, float] = {z: v for z, v in results if v is not None}
    if not fresh:
        return 0
    n = 0
    for site in footprint.sites:
        if site.grid_zone in fresh:
            site.avg_carbon_g_kwh = round(fresh[site.grid_zone], 1)
            n += 1
    return n
