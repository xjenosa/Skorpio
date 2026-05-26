"""
Auto-generated 24-hour shape of Ontario system demand on winter weekdays
(Dec / Jan / Feb, Mon-Fri). Source: IESO Public Reports
PUB_Demand_2025.csv.

The shape is normalized so the 24 values average to 1.0. Downstream
callers multiply this shape by their own per-household baseline magnitude
to get an absolute hourly load. This is the real *timing pattern* of
Ontario demand even though IESO publishes system-wide totals, not
residential-only — the time-of-day signal is dominated by residential and
small-commercial behavior since heavy industry runs roughly flat.

Hours are 0..23 in IESO local time (EST, no DST). Index 0 = midnight
to 1 am.

DO NOT EDIT BY HAND - re-run `python -m backend.scripts.ingest_ieso_demand`.

Used by:
  - grid/electrification_modeling.py — overlays the real shape onto the
    eyeballed `_BASE_LOAD_KW_HOUR` array (preserves the original mean
    magnitude, applies the real time-of-day pattern)
"""

IESO_DEMAND_SHAPE_YEAR: int = 2025

# 24 values, mean = 1.0. Multiply by your own per-household mean kW to
# get an absolute hourly load.
IESO_WINTER_WEEKDAY_SHAPE: list[float] = [0.9012, 0.8811, 0.8749, 0.8732, 0.8816, 0.9097, 0.9685, 1.0314, 1.0476, 1.0471, 1.0425, 1.0343, 1.0255, 1.0245, 1.0294, 1.0438, 1.074, 1.1045, 1.0988, 1.0849, 1.0664, 1.0327, 0.9836, 0.9388]
