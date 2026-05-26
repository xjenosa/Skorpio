"""
Ingest StatsCan Table 25-10-0021 (Electric power, electric utilities and
industry, annual supply and disposition) and emit per-province totals for
the rest of the pipeline.

Captures per province × year:
  - total generation (MWh)
  - residential consumption (MWh)
  - commercial / institutional consumption (MWh)
  - industrial consumption (MWh)

Used by feeder_topology to anchor CITY_PROFILES customer/load numbers for
provinces where the OEB Yearbook overlay does not apply (i.e. anything
outside Ontario — Quebec, Alberta, BC, Manitoba, etc.).

Source: Statistics Canada published English CSV ZIP, no API key needed.

Usage:

    python -m backend.scripts.ingest_provincial_electricity

Cache: data/cache/provincial_electricity.zip. Re-run to refresh.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from urllib.request import urlopen

CSV_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/25100021-eng.zip"

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
CACHED_ZIP = CACHE_DIR / "provincial_electricity.zip"
OUTPUT_FILE = REPO_ROOT / "backend" / "services" / "_provincial_electricity_generated.py"


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

# StatsCan publishes 21 different "components" in this table; we keep the
# six that matter for our pipeline and map them to short keys. Anything else
# (imports, exports, interprovincial flows, etc.) is dropped.
COMPONENT_LABELS: dict[str, str] = {
    "residential sales of electricity": "residential_mwh",
    "mining and manufacturing sales of electricity": "industrial_mwh",
    "other industries sales of electricity": "other_industry_mwh",
    "agriculture sales of electricity": "agriculture_mwh",
    "total sales of electricity to ultimate customers": "total_sales_mwh",
    "total generation of electricity": "total_generation_mwh",
}


def _download_if_missing() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHED_ZIP.exists() and CACHED_ZIP.stat().st_size > 50_000:
        print(f"[ok] Using cached ZIP at {CACHED_ZIP} ({CACHED_ZIP.stat().st_size / 1e3:.0f} KB)")
        return CACHED_ZIP
    print("[..] Downloading StatsCan 25-10-0021 provincial electricity...")
    with urlopen(CSV_URL) as resp, CACHED_ZIP.open("wb") as out:
        while chunk := resp.read(1 << 16):
            out.write(chunk)
    print(f"[ok] Saved to {CACHED_ZIP} ({CACHED_ZIP.stat().st_size / 1e3:.0f} KB)")
    return CACHED_ZIP


def _find_data_csv(zf: zipfile.ZipFile) -> str:
    candidates = [
        n for n in zf.namelist()
        if n.lower().endswith(".csv") and "metadata" not in n.lower()
    ]
    if not candidates:
        raise SystemExit(f"No data CSV in {CACHED_ZIP}: {zf.namelist()}")
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
    """Returns {province_code: {year, sectors: {sector_key: MWh}, ...}}.
    Keeps only the latest year per province."""
    with zipfile.ZipFile(zip_path) as zf:
        data_name = _find_data_csv(zf)
        print(f"  Reading {data_name} ...")
        with zf.open(data_name) as raw:
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
            component_c = find("electric power, components", "components")
            uom_c = find("UOM")
            if not (ref_c and geo_c and value_c and component_c):
                raise SystemExit(
                    f"Required columns missing. Saw: {cols}\n"
                    f"Got ref={ref_c!r} geo={geo_c!r} value={value_c!r} component={component_c!r}"
                )

            # year → province → component_key → value (MWh after UOM scaling)
            buckets: dict[int, dict[str, dict[str, float]]] = defaultdict(
                lambda: defaultdict(lambda: defaultdict(float))
            )
            for row in reader:
                year_s = row.get(ref_c, "")
                if not year_s.isdigit():
                    continue
                year = int(year_s)
                province = PROVINCE_LABELS.get((row.get(geo_c) or "").strip())
                if not province:
                    continue
                component = _norm(row.get(component_c, ""))
                key = COMPONENT_LABELS.get(component)
                if key is None:
                    continue
                val = _to_float(row.get(value_c, ""))
                if val is None or val <= 0:
                    continue
                # StatsCan reports this table in megawatt hours already, but
                # double-check the UOM column so we don't get fooled by a
                # later rescaling.
                uom = (row.get(uom_c, "") or "").lower() if uom_c else ""
                if "kilowatt" in uom:
                    val /= 1000.0
                elif "gigawatt" in uom:
                    val *= 1000.0
                buckets[year][province][key] = val

    years_sorted = sorted(buckets)
    if years_sorted:
        print(f"  Years seen: {years_sorted[:3]} ... {years_sorted[-3:]}")
    out: dict[str, dict] = {}
    for province in PROVINCE_LABELS.values():
        latest = None
        for year in sorted(buckets, reverse=True):
            components = buckets[year].get(province) or {}
            if "residential_mwh" in components:
                latest = (year, components)
                break
        if latest:
            year, components = latest
            out[province] = {"year": year, "components_mwh": dict(components)}
    return out


HEADER = '''"""
Auto-generated provincial-level annual electricity supply / disposition,
in MWh. Source: Statistics Canada Table 25-10-0021 ("Electric power,
electric utilities and industry, annual supply and disposition"), downloaded
as the published English CSV.

Values are the *latest* reporting year present in the source for each
province. The dict maps province two-letter code → {year, components_mwh}
where `components_mwh` keys are:
  - residential_mwh       (Residential sales of electricity)
  - industrial_mwh        (Mining and manufacturing sales of electricity)
  - other_industry_mwh    (Other industries sales of electricity)
  - agriculture_mwh       (Agriculture sales of electricity)
  - total_sales_mwh       (Total sales to ultimate customers)
  - total_generation_mwh  (Total generation of electricity)

DO NOT EDIT BY HAND - re-run `python -m
backend.scripts.ingest_provincial_electricity`.

Used by:
  - feeder_topology.py CITY_PROFILES (residential MWh anchors winter peak
    estimates for non-Ontario provinces, where OEB Yearbook overlay does
    not apply)
"""

PROVINCIAL_ELECTRICITY_BY_PROVINCE: dict[str, dict] = {
'''


def emit_python(per_prov: dict[str, dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write(HEADER)
        for province in sorted(per_prov):
            e = per_prov[province]
            f.write(f'    "{province}": {{\n')
            f.write(f'        "year": {e["year"]},\n')
            f.write(f'        "components_mwh": {{\n')
            for k in sorted(e["components_mwh"]):
                f.write(f'            "{k}": {int(e["components_mwh"][k])},\n')
            f.write(f'        }},\n')
            f.write(f'    }},\n')
        f.write("}\n")
    print(f"  Wrote {path}")


def main() -> None:
    zip_path = _download_if_missing()
    per_prov = aggregate(zip_path)
    print(f"  Aggregated {len(per_prov)} provinces.")
    emit_python(per_prov, OUTPUT_FILE)

    print("\nSpot-check (residential MWh by province, latest year):")
    rows = [(p, e["year"], e["components_mwh"].get("residential_mwh", 0))
            for p, e in per_prov.items()]
    rows.sort(key=lambda r: -r[2])
    for p, y, mwh in rows:
        print(f"  {p} ({y}): {mwh:,} MWh residential")


if __name__ == "__main__":
    main()
