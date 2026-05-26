"""
Ingest StatsCan Table 23-10-0308 (Vehicle registrations, by type of vehicle
and fuel type) and emit per-province totals + EV share. Replaces the
hand-tuned `ev_penetration_pct` numbers in feeder_topology CITY_PROFILES
and the `vehicles_per_household` defaults in PROVINCE_DEFAULTS.

Source: StatsCan WDS via the published English CSV ZIP. No API key needed.

Usage:

    python -m backend.scripts.ingest_vehicle_registrations

Cache: data/cache/vehicle_registrations.zip. Re-run to refresh.
"""

from __future__ import annotations

import csv
import io
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from urllib.request import urlopen

CSV_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/23100308-eng.zip"

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
CACHED_ZIP = CACHE_DIR / "vehicle_registrations.zip"
OUTPUT_FILE = REPO_ROOT / "backend" / "services" / "_vehicle_registrations_generated.py"

# StatsCan publishes English province labels; map back to 2-letter codes the
# rest of Skorpio uses.
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

# StatsCan publishes light-duty as the aggregate "Total, vehicles weighing
# 4,536 kilograms or less" line — that bucket combines passenger cars, light
# pickups, vans, and SUVs, which is what the electrification pipeline cares
# about (heavy trucks have a separate adoption curve we don't model).
VEHICLE_TYPE_LIGHT_DUTY = "total, vehicles weighing 4,536 kilograms or less"

# Fuel-type labels we treat as zero-emission for "EV share" purposes.
# StatsCan uses one composite "Battery electric" plus "Plug-in hybrid
# electric" line; "Hybrid electric" (non-plug-in) is NOT counted.
EV_FUEL_LABELS = {"battery electric", "plug-in hybrid electric"}
TOTAL_FUEL_LABEL = "all fuel types"


# ── Download ────────────────────────────────────────────────────────────── #

def _download_if_missing() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHED_ZIP.exists() and CACHED_ZIP.stat().st_size > 50_000:
        print(f"[ok] Using cached ZIP at {CACHED_ZIP} ({CACHED_ZIP.stat().st_size / 1e3:.0f} KB)")
        return CACHED_ZIP
    print("[..] Downloading StatsCan 23-10-0308 vehicle registrations...")
    with urlopen(CSV_URL) as resp, CACHED_ZIP.open("wb") as out:
        while chunk := resp.read(1 << 16):
            out.write(chunk)
    print(f"[ok] Saved to {CACHED_ZIP} ({CACHED_ZIP.stat().st_size / 1e3:.0f} KB)")
    return CACHED_ZIP


def _find_data_csv(zf: zipfile.ZipFile) -> str:
    """The ZIP usually contains <table>.csv plus a metadata CSV. Pick the
    data file (largest .csv inside, by uncompressed size)."""
    candidates = [
        n for n in zf.namelist()
        if n.lower().endswith(".csv") and "metadata" not in n.lower()
    ]
    if not candidates:
        raise SystemExit(f"No data CSV inside {CACHED_ZIP}: {zf.namelist()}")
    return max(candidates, key=lambda n: zf.getinfo(n).file_size)


# ── Parse ───────────────────────────────────────────────────────────────── #

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
    """Returns {province_code: {year: int, total: float, ev: float, share_pct: float}}.
    Uses the latest year in the file per province."""
    with zipfile.ZipFile(zip_path) as zf:
        data_name = _find_data_csv(zf)
        print(f"  Reading {data_name} ...")
        with zf.open(data_name) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text)
            cols = reader.fieldnames or []

            def find(*needles: str) -> str:
                for needle in needles:
                    for c in cols:
                        if needle.lower() in c.lower():
                            return c
                raise SystemExit(f"Missing column among {needles!r} in {cols}")

            ref_c = find("REF_DATE")
            geo_c = find("GEO")
            value_c = find("VALUE")
            # Vehicle type + fuel type live in their own columns; sniff them.
            vtype_c = next((c for c in cols if "vehicle type" in c.lower()
                            or "type of vehicle" in c.lower()), "")
            ftype_c = next((c for c in cols if "fuel type" in c.lower()), "")
            if not vtype_c or not ftype_c:
                raise SystemExit(
                    f"Could not find vehicle-type / fuel-type columns. "
                    f"Cols seen: {cols}"
                )

            # year → province → {fuel_label: total}
            buckets: dict[int, dict[str, dict[str, float]]] = defaultdict(
                lambda: defaultdict(lambda: defaultdict(float))
            )
            for row in reader:
                year = int(row[ref_c]) if row.get(ref_c, "").isdigit() else None
                if not year:
                    continue
                geo = (row.get(geo_c) or "").strip()
                province = PROVINCE_LABELS.get(geo)
                if not province:
                    # Skip "Canada" rollup and any unknown regions.
                    continue
                vtype = _norm(row.get(vtype_c, ""))
                ftype = _norm(row.get(ftype_c, ""))
                if vtype != VEHICLE_TYPE_LIGHT_DUTY:
                    continue
                val = _to_float(row.get(value_c, ""))
                if val is None:
                    continue
                buckets[year][province][ftype] = val

    # Pick latest year that has both a total and at least one EV split.
    print(f"  Years seen: {sorted(buckets)}")
    out: dict[str, dict] = {}
    for province in PROVINCE_LABELS.values():
        latest = None
        for year in sorted(buckets, reverse=True):
            fuels = buckets[year].get(province) or {}
            total = fuels.get(TOTAL_FUEL_LABEL)
            ev_sum = sum(v for k, v in fuels.items() if k in EV_FUEL_LABELS)
            if total and total > 0:
                latest = (year, total, ev_sum)
                break
        if latest:
            year, total, ev = latest
            out[province] = {
                "year": year,
                "total_light_duty": int(total),
                "ev_count": int(ev),
                "ev_share_pct": round(100.0 * ev / total, 2),
            }
    return out


# ── Emit ────────────────────────────────────────────────────────────────── #

HEADER = '''"""
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
'''


def emit_python(per_prov: dict[str, dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write(HEADER)
        for province in sorted(per_prov):
            e = per_prov[province]
            f.write(f'    "{province}": {{\n')
            f.write(f'        "year": {e["year"]},\n')
            f.write(f'        "total_light_duty": {e["total_light_duty"]},\n')
            f.write(f'        "ev_count": {e["ev_count"]},\n')
            f.write(f'        "ev_share_pct": {e["ev_share_pct"]},\n')
            f.write(f'    }},\n')
        f.write("}\n")
    print(f"  Wrote {path}")


def main() -> None:
    zip_path = _download_if_missing()
    per_prov = aggregate(zip_path)
    print(f"  Aggregated {len(per_prov)} provinces.")
    emit_python(per_prov, OUTPUT_FILE)

    print("\nSpot-check (EV share by province, latest year):")
    for province in sorted(per_prov, key=lambda p: -per_prov[p]["ev_share_pct"]):
        e = per_prov[province]
        print(f"  {province} ({e['year']}): {e['ev_share_pct']:.2f}% EV "
              f"({e['ev_count']:,} / {e['total_light_duty']:,})")


if __name__ == "__main__":
    main()
