"""
Ingest AESO Hourly Pool Price + AIL (Alberta Internal Load) historical CSV
from 2020 through latest. Single file satisfies BOTH:
  - Fix #4: real Alberta spot $/MWh for Siting candidates
  - Fix #11: real Alberta peak demand for Winter Stress Edmonton baseline

Source: AESO Market & System Reporting
  https://www.aeso.ca/assets/Uploads/data-requests/Hourly_Metered_Volumes_and_Pool_Price_and_AIL_2020-Jul2025.csv

Usage:

    python -m backend.scripts.ingest_aeso_pool_ail

Cache: data/cache/aeso_pool_ail.csv. Re-run to refresh.
"""

from __future__ import annotations

import csv
import statistics
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

URL = (
    "https://www.aeso.ca/assets/Uploads/data-requests/"
    "Hourly_Metered_Volumes_and_Pool_Price_and_AIL_2020-Jul2025.csv"
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
CACHED_CSV = CACHE_DIR / "aeso_pool_ail.csv"
OUTPUT_FILE = REPO_ROOT / "backend" / "services" / "_aeso_pool_ail_generated.py"


def _download_if_missing() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHED_CSV.exists() and CACHED_CSV.stat().st_size > 100_000:
        print(f"[ok] Using cached CSV at {CACHED_CSV} "
              f"({CACHED_CSV.stat().st_size / 1e6:.1f} MB)")
        return CACHED_CSV
    print(f"[..] Downloading AESO Pool Price + AIL from {URL} ...")
    req = Request(URL, headers={"User-Agent": "Skorpio/1.0 (skorpio@energyplacement.ai)"})
    with urlopen(req) as resp, CACHED_CSV.open("wb") as out:
        while chunk := resp.read(1 << 16):
            out.write(chunk)
    print(f"[ok] Saved to {CACHED_CSV} ({CACHED_CSV.stat().st_size / 1e6:.1f} MB)")
    return CACHED_CSV


def parse(csv_path: Path) -> tuple[list[float], list[float], int | None]:
    """Return (pool_prices, ail_values, latest_year). All values are full hourly
    series across the file's coverage; downstream summary picks the most
    recent year only."""
    prices: list[float] = []
    ail: list[float] = []
    latest_year: int | None = None
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        lines = f.readlines()
    # AESO CSV has no preamble — header is line 0. Column names use
    # underscores ("ACTUAL_POOL_PRICE", "ACTUAL_AIL"), not spaces.
    header_idx = -1
    for i, line in enumerate(lines):
        upper = line.upper()
        if "POOL_PRICE" in upper and "ACTUAL_AIL" in upper:
            header_idx = i
            break
    if header_idx < 0:
        raise SystemExit("Could not find Pool Price header row in AESO CSV.")
    reader = csv.DictReader(lines[header_idx:])
    cols = reader.fieldnames or []
    price_col = next((c for c in cols if "POOL_PRICE" in c.upper()
                                          and "FORECAST" not in c.upper()), None)
    ail_col = next((c for c in cols if c.upper() == "ACTUAL_AIL"
                                        or c.upper() == "AIL"), None)
    date_col = next((c for c in cols if "DATE" in c.upper() or "TIME" in c.upper()),
                    cols[0] if cols else None)
    if not price_col:
        raise SystemExit(f"No Pool Price column among {cols}")
    for row in reader:
        try:
            p = float(row[price_col])
            prices.append(p)
        except (ValueError, TypeError, KeyError):
            pass
        if ail_col:
            try:
                a = float(row[ail_col])
                ail.append(a)
            except (ValueError, TypeError, KeyError):
                pass
        if date_col:
            ds = (row.get(date_col) or "").strip()
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S",
                        "%m/%d/%Y %H:%M"):
                try:
                    dt = datetime.strptime(ds[:len(fmt) + 2], fmt[:len(ds)])
                    if latest_year is None or dt.year > latest_year:
                        latest_year = dt.year
                    break
                except ValueError:
                    continue
    return prices, ail, latest_year


HEADER = '''"""
Auto-generated hourly Alberta Pool Price (CAD/MWh) and Alberta Internal
Load (AIL, MW). Source: AESO published CSV
`Hourly_Metered_Volumes_and_Pool_Price_and_AIL_2020-Jul2025.csv`.

Used by:
  - grid/generator.py (Siting) — real `spot_lmp_usd_mwh` for Alberta candidates
  - grid/feeder_topology.py (Winter Stress) — real Edmonton province-anchor peak
"""

POOL_PRICE_SUMMARY: dict = {
'''


def emit_python(prices: list[float], ail: list[float], latest_year: int | None,
                path: Path) -> None:
    if not prices:
        raise SystemExit("No Pool Price values parsed; refusing to emit empty file.")

    def summary(vals: list[float]) -> dict:
        s = sorted(vals)
        return {
            "count": len(vals),
            "mean": round(statistics.fmean(vals), 2),
            "median": round(statistics.median(vals), 2),
            "p10": round(s[len(s) // 10], 2),
            "p90": round(s[(len(s) * 9) // 10], 2),
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
        }

    price_s = summary(prices)
    ail_s = summary(ail) if ail else None
    with path.open("w", encoding="utf-8") as f:
        f.write(HEADER)
        for k, v in price_s.items():
            f.write(f'    "{k}": {v},\n')
        f.write("}\n\n")
        f.write(f"DATA_YEARS_COVERED: tuple = (2020, {latest_year or 2025})\n\n")
        if ail_s:
            f.write("AIL_SUMMARY_MW: dict = {\n")
            for k, v in ail_s.items():
                f.write(f'    "{k}": {v},\n')
            f.write("}\n")
            # The 95th percentile of AIL is a fair proxy for "winter peak day"
            # without us needing to ship every hour.
            p95 = round(sorted(ail)[(len(ail) * 95) // 100], 1)
            f.write(f"\n# 95th percentile AIL — proxy for a typical extreme-cold-day peak MW.\n")
            f.write(f"AIL_P95_MW: float = {p95}\n")
    print(f"  Wrote {path}")
    print(f"  Pool Price: median={price_s['median']} mean={price_s['mean']} "
          f"p10={price_s['p10']} p90={price_s['p90']} CAD/MWh")
    if ail_s:
        print(f"  AIL: median={ail_s['median']} p95={sorted(ail)[(len(ail) * 95) // 100]:.0f} "
              f"max={ail_s['max']:.0f} MW")


def main() -> None:
    csv_path = _download_if_missing()
    prices, ail, latest_year = parse(csv_path)
    print(f"  Parsed {len(prices)} price rows, {len(ail)} AIL rows.")
    emit_python(prices, ail, latest_year, OUTPUT_FILE)


if __name__ == "__main__":
    main()
