"""
Auto-generated province-level winter peak day 24-hour temperature curves.
Source: ECCC bulk_data_e.html hourly CSVs for canonical city stations
(Toronto City Centre, Montréal McTavish, Edmonton Blatchford, Calgary,
Vancouver Harbour, Halifax Citadel, Winnipeg, Ottawa). For each
province we slide a 24-hour window across Dec / Jan / Feb of the most
recent two complete winters and pick the window with the lowest mean
temperature — the realistic "coldest day" curve.

Hours are 0..23 in Local Standard Time at the station. Temperatures
are °C.

DO NOT EDIT BY HAND - re-run `python -m
backend.scripts.ingest_eccc_winter_hourly`.

Used by:
  - grid/electrification_modeling.py — replaces the eyeballed
    `_BASE_TEMP_PROFILE_C` constant with the real coldest-day curve
    for the FSA's province, when available
"""

WINTER_PEAK_DAY_TEMP_C: dict[str, dict] = {
    "AB": {
        "city": "Edmonton Blatchford",
        "station_id": 50149,
        "year": 2024,
        "mean_c": -41.4,
        "hours_c": [-44.7, -44.3, -43.9, -43.6, -43.8, -43.3, -45.0, -44.5, -43.8, -45.7, -44.5, -39.8, -38.0, -35.5, -34.6, -34.5, -34.6, -35.6, -37.8, -42.4, -41.3, -44.1, -45.1, -43.5],
    },
    "BC": {
        "city": "Vancouver Harbour CS",
        "station_id": 51442,
        "year": 2024,
        "mean_c": -11.5,
        "hours_c": [-12.2, -12.5, -12.8, -13.0, -13.6, -13.4, -13.5, -13.0, -13.3, -12.6, -11.4, -10.5, -9.4, -8.7, -8.6, -8.6, -9.4, -10.4, -10.9, -11.1, -11.8, -11.5, -11.7, -11.6],
    },
    "NS": {
        "city": "Halifax Citadel",
        "station_id": 53938,
        "year": 2024,
        "mean_c": -14.9,
        "hours_c": [-15.5, -17.0, -17.1, -17.1, -16.7, -16.6, -16.0, -17.3, -16.7, -14.0, -12.9, -13.3, -13.5, -13.1, -14.1, -13.4, -13.1, -13.5, -13.8, -14.5, -14.3, -14.0, -14.2, -15.5],
    },
    "ON": {
        "city": "Toronto City Centre",
        "station_id": 51459,
        "year": 2024,
        "mean_c": -15.3,
        "hours_c": [-16.5, -17.1, -17.3, -17.4, -17.6, -18.0, -18.2, -18.2, -18.0, -16.5, -14.6, -13.1, -12.6, -12.2, -12.2, -12.0, -12.2, -12.9, -13.8, -14.4, -15.0, -15.7, -16.1, -16.3],
    },
    "QC": {
        "city": "Montréal McTavish",
        "station_id": 51457,
        "year": 2024,
        "mean_c": -22.4,
        "hours_c": [-25.1, -27.6, -26.1, -28.0, -26.4, -27.6, -26.0, -26.8, -25.0, -22.2, -20.9, -18.7, -18.0, -16.7, -15.9, -15.3, -15.9, -17.8, -18.9, -21.0, -23.5, -24.8, -24.7, -24.7],
    },
}
