"""
Auto-generated annual electricity generation per province × fuel type, MWh.
Source: Statistics Canada Table 25-10-0015 ("Electric power generation,
monthly generation by class of electricity producer"), aggregated to the
most recent full year.

For each province: {year, fuels_mwh: {fuel_label: MWh}, total_mwh}.

Fuel labels are the raw StatsCan labels (lowercased) — typical values
include: combustible fuels, hydro, nuclear, tidal power, wind power,
solar power. Use a substring match (e.g. `"wind" in fuel`) when
classifying.

DO NOT EDIT BY HAND - re-run `python -m
backend.scripts.ingest_statscan_generating_stations`.

Used by:
  - grid/expansion_modeling.py — real per-province installed-generation
    proxy (annual MWh) for sanity-checking growth-rate projections
  - grid/feeder_topology.py — generation totals fed into provincial
    overlay for non-Ontario cities
"""

PROVINCIAL_GENERATION_MIX: dict[str, dict] = {
    "AB": {
        "year": 2026,
        "total_mwh": 7828606,
        "fuels_mwh": {
            "hydraulic turbine": 503248,
            "other types of electricity generation": 140826,
            "solar": 650020,
            "wind power turbine": 6534512,
        },
    },
    "BC": {
        "year": 2026,
        "total_mwh": 23832566,
        "fuels_mwh": {
            "hydraulic turbine": 23053224,
            "solar": 6246,
            "wind power turbine": 773096,
        },
    },
    "MB": {
        "year": 2026,
        "total_mwh": 9916624,
        "fuels_mwh": {
            "hydraulic turbine": 9582574,
            "solar": 630,
            "wind power turbine": 333420,
        },
    },
    "NB": {
        "year": 2026,
        "total_mwh": 2702196,
        "fuels_mwh": {
            "hydraulic turbine": 438430,
            "nuclear steam turbine": 1886812,
            "solar": 568,
            "wind power turbine": 376386,
        },
    },
    "NL": {
        "year": 2026,
        "total_mwh": 17344104,
        "fuels_mwh": {
            "hydraulic turbine": 17267304,
            "wind power turbine": 76800,
        },
    },
    "NS": {
        "year": 2026,
        "total_mwh": 829314,
        "fuels_mwh": {
            "hydraulic turbine": 252864,
            "solar": 1712,
            "wind power turbine": 574738,
        },
    },
    "NT": {
        "year": 2026,
        "total_mwh": 81380,
        "fuels_mwh": {
            "hydraulic turbine": 73734,
            "solar": 102,
            "wind power turbine": 7544,
        },
    },
    "NU": {
        "year": 2026,
        "total_mwh": 20,
        "fuels_mwh": {
            "solar": 20,
        },
    },
    "ON": {
        "year": 2026,
        "total_mwh": 43721776,
        "fuels_mwh": {
            "hydraulic turbine": 12337490,
            "nuclear steam turbine": 25177020,
            "solar": 410062,
            "wind power turbine": 5797204,
        },
    },
    "PE": {
        "year": 2026,
        "total_mwh": 283384,
        "fuels_mwh": {
            "solar": 9240,
            "wind power turbine": 274144,
        },
    },
    "QC": {
        "year": 2026,
        "total_mwh": 79968206,
        "fuels_mwh": {
            "hydraulic turbine": 75761908,
            "solar": 2622,
            "wind power turbine": 4203676,
        },
    },
    "SK": {
        "year": 2026,
        "total_mwh": 2132160,
        "fuels_mwh": {
            "hydraulic turbine": 1067330,
            "other types of electricity generation": 46796,
            "solar": 12416,
            "wind power turbine": 1005618,
        },
    },
    "YT": {
        "year": 2026,
        "total_mwh": 158652,
        "fuels_mwh": {
            "hydraulic turbine": 154876,
            "solar": 936,
            "wind power turbine": 2840,
        },
    },
}
