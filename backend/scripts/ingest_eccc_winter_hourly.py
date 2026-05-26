"""
Ingest ECCC hourly temperature data for canonical Canadian city stations
and derive a real "winter peak day" 24-hour temperature curve per
province. Replaces the eyeballed `_BASE_TEMP_PROFILE_C` array in
electrification_modeling.py with curves from the coldest 24-hour window
observed at each canonical station across the most recent two winters.

Source: ECCC Climate Data bulk_data endpoint
  https://climate.weather.gc.ca/climate_data/bulk_data_e.html

Usage:

    python -m backend.scripts.ingest_eccc_winter_hourly

Cache: data/cache/eccc_hourly_<STN>_<YYYY-MM>.csv. Re-run to refresh.
"""

from __future__ import annotations

import csv
import statistics
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
OUTPUT_FILE = REPO_ROOT / "backend" / "services" / "_winter_peak_curves_generated.py"

BULK_URL = "https://climate.weather.gc.ca/climate_data/bulk_data_e.html"


# Canonical ECCC stations by city. Station IDs are ECCC internal IDs
# (the `stationID` query parameter on climate.weather.gc.ca), verified
# from the ECCC station lookup. Each station's `name` and `province`
# match the labels ECCC ships in its own metadata.
STATIONS = [
    # ECCC stationID, city, province
    (51459, "Toronto City Centre",     "ON"),
    (51457, "Montréal McTavish",       "QC"),
    (50149, "Edmonton Blatchford",     "AB"),
    (50430, "Calgary International",   "AB"),
    (51442, "Vancouver Harbour CS",    "BC"),
    (53938, "Halifax Citadel",         "NS"),
    (3471,  "Winnipeg Richardson Int'l","MB"),
    (50620, "Ottawa CDA RCS",          "ON"),
]

# Winter months we sample from. ECCC publishes one file per month, so
# the script fetches each of these for each station × year.
WINTER_MONTHS = [12, 1, 2]
YEARS = [datetime.utcnow().year - 1, datetime.utcnow().year - 2]


def _url(station_id: int, year: int, month: int) -> str:
    params = {
        "format": "csv",
        "stationID": station_id,
        "Year": year,
        "Month": month,
        "Day": 14,
        "timeframe": 1,           # 1 = hourly
        "submit": "Download Data",
    }
    return f"{BULK_URL}?{urlencode(params)}"


def _download_if_missing(station_id: int, year: int, month: int) -> Path | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / f"eccc_hourly_{station_id}_{year}-{month:02d}.csv"
    if target.exists() and target.stat().st_size > 2_000:
        return target
    url = _url(station_id, year, month)
    try:
        req = Request(url, headers={"User-Agent": "Skorpio/1.0 (skorpio@energyplacement.ai)"})
        with urlopen(req, timeout=60) as resp, target.open("wb") as out:
            while chunk := resp.read(1 << 16):
                out.write(chunk)
        if target.stat().st_size < 2_000:
            target.unlink(missing_ok=True)
            return None
        return target
    except Exception as e:
        print(f"  [warn] stn {station_id} {year}-{month:02d}: {e}")
        return None


def _read_hourly_temps(csv_path: Path) -> list[tuple[datetime, float]]:
    """Return [(timestamp, temp_c)] for every well-formed row."""
    out: list[tuple[datetime, float]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        # ECCC bulk files have N rows of metadata at the top before the
        # actual CSV header. Walk forward until we find the header row.
        rows = list(csv.reader(f))
    header_idx = -1
    for i, row in enumerate(rows[:30]):
        joined = ",".join(row).lower()
        if "date/time" in joined or "date_time" in joined or "longitude" in joined:
            header_idx = i
            break
    if header_idx < 0:
        return out
    header = rows[header_idx]

    # ECCC labels temperature as "Temp (°C)" or "Temp (deg C)" depending on
    # vintage. Date/time appears as "Date/Time (LST)" or "Date_Time (LST)".
    def col_index(predicate) -> int | None:
        for i, c in enumerate(header):
            if predicate((c or "").strip().lower()):
                return i
        return None

    date_idx = col_index(lambda c: c.startswith("date/time") or c.startswith("date_time"))
    temp_idx = col_index(
        lambda c: c.startswith("temp ") and ("c" in c or "°" in c)
    )
    if date_idx is None or temp_idx is None:
        return out

    for row in rows[header_idx + 1:]:
        if len(row) <= max(date_idx, temp_idx):
            continue
        ts_raw = (row[date_idx] or "").strip()
        t_raw = (row[temp_idx] or "").strip()
        if not ts_raw or not t_raw:
            continue
        try:
            t = float(t_raw)
        except ValueError:
            continue
        ts: datetime | None = None
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                ts = datetime.strptime(ts_raw, fmt)
                break
            except ValueError:
                continue
        if ts is None:
            continue
        out.append((ts, t))
    return out


def _coldest_24h_window(samples: list[tuple[datetime, float]]) -> list[float] | None:
    if len(samples) < 48:
        return None
    samples.sort(key=lambda r: r[0])
    best_mean = float("inf")
    best_window: list[float] | None = None
    for i in range(len(samples) - 23):
        window = samples[i : i + 24]
        if (window[-1][0] - window[0][0]).total_seconds() > 25 * 3600:
            continue
        vals = [v for _, v in window]
        mean_v = statistics.fmean(vals)
        if mean_v < best_mean:
            best_mean = mean_v
            by_hour = {ts.hour: v for ts, v in window}
            best_window = [round(by_hour.get(h, mean_v), 1) for h in range(24)]
    return best_window


def build_curves() -> dict[str, dict]:
    by_prov_best: dict[str, dict] = {}
    for station_id, city, prov_code in STATIONS:
        all_samples: list[tuple[datetime, float]] = []
        last_year: int | None = None
        for year in YEARS:
            for month in WINTER_MONTHS:
                path = _download_if_missing(station_id, year, month)
                if not path:
                    continue
                samples = _read_hourly_temps(path)
                all_samples.extend(samples)
                if samples:
                    last_year = year
        if len(all_samples) < 48:
            print(f"  [skip] {city}: insufficient hourly samples ({len(all_samples)})")
            continue
        curve = _coldest_24h_window(all_samples)
        if not curve:
            continue
        mean_c = round(statistics.fmean(curve), 1)
        existing = by_prov_best.get(prov_code)
        if existing is None or mean_c < existing["mean_c"]:
            by_prov_best[prov_code] = {
                "city": city,
                "station_id": station_id,
                "year": last_year,
                "hours_c": curve,
                "mean_c": mean_c,
            }
            print(f"  [ok] {city} ({prov_code}): coldest 24h mean = {mean_c} °C")
    return by_prov_best


HEADER = '''"""
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
'''


def emit_python(curves: dict[str, dict], path: Path) -> None:
    if not curves:
        raise SystemExit("No winter curves derived; refusing to emit empty file.")
    with path.open("w", encoding="utf-8") as f:
        f.write(HEADER)
        for prov in sorted(curves):
            c = curves[prov]
            f.write(f'    "{prov}": {{\n')
            f.write(f'        "city": "{c["city"]}",\n')
            f.write(f'        "station_id": {c["station_id"]},\n')
            f.write(f'        "year": {c["year"]},\n')
            f.write(f'        "mean_c": {c["mean_c"]},\n')
            f.write(f'        "hours_c": {c["hours_c"]!r},\n')
            f.write(f'    }},\n')
        f.write("}\n")
    print(f"  Wrote {path}")


def main() -> None:
    curves = build_curves()
    emit_python(curves, OUTPUT_FILE)


if __name__ == "__main__":
    main()
