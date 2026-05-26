"""
Ingest ECCC 1981-2010 Canadian Climate Normals (per-station CSV files from
the MSC Datamart) and emit a list of stations with lat/lon and annual
HDD18 (heating degree days, base 18 °C). The electrification pipeline can
then look up the nearest station to any FSA centroid instead of using the
province-level HDD default.

Source: https://dd.weather.gc.ca/today/climate/observations/normals/csv/1981-2010/<PROV>/
  ~1,500 per-station CSVs total. Each one is a few KB. We pull them
  concurrently (ThreadPool, 16 workers) so the whole ingest takes ~1 minute
  on a decent connection.

Usage:

    python -m backend.scripts.ingest_climate_normals

Cache: data/cache/climate_normals/<PROV>/*.csv. Re-runs are cheap.
"""

from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache" / "climate_normals"
OUTPUT_FILE = REPO_ROOT / "backend" / "services" / "_hdd_stations_generated.py"

BASE_URL = "https://dd.weather.gc.ca/today/climate/observations/normals/csv/1981-2010"
PROVINCES = ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"]
USER_AGENT = "Skorpio/1.0 (skorpio@energyplacement.ai)"


# ── Listing & download ─────────────────────────────────────────────────── #

class _LinkParser(HTMLParser):
    """Extract CSV filenames from the Apache directory listing."""
    def __init__(self) -> None:
        super().__init__()
        self.csvs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for k, v in attrs:
            if k == "href" and v and v.endswith(".csv"):
                self.csvs.append(v)


def _fetch(url: str, dest: Path | None = None) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=120) as resp:
        data = resp.read()
    if dest is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return data


def list_province_files(prov: str) -> list[str]:
    """Return CSV filenames in the province's Datamart directory."""
    html = _fetch(f"{BASE_URL}/{prov}/").decode("utf-8", errors="replace")
    p = _LinkParser()
    p.feed(html)
    return p.csvs


def download_all_csvs() -> list[Path]:
    """Download every per-station CSV across all provinces (cached)."""
    all_paths: list[Path] = []
    for prov in PROVINCES:
        prov_dir = CACHE_DIR / prov
        prov_dir.mkdir(parents=True, exist_ok=True)
        files = list_province_files(prov)
        # Schedule the missing ones; reuse cached.
        missing = [(f, prov_dir / f) for f in files if not (prov_dir / f).exists()]
        if missing:
            print(f"  [{prov}] downloading {len(missing)} of {len(files)} stations...")
            with ThreadPoolExecutor(max_workers=16) as pool:
                futures = [pool.submit(_fetch, f"{BASE_URL}/{prov}/{name}", path)
                           for name, path in missing]
                for fut in as_completed(futures):
                    fut.result()  # raise on failure
        else:
            print(f"  [{prov}] {len(files)} stations cached.")
        all_paths.extend(prov_dir / f for f in files)
    return all_paths


# ── Parse ───────────────────────────────────────────────────────────────── #

# ECCC CSV uses Windows-1252; the degree sign comes through fine that way.
CSV_ENCODING = "cp1252"


def _dms_to_decimal(s: str) -> float | None:
    """ECCC writes "44°07'00.000" N" / "77°32'00.000" W". Convert to signed decimal."""
    if not s:
        return None
    s = s.strip().strip('"').replace("\xb0", " ").replace("'", " ").replace('"', " ")
    # Normalise the degree symbol that ECCC sometimes writes as ° / � / etc.
    s = re.sub(r"[^A-Za-z0-9.\-\s]", " ", s)
    parts = s.split()
    if len(parts) < 3:
        return None
    try:
        deg = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])
        hemi = parts[-1].upper() if parts[-1].isalpha() else ""
    except ValueError:
        return None
    val = deg + minutes / 60.0 + seconds / 3600.0
    if hemi in {"S", "W"}:
        val = -val
    return round(val, 6)


def _to_float(s: str) -> float | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_station(path: Path) -> dict | None:
    """Returns {name, province, lat, lon, hdd18_annual, climate_id} or None
    if the file is missing required fields."""
    try:
        text = path.read_text(encoding=CSV_ENCODING, errors="replace")
    except OSError:
        return None
    lines = text.splitlines()

    # Find the metadata block: header line starts with "STATION_NAME"
    name = province = lat_dms = lon_dms = climate_id = ""
    for i, ln in enumerate(lines):
        if ln.startswith('"STATION_NAME"'):
            if i + 1 < len(lines):
                # CSV row, fields are quoted with comma sep
                row = next(__import__("csv").reader([lines[i + 1]]))
                if len(row) >= 6:
                    name = row[0].lstrip("* ").strip()
                    province = row[1].strip()
                    lat_dms = row[2]
                    lon_dms = row[3]
                    climate_id = row[5].strip()
            break

    lat = _dms_to_decimal(lat_dms)
    lon = _dms_to_decimal(lon_dms)
    if lat is None or lon is None:
        return None

    # Find the HDD18 annual row. After the "Degree Days" section header we
    # have several "Above N °C" and "Below N °C" rows. We want
    # "Below 18 �C" (the degree symbol becomes � under cp1252 mojibake;
    # match generously).
    hdd18 = None
    in_dd_section = False
    for ln in lines:
        if '"Degree Days"' in ln:
            in_dd_section = True
            continue
        if not in_dd_section:
            continue
        # Stop when we leave the degree-days block (next titled section).
        # The next section header is just a bare quoted phrase with no
        # numeric data, e.g. '"Humidex"'.
        # But within DD, rows look like '"Below 18 ?C","val1",...'
        m = re.match(r'^"Below\s+18\s+[^"]*?C",(.+)$', ln)
        if m:
            row = next(__import__("csv").reader([ln]))
            # Cols: label, Jan..Dec (12), Year (13th value col), Code
            if len(row) >= 14:
                hdd18 = _to_float(row[13])
            break
        # Cheap section-leave heuristic: a "Humidex" or other titled row.
        if re.match(r'^"[A-Z][a-zA-Z ]+"$', ln.rstrip(",")):
            break

    if hdd18 is None:
        return None

    return {
        "name": name,
        "province": province,
        "lat": lat,
        "lon": lon,
        "hdd18_annual": round(hdd18, 1),
        "climate_id": climate_id,
    }


# ── Emit ────────────────────────────────────────────────────────────────── #

HEADER = '''"""
Auto-generated list of ECCC weather stations with annual HDD18 (heating
degree days, base 18 °C) computed from the official 1981-2010 Canadian
Climate Normals. Each entry traces to the source CSV at
https://dd.weather.gc.ca/today/climate/observations/normals/csv/1981-2010/.

Used by the electrification pipeline to override the province-level HDD
default with the nearest station's actual normal for a given FSA centroid.

DO NOT EDIT BY HAND - re-run `python -m backend.scripts.ingest_climate_normals`.

Fields per station:
  name           — ECCC station name (asterisk prefix indicating WMO
                   conformance is stripped)
  province       — 2-letter code
  lat, lon       — WGS84 decimal degrees (converted from the file's DMS)
  hdd18_annual   — annual total degree-days below 18 °C, 30-year normal
  climate_id     — ECCC climate identifier (audit-able on the ECCC site)
"""

HDD_STATIONS: list[dict] = [
'''


def emit_python(stations: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write(HEADER)
        for s in sorted(stations, key=lambda x: (x["province"], x["name"])):
            f.write('    {')
            f.write(f'"name": {s["name"]!r}, "province": {s["province"]!r}, ')
            f.write(f'"lat": {s["lat"]}, "lon": {s["lon"]}, ')
            f.write(f'"hdd18_annual": {s["hdd18_annual"]}, ')
            f.write(f'"climate_id": {s["climate_id"]!r}')
            f.write('},\n')
        f.write("]\n")
    print(f"  Wrote {path}")


def main() -> None:
    print("[..] Listing + downloading ECCC Climate Normals per province...")
    paths = download_all_csvs()
    print(f"  {len(paths):,} per-station CSVs available.")

    print("[..] Parsing HDD18 from each file (may show some skips for non-temp stations)...")
    stations: list[dict] = []
    skipped = 0
    for p in paths:
        rec = parse_station(p)
        if rec is None:
            skipped += 1
            continue
        stations.append(rec)
    print(f"  Parsed {len(stations):,} stations with HDD18 ({skipped:,} skipped).")
    emit_python(stations, OUTPUT_FILE)

    print("\nSpot-check (3 known cities, nearest station per province):")
    for target_name in ("TORONTO", "MONTREAL", "CALGARY", "HALIFAX"):
        match = next((s for s in stations if target_name in s["name"].upper()), None)
        if match:
            print(f"  {match['name']} ({match['province']}): "
                  f"HDD18={match['hdd18_annual']:.0f}, "
                  f"({match['lat']}, {match['lon']})")


if __name__ == "__main__":
    main()
