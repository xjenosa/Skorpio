"""
Auto-generated per-province residential heating-system mix shares. Source:
NRCan Survey of Household Energy Use 2019 (SHEU-2019), main
heating-equipment table from the published `SH2019e.xls` workbook.
Atlantic + Prairie regional buckets are stamped onto each constituent
province (NL/PE/NS/NB; MB/SK).

Shares sum to 1.0 within each province. Categories match the Skorpio
HeatingMix model: natural_gas, electric_baseboard, electric_forced_air,
heat_pump, oil, wood, other.

DO NOT EDIT BY HAND - re-run `python -m backend.scripts.ingest_sheu_2019`.

Used by:
  - services/statscan.py PROVINCE_DEFAULTS heating_mix (overlay)
"""

SHEU_HEATING_MIX_BY_PROVINCE: dict[str, dict[str, float]] = {
    "AB": {
        "natural_gas": 1.0,
        "electric_baseboard": 0.0,
        "electric_forced_air": 0.0,
        "heat_pump": 0.0,
        "oil": 0.0,
        "wood": 0.0,
        "other": 0.0,
    },
    "BC": {
        "natural_gas": 0.5637,
        "electric_baseboard": 0.2882,
        "electric_forced_air": 0.0,
        "heat_pump": 0.0648,
        "oil": 0.0,
        "wood": 0.0833,
        "other": 0.0,
    },
    "MB": {
        "natural_gas": 0.8992,
        "electric_baseboard": 0.1008,
        "electric_forced_air": 0.0,
        "heat_pump": 0.0,
        "oil": 0.0,
        "wood": 0.0,
        "other": 0.0,
    },
    "NB": {
        "natural_gas": 0.0,
        "electric_baseboard": 0.346,
        "electric_forced_air": 0.0,
        "heat_pump": 0.2101,
        "oil": 0.2333,
        "wood": 0.2105,
        "other": 0.0,
    },
    "NL": {
        "natural_gas": 0.0,
        "electric_baseboard": 0.346,
        "electric_forced_air": 0.0,
        "heat_pump": 0.2101,
        "oil": 0.2333,
        "wood": 0.2105,
        "other": 0.0,
    },
    "NS": {
        "natural_gas": 0.0,
        "electric_baseboard": 0.346,
        "electric_forced_air": 0.0,
        "heat_pump": 0.2101,
        "oil": 0.2333,
        "wood": 0.2105,
        "other": 0.0,
    },
    "ON": {
        "natural_gas": 0.7919,
        "electric_baseboard": 0.1043,
        "electric_forced_air": 0.0,
        "heat_pump": 0.0187,
        "oil": 0.0209,
        "wood": 0.0287,
        "other": 0.0355,
    },
    "PE": {
        "natural_gas": 0.0,
        "electric_baseboard": 0.346,
        "electric_forced_air": 0.0,
        "heat_pump": 0.2101,
        "oil": 0.2333,
        "wood": 0.2105,
        "other": 0.0,
    },
    "QC": {
        "natural_gas": 0.0492,
        "electric_baseboard": 0.6793,
        "electric_forced_air": 0.0,
        "heat_pump": 0.0834,
        "oil": 0.0372,
        "wood": 0.151,
        "other": 0.0,
    },
    "SK": {
        "natural_gas": 0.8992,
        "electric_baseboard": 0.1008,
        "electric_forced_air": 0.0,
        "heat_pump": 0.0,
        "oil": 0.0,
        "wood": 0.0,
        "other": 0.0,
    },
}
