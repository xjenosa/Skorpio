"""
Auto-generated province-level light-duty vehicle registration totals and EV
shares. Source: Statistics Canada Table 23-10-0308 ("Vehicle registrations,
by type of vehicle and fuel type"), downloaded as the published English CSV.

EV share = (Battery electric + Plug-in hybrid electric) / All fuel types,
for light-duty vehicles only. Non-plug-in hybrids are NOT counted as EVs.

DO NOT EDIT BY HAND - re-run `python -m
backend.scripts.ingest_vehicle_registrations`.

Used by:
  - feeder_topology.py CITY_PROFILES (ev_penetration_pct per city, derived
    from the matching province's share)
  - statscan.py PROVINCE_DEFAULTS (vehicles_per_household sanity-check)
"""

VEHICLE_REGISTRATIONS_BY_PROVINCE: dict[str, dict] = {
    "AB": {
        "year": 2024,
        "total_light_duty": 3207147,
        "ev_count": 23992,
        "ev_share_pct": 0.75,
    },
    "BC": {
        "year": 2024,
        "total_light_duty": 3416922,
        "ev_count": 170341,
        "ev_share_pct": 4.99,
    },
    "MB": {
        "year": 2024,
        "total_light_duty": 871321,
        "ev_count": 6266,
        "ev_share_pct": 0.72,
    },
    "NB": {
        "year": 2024,
        "total_light_duty": 568138,
        "ev_count": 5222,
        "ev_share_pct": 0.92,
    },
    "NL": {
        "year": 2024,
        "total_light_duty": 357183,
        "ev_count": 2110,
        "ev_share_pct": 0.59,
    },
    "NS": {
        "year": 2024,
        "total_light_duty": 665832,
        "ev_count": 6218,
        "ev_share_pct": 0.93,
    },
    "NT": {
        "year": 2024,
        "total_light_duty": 23537,
        "ev_count": 103,
        "ev_share_pct": 0.44,
    },
    "NU": {
        "year": 2024,
        "total_light_duty": 4503,
        "ev_count": 3,
        "ev_share_pct": 0.07,
    },
    "ON": {
        "year": 2024,
        "total_light_duty": 8806814,
        "ev_count": 172130,
        "ev_share_pct": 1.95,
    },
    "PE": {
        "year": 2024,
        "total_light_duty": 109758,
        "ev_count": 1605,
        "ev_share_pct": 1.46,
    },
    "QC": {
        "year": 2024,
        "total_light_duty": 5635194,
        "ev_count": 293111,
        "ev_share_pct": 5.2,
    },
    "SK": {
        "year": 2024,
        "total_light_duty": 848283,
        "ev_count": 3647,
        "ev_share_pct": 0.43,
    },
    "YT": {
        "year": 2024,
        "total_light_duty": 35560,
        "ev_count": 451,
        "ev_share_pct": 1.27,
    },
}
