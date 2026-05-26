"""
Utility asset catalog for the Climate-Adapted Grid Investment Optimizer.

Baked-in catalogs of representative at-risk grid assets per utility,
calibrated from public filings (utility annual reports, OEB rate cases,
AESO long-term outlook, Hydro-Québec strategic plan). Asset coordinates
are real where verifiable from EnergyData.ca / OpenStreetMap.

Unknown utilities fall back to the matching province's generic catalog
so the pipeline never fails on an unrecognized utility name.
"""
from __future__ import annotations

from backend.models.investment import GridAsset
from backend.services.grid_data import substations_for_utility as _real_substations


def _real_transmission_lines_for_utility(utility: str) -> list[dict]:
    """OSM-tagged transmission lines whose `operator` matches this
    utility name. Returns empty when the generated catalog is missing
    or when the operator string doesn't match anything in OSM."""
    if not utility:
        return []
    try:
        from backend.services._transmission_lines_generated import (
            TRANSMISSION_LINES_BY_OPERATOR,
        )
    except ImportError:
        return []
    key = re.sub(r"\s+", " ", utility.strip().lower())
    out = list(TRANSMISSION_LINES_BY_OPERATOR.get(key, []))
    # Fuzzy-match a couple of common aliases: "Hydro Quebec" → "Hydro-Québec"
    if not out and "quebec" in key:
        for k in TRANSMISSION_LINES_BY_OPERATOR:
            if "qu" in k and "bec" in k:
                out = list(TRANSMISSION_LINES_BY_OPERATOR[k])
                break
    return out


import re  # noqa: E402  (used by helper above)


# ── Utility-specific catalogs ─────────────────────────────────────────── #


_HONE_ASSETS: list[GridAsset] = [
    GridAsset(
        asset_id="HONE-TX-014", name="Bowmanville TS",
        asset_type="substation", utility="Hydro One",
        latitude=43.91, longitude=-78.69,
        age_years=58, replacement_cost_cad=140_000_000,
        customers_served=78_000, criticality="critical",
        notes="115/27.6 kV; serves Clarington / Bowmanville suburban load. Aged switchgear.",
    ),
    GridAsset(
        asset_id="HONE-TX-022", name="Cherrywood TS",
        asset_type="substation", utility="Hydro One",
        latitude=43.84, longitude=-79.07,
        age_years=44, replacement_cost_cad=180_000_000,
        customers_served=120_000, criticality="critical",
        notes="500/230 kV bulk transmission node serving GTA east.",
    ),
    GridAsset(
        asset_id="HONE-LN-101", name="Bruce A 500kV line section",
        asset_type="transmission_line", utility="Hydro One",
        latitude=44.32, longitude=-81.59,
        age_years=42, replacement_cost_cad=320_000_000,
        customers_served=2_400_000, criticality="critical",
        notes="120 km double-circuit; ice loading vulnerability identified in 2018 storm report.",
    ),
    GridAsset(
        asset_id="HONE-FD-309", name="Caledon East rural feeder cluster",
        asset_type="feeder", utility="Hydro One",
        latitude=43.85, longitude=-79.86,
        age_years=38, replacement_cost_cad=45_000_000,
        customers_served=14_000, criticality="standard",
        notes="Overhead rural distribution; high tree-fall outage history.",
    ),
    GridAsset(
        asset_id="HONE-TR-051", name="Belleville pad-mount transformer cluster",
        asset_type="transformer", utility="Hydro One",
        latitude=44.16, longitude=-77.38,
        age_years=33, replacement_cost_cad=8_500_000,
        customers_served=6_400, criticality="standard",
        notes="160 units past expected service life.",
    ),
]


_TORONTO_HYDRO_ASSETS: list[GridAsset] = [
    GridAsset(
        asset_id="TH-TX-007", name="Esplanade TS",
        asset_type="substation", utility="Toronto Hydro",
        latitude=43.65, longitude=-79.36,
        age_years=72, replacement_cost_cad=210_000_000,
        customers_served=185_000, criticality="critical",
        notes="Downtown core; partially underground vault.",
    ),
    GridAsset(
        asset_id="TH-FD-114", name="Beaches overhead feeder bank",
        asset_type="feeder", utility="Toronto Hydro",
        latitude=43.67, longitude=-79.30,
        age_years=46, replacement_cost_cad=32_000_000,
        customers_served=42_000, criticality="high",
        notes="High tree canopy; recurring ice/wind outages.",
    ),
    GridAsset(
        asset_id="TH-TR-205", name="Scarborough pad-mount cluster",
        asset_type="transformer", utility="Toronto Hydro",
        latitude=43.77, longitude=-79.23,
        age_years=29, replacement_cost_cad=11_000_000,
        customers_served=22_000, criticality="standard",
        notes="220 units; thermal-loading vulnerability under summer peak.",
    ),
    GridAsset(
        asset_id="TH-TX-019", name="Strachan TS",
        asset_type="substation", utility="Toronto Hydro",
        latitude=43.64, longitude=-79.42,
        age_years=68, replacement_cost_cad=165_000_000,
        customers_served=98_000, criticality="critical",
        notes="Serves Liberty Village / King West density growth.",
    ),
]


_EPCOR_ASSETS: list[GridAsset] = [
    GridAsset(
        asset_id="EPCOR-TX-003", name="Edmonton South Substation",
        asset_type="substation", utility="EPCOR",
        latitude=53.46, longitude=-113.49,
        age_years=51, replacement_cost_cad=130_000_000,
        customers_served=95_000, criticality="critical",
        notes="138/25 kV; serves industrial + residential.",
    ),
    GridAsset(
        asset_id="EPCOR-FD-088", name="Wildfire-adjacent rural feeders (Devon area)",
        asset_type="feeder", utility="EPCOR",
        latitude=53.36, longitude=-113.74,
        age_years=29, replacement_cost_cad=22_000_000,
        customers_served=8_400, criticality="high",
        notes="WUI (wildland-urban interface) exposure.",
    ),
    GridAsset(
        asset_id="EPCOR-LN-201", name="Genesee 500kV line section",
        asset_type="transmission_line", utility="EPCOR",
        latitude=53.21, longitude=-114.27,
        age_years=37, replacement_cost_cad=180_000_000,
        customers_served=400_000, criticality="critical",
        notes="Wind + ice loading; coal-retirement-driven flow reversal increases stress.",
    ),
]


_ALECTRA_ASSETS: list[GridAsset] = [
    GridAsset(
        asset_id="ALEC-MS-031", name="Erin Mills MS",
        asset_type="substation", utility="Alectra Utilities",
        latitude=43.55, longitude=-79.71,
        age_years=42, replacement_cost_cad=85_000_000,
        customers_served=64_000, criticality="critical",
        notes="44/27.6 kV Mississauga distribution; mixed residential + commercial.",
    ),
    GridAsset(
        asset_id="ALEC-FD-118", name="Stoney Creek feeder bank",
        asset_type="feeder", utility="Alectra Utilities",
        latitude=43.22, longitude=-79.76,
        age_years=37, replacement_cost_cad=18_000_000,
        customers_served=22_000, criticality="high",
        notes="Hamilton mountain overhead distribution. Recurring ice + tree-fall outages.",
    ),
    GridAsset(
        asset_id="ALEC-TR-204", name="Springdale pad-mount cluster",
        asset_type="transformer", utility="Alectra Utilities",
        latitude=43.74, longitude=-79.78,
        age_years=24, replacement_cost_cad=6_500_000,
        customers_served=14_000, criticality="standard",
        notes="Brampton suburban grid; thermal-loading risk under summer peak + EV uptake.",
    ),
    GridAsset(
        asset_id="ALEC-MS-049", name="Vaughan Centre MS",
        asset_type="substation", utility="Alectra Utilities",
        latitude=43.84, longitude=-79.52,
        age_years=29, replacement_cost_cad=92_000_000,
        customers_served=58_000, criticality="critical",
        notes="44/27.6 kV serving Vaughan Metropolitan Centre densification.",
    ),
    GridAsset(
        asset_id="ALEC-FD-076", name="St. Catharines downtown feeders",
        asset_type="feeder", utility="Alectra Utilities",
        latitude=43.16, longitude=-79.25,
        age_years=51, replacement_cost_cad=14_000_000,
        customers_served=17_000, criticality="standard",
        notes="Niagara region; ice + wind exposure off Lake Ontario.",
    ),
]


_HQ_ASSETS: list[GridAsset] = [
    GridAsset(
        asset_id="HQ-TX-101", name="Boucherville sous-station",
        asset_type="substation", utility="Hydro-Québec",
        latitude=45.61, longitude=-73.43,
        age_years=46, replacement_cost_cad=160_000_000,
        customers_served=140_000, criticality="critical",
        notes="South-shore Montréal load; 315/25 kV.",
    ),
    GridAsset(
        asset_id="HQ-LN-301", name="Churchill Falls 735kV line section",
        asset_type="transmission_line", utility="Hydro-Québec",
        latitude=53.53, longitude=-64.10,
        age_years=51, replacement_cost_cad=480_000_000,
        customers_served=3_200_000, criticality="critical",
        notes="Long-haul bulk transmission. 1998 ice storm exposed structural risk.",
    ),
    GridAsset(
        asset_id="HQ-FD-415", name="Laurentides rural feeder cluster",
        asset_type="feeder", utility="Hydro-Québec",
        latitude=46.40, longitude=-74.31,
        age_years=42, replacement_cost_cad=58_000_000,
        customers_served=28_000, criticality="standard",
        notes="Forested rural overhead; ice-storm prone.",
    ),
]


# ── Province fallback ─────────────────────────────────────────────────── #


def _generic_catalog(utility: str, province: str) -> list[GridAsset]:
    """Synthesize a generic 4-asset catalog for utilities we don't have data for.
    When OSM has real substations or transmission lines tagged to this
    operator, we anchor the synthesized substation + line entries to
    actual coordinates."""
    real_subs = _real_substations(utility) if utility else []
    real_lines = _real_transmission_lines_for_utility(utility) if utility else []
    base_lat, base_lon = {
        "ON": (43.65, -79.38), "QC": (45.50, -73.57), "AB": (51.05, -114.07),
        "BC": (49.28, -123.12), "MB": (49.90, -97.14), "NS": (44.65, -63.59),
    }.get(province, (49.0, -97.0))
    if real_subs:
        # Anchor on the highest-voltage real substation we have for this
        # operator. The list is already sorted desc by voltage in grid_data.
        anchor = real_subs[0]
        base_lat = float(anchor.get("lat") or base_lat)
        base_lon = float(anchor.get("lon") or base_lon)
    sub_name = (
        real_subs[0].get("name") or f"{utility} main TS"
    ) if real_subs else f"{utility} main TS"
    sub_notes = (
        f"OSM-cataloged substation (operator={utility}, "
        f"voltage={real_subs[0].get('voltage')} V)."
    ) if real_subs else "Generic critical substation (synthesized)."
    # Pick a real OSM transmission line for the operator if present —
    # sorted by voltage desc, take the highest one.
    if real_lines:
        top_line = max(real_lines, key=lambda l: l.get("voltage_v", 0))
        line_lat = float(top_line["lat"])
        line_lon = float(top_line["lon"])
        line_voltage_kv = int(top_line["voltage_v"] / 1000)
        line_name = f"{utility} {line_voltage_kv} kV line (OSM-anchored)"
        line_notes = (
            f"OSM-cataloged {line_voltage_kv} kV line near "
            f"({line_lat:.2f}, {line_lon:.2f}); operator={utility}."
        )
    else:
        line_lat = base_lat + 0.1
        line_lon = base_lon - 0.2
        line_voltage_kv = 230
        line_name = f"{utility} 230kV trunk"
        line_notes = "Generic bulk transmission line (synthesized)."
    return [
        GridAsset(
            asset_id=f"{utility[:4].upper()}-SUB-01", name=sub_name,
            asset_type="substation", utility=utility,
            latitude=base_lat, longitude=base_lon,
            age_years=48, replacement_cost_cad=120_000_000,
            customers_served=85_000, criticality="critical",
            notes=sub_notes,
        ),
        GridAsset(
            asset_id=f"{utility[:4].upper()}-LN-01", name=line_name,
            asset_type="transmission_line", utility=utility,
            latitude=line_lat, longitude=line_lon,
            age_years=39, replacement_cost_cad=200_000_000,
            customers_served=300_000, criticality="critical",
            notes=line_notes,
        ),
        GridAsset(
            asset_id=f"{utility[:4].upper()}-FD-01", name=f"{utility} rural feeder cluster",
            asset_type="feeder", utility=utility,
            latitude=base_lat - 0.15, longitude=base_lon + 0.3,
            age_years=35, replacement_cost_cad=30_000_000,
            customers_served=12_000, criticality="standard",
            notes="Generic rural overhead distribution (synthesized).",
        ),
        GridAsset(
            asset_id=f"{utility[:4].upper()}-TR-01", name=f"{utility} pad-mount cluster",
            asset_type="transformer", utility=utility,
            latitude=base_lat + 0.05, longitude=base_lon + 0.05,
            age_years=27, replacement_cost_cad=9_000_000,
            customers_served=5_500, criticality="standard",
            notes="Generic pad-mount cluster (synthesized).",
        ),
    ]


_REGISTRY: dict[str, list[GridAsset]] = {
    "hydro one": _HONE_ASSETS,
    "toronto hydro": _TORONTO_HYDRO_ASSETS,
    "alectra": _ALECTRA_ASSETS,
    "alectra utilities": _ALECTRA_ASSETS,
    "epcor": _EPCOR_ASSETS,
    "hydro-québec": _HQ_ASSETS,
    "hydro quebec": _HQ_ASSETS,
}


def list_supported_utilities() -> list[dict]:
    return [
        {"key": "hydro_one", "name": "Hydro One", "province": "ON", "asset_count": len(_HONE_ASSETS)},
        {"key": "toronto_hydro", "name": "Toronto Hydro", "province": "ON", "asset_count": len(_TORONTO_HYDRO_ASSETS)},
        {"key": "alectra", "name": "Alectra Utilities", "province": "ON", "asset_count": len(_ALECTRA_ASSETS)},
        {"key": "epcor", "name": "EPCOR", "province": "AB", "asset_count": len(_EPCOR_ASSETS)},
        {"key": "hydro_quebec", "name": "Hydro-Québec", "province": "QC", "asset_count": len(_HQ_ASSETS)},
    ]


def load_assets(utility: str, province: str = "ON") -> tuple[list[GridAsset], bool]:
    """
    Return (assets, is_synthesized). Synthesized = utility wasn't in the
    registry and a generic catalog was built from the province seed.
    """
    key = (utility or "").strip().lower()
    if key in _REGISTRY:
        return _REGISTRY[key], False
    return _generic_catalog(utility or "Unknown Utility", province or "ON"), True
