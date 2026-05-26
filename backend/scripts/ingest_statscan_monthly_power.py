"""
Ingest StatsCan Table 25-10-0022 (Electric power, monthly disposition,
by province). Captures per-province monthly demand/disposition so the
Winter Stress pipeline can anchor non-Ontario city peaks against a
real monthly time series (StatsCan only publishes monthly, not hourly,
for most provinces — that's the trade-off vs. paid hourly utility data).

Source: StatsCan English CSV ZIP
  https://www150.statcan.gc.ca/n1/tbl/csv/25100022-eng.zip

Usage:

    python -m backend.scripts.ingest_statscan_monthly_power

Cache: data/cache/statscan_monthly_power.zip. Re-run to refresh.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from urllib.request import urlopen

URL = "https://www150.statcan.gc.ca/n1/tbl/csv/25100022-eng.zip"

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
CACHED_ZIP = CACHE_DIR / "statscan_monthly_power.zip"
OUTPUT_FILE = REPO_ROOT / "backend" / "services" / "_provincial_monthly_power_generated.py"


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
    print("[..] Downloading StatsCan 25-10-0022 monthly electric power...")
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
    """{province: {year, monthly_total_mwh: [Jan..Dec], peak_month_mwh, peak_month}}
    using the latest year that has 12 months of data."""
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
            component_c = find("electric power, components", "components",
                               "type of consumer")
            if not (ref_c and geo_c and value_c):
                raise SystemExit(
                    f"Required columns missing. Saw: {cols}\n"
                    f"Got ref={ref_c!r} geo={geo_c!r} value={value_c!r}"
                )

            # year → province → month → MWh, for "Total electricity available
            # for use within specific geographic border" component (which is
            # the closest proxy to total provincial demand published monthly).
            target_component = ("total electricity available for use within "
                                "specific geographic border")
            buckets: dict[int, dict[str, dict[int, float]]] = defaultdict(
                lambda: defaultdict(lambda: defaultdict(float))
            )
            for row in reader:
                ref = row.get(ref_c, "")
                # REF_DATE in this table is YYYY-MM
                m = re.match(r"(\d{4})-(\d{1,2})", ref)
                if not m:
                    continue
                year = int(m.group(1))
                month = int(m.group(2))
                if month < 1 or month > 12:
                    continue
                province = PROVINCE_LABELS.get((row.get(geo_c) or "").strip())
                if not province:
                    continue
                if component_c:
                    component = _norm(row.get(component_c, ""))
                    if component != target_component:
                        continue
                val = _to_float(row.get(value_c, ""))
                if val is None or val <= 0:
                    continue
                buckets[year][province][month] = val

    if not buckets:
        raise SystemExit("Parsed 0 rows from monthly power table.")
    print(f"  Years seen: {sorted(buckets)[:3]} ... {sorted(buckets)[-3:]}")

    # Pick the latest year with 12 months of data for at least 8 provinces.
    target_year = None
    for y in sorted(buckets, reverse=True):
        full_months_provinces = sum(1 for p, mm in buckets[y].items() if len(mm) >= 12)
        if full_months_provinces >= 8:
            target_year = y
            break
    if target_year is None:
        target_year = max(buckets)
    print(f"  Using target year: {target_year}")

    out: dict[str, dict] = {}
    for province in PROVINCE_LABELS.values():
        months = buckets[target_year].get(province) or {}
        if not months:
            continue
        monthly = [int(months.get(m, 0)) for m in range(1, 13)]
        peak_month = max(range(1, 13), key=lambda m: months.get(m, 0))
        out[province] = {
            "year": target_year,
            "monthly_total_mwh": monthly,
            "peak_month": peak_month,
            "peak_month_mwh": int(months.get(peak_month, 0)),
            "annual_total_mwh": int(sum(monthly)),
        }
    return out


HEADER = '''"""
Auto-generated per-province monthly electricity disposition, MWh.
Source: Statistics Canada Table 25-10-0022 ("Electric power, monthly
disposition"), filtered to the "Total electricity available for use
within specific geographic border" component.

For each province: {year, monthly_total_mwh: [Jan..Dec], peak_month,
peak_month_mwh, annual_total_mwh}.

Note: this is monthly granularity, not hourly. Hydro-Québec / EPCOR /
Manitoba Hydro do not publish hourly historical demand as free data,
so the Winter Stress pipeline uses the peak month total here as a
sanity bound on hand-curated city peaks rather than the source of
truth for them.

DO NOT EDIT BY HAND - re-run `python -m
backend.scripts.ingest_statscan_monthly_power`.

Used by:
  - grid/feeder_topology.py — peak-month MWh used to flag hand-curated
    city winter_peak_mw values that imply an implausible energy total
"""

PROVINCIAL_MONTHLY_POWER: dict[str, dict] = {
'''


def emit_python(per_prov: dict[str, dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write(HEADER)
        for province in sorted(per_prov):
            e = per_prov[province]
            f.write(f'    "{province}": {{\n')
            f.write(f'        "year": {e["year"]},\n')
            f.write(f'        "peak_month": {e["peak_month"]},\n')
            f.write(f'        "peak_month_mwh": {e["peak_month_mwh"]},\n')
            f.write(f'        "annual_total_mwh": {e["annual_total_mwh"]},\n')
            f.write(f'        "monthly_total_mwh": {e["monthly_total_mwh"]!r},\n')
            f.write(f'    }},\n')
        f.write("}\n")
    print(f"  Wrote {path}")


def main() -> None:
    zip_path = _download_if_missing()
    per_prov = aggregate(zip_path)
    print(f"  Aggregated {len(per_prov)} provinces.")
    emit_python(per_prov, OUTPUT_FILE)

    print("\nSpot-check (peak-month MWh by province, latest year):")
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    rows = [(p, e["year"], months[e["peak_month"] - 1], e["peak_month_mwh"])
            for p, e in per_prov.items()]
    rows.sort(key=lambda r: -r[3])
    for p, y, m, mwh in rows:
        print(f"  {p} ({y}): peak {m} = {mwh:,} MWh")


if __name__ == "__main__":
    main()
