"""
Ingest StatsCan Table 25-10-0015 (Electric power generation, monthly
generation by class of electricity producer). Aggregates the most-recent
year per province + fuel into installed-capacity-proxy MWh totals.

Source: StatsCan English CSV ZIP
  https://www150.statcan.gc.ca/n1/tbl/csv/25100015-eng.zip

Usage:

    python -m backend.scripts.ingest_statscan_generating_stations

Cache: data/cache/statscan_generating_stations.zip. Re-run to refresh.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from urllib.request import urlopen

URL = "https://www150.statcan.gc.ca/n1/tbl/csv/25100015-eng.zip"

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
CACHED_ZIP = CACHE_DIR / "statscan_generating_stations.zip"
OUTPUT_FILE = REPO_ROOT / "backend" / "services" / "_provincial_generation_mix_generated.py"


PROVINCE_LABELS: dict[str, str] = {
    "Newfoundland and Labrador": "NL",
    "Prince Edward Island": "PE",
    "Nova Scotia": "NS",
    "New Brunswick": "NB",
    "Quebec": "QC",
    "Ontario": "ON",
    "Manitoba": "MB",
    "Saskatchewan": "SK",
    "Alberta": "AB",
    "British Columbia": "BC",
    "Yukon": "YT",
    "Northwest Territories": "NT",
    "Nunavut": "NU",
}


def _download_if_missing() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHED_ZIP.exists() and CACHED_ZIP.stat().st_size > 50_000:
        print(f"[ok] Using cached ZIP at {CACHED_ZIP} "
              f"({CACHED_ZIP.stat().st_size / 1e3:.0f} KB)")
        return CACHED_ZIP
    print("[..] Downloading StatsCan 25-10-0015 generating stations...")
    with urlopen(URL) as resp, CACHED_ZIP.open("wb") as out:
        while chunk := resp.read(1 << 16):
            out.write(chunk)
    print(f"[ok] Saved to {CACHED_ZIP} ({CACHED_ZIP.stat().st_size / 1e3:.0f} KB)")
    return CACHED_ZIP


def _find_data_csv(zf: zipfile.ZipFile) -> str:
    candidates = [n for n in zf.namelist()
                  if n.lower().endswith(".csv") and "metadata" not in n.lower()]
    if not candidates:
        raise SystemExit(f"No data CSV in zip: {zf.namelist()}")
    return max(candidates, key=lambda n: zf.getinfo(n).file_size)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _to_float(s: str) -> float | None:
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if not s or s in {"..", "...", "F", "x", "-"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def aggregate(zip_path: Path) -> dict[str, dict]:
    """{province: {year, fuels_mwh: {fuel: total_mwh}}} for latest year."""
    with zipfile.ZipFile(zip_path) as zf:
        name = _find_data_csv(zf)
        print(f"  Reading {name} ...")
        with zf.open(name) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text)
            cols = reader.fieldnames or []

            def find(*needles: str) -> str | None:
                for needle in needles:
                    for c in cols:
                        if needle.lower() in c.lower():
                            return c
                return None

            ref_c = find("REF_DATE")
            geo_c = find("GEO")
            value_c = find("VALUE")
            fuel_c = find("type of electricity generation", "type of generation",
                          "class of electricity producer", "generation type")
            if not (ref_c and geo_c and value_c and fuel_c):
                raise SystemExit(
                    f"Required columns missing. Saw: {cols}\n"
                    f"Got ref={ref_c!r} geo={geo_c!r} value={value_c!r} fuel={fuel_c!r}"
                )

            # The reference period is monthly (YYYY-MM); we aggregate per
            # year and pick the most recent complete year.
            buckets: dict[int, dict[str, dict[str, float]]] = defaultdict(
                lambda: defaultdict(lambda: defaultdict(float))
            )
            seen_years_with_full_data: dict[int, int] = defaultdict(int)
            for row in reader:
                ref = row.get(ref_c, "")
                if len(ref) >= 4 and ref[:4].isdigit():
                    year = int(ref[:4])
                else:
                    continue
                province = PROVINCE_LABELS.get((row.get(geo_c) or "").strip())
                if not province:
                    continue
                fuel = _norm(row.get(fuel_c, ""))
                if not fuel or "total" in fuel:
                    continue
                val = _to_float(row.get(value_c, ""))
                if val is None or val <= 0:
                    continue
                buckets[year][province][fuel] += val
                seen_years_with_full_data[year] += 1

    if not buckets:
        raise SystemExit("Parsed 0 rows from generating stations table.")
    print(f"  Years seen: {sorted(buckets)[:3]} ... {sorted(buckets)[-3:]}")

    # Pick the latest year that has data for ≥8 provinces (covers a full year).
    target_year = None
    for y in sorted(buckets, reverse=True):
        if len(buckets[y]) >= 8:
            target_year = y
            break
    if target_year is None:
        target_year = max(buckets)
    print(f"  Using target year: {target_year}")

    out: dict[str, dict] = {}
    for province, fuels in buckets[target_year].items():
        out[province] = {
            "year": target_year,
            "fuels_mwh": dict(fuels),
            "total_mwh": int(sum(fuels.values())),
        }
    return out


HEADER = '''"""
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
'''


def emit_python(per_prov: dict[str, dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write(HEADER)
        for province in sorted(per_prov):
            e = per_prov[province]
            f.write(f'    "{province}": {{\n')
            f.write(f'        "year": {e["year"]},\n')
            f.write(f'        "total_mwh": {e["total_mwh"]},\n')
            f.write(f'        "fuels_mwh": {{\n')
            for fuel in sorted(e["fuels_mwh"]):
                f.write(f'            "{fuel}": {int(e["fuels_mwh"][fuel])},\n')
            f.write(f'        }},\n')
            f.write(f'    }},\n')
        f.write("}\n")
    print(f"  Wrote {path}")


def main() -> None:
    zip_path = _download_if_missing()
    per_prov = aggregate(zip_path)
    print(f"  Aggregated {len(per_prov)} provinces.")
    emit_python(per_prov, OUTPUT_FILE)

    print("\nSpot-check (total MWh by province, latest year):")
    rows = [(p, e["year"], e["total_mwh"]) for p, e in per_prov.items()]
    rows.sort(key=lambda r: -r[2])
    for p, y, mwh in rows:
        print(f"  {p} ({y}): {mwh:,} MWh total")


if __name__ == "__main__":
    main()
