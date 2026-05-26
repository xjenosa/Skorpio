"""
Auto-generated hourly Alberta Pool Price (CAD/MWh) and Alberta Internal
Load (AIL, MW). Source: AESO published CSV
`Hourly_Metered_Volumes_and_Pool_Price_and_AIL_2020-Jul2025.csv`.

Used by:
  - grid/generator.py (Siting) — real `spot_lmp_usd_mwh` for Alberta candidates
  - grid/feeder_topology.py (Winter Stress) — real Edmonton province-anchor peak
"""

POOL_PRICE_SUMMARY: dict = {
    "count": 48935,
    "mean": 94.94,
    "median": 45.31,
    "p10": 19.3,
    "p90": 199.09,
    "min": 0.0,
    "max": 999.99,
}

DATA_YEARS_COVERED: tuple = (2020, 2025)

AIL_SUMMARY_MW: dict = {
    "count": 48935,
    "mean": 9846.49,
    "median": 9837.0,
    "p10": 8754.0,
    "p90": 10928.0,
    "min": 7579.0,
    "max": 12384.0,
}

# 95th percentile AIL — proxy for a typical extreme-cold-day peak MW.
AIL_P95_MW: float = 11193.0
